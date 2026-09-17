"""Wiza provider registration, bounded platform pricing, BYOK and routing."""

from __future__ import annotations

import json

import httpx
import pytest

from treg import api as A
from treg import oauth_providers as P
from treg.application.call import service as call_service
from treg.application.call.types import UpstreamResponse
from treg.config import Settings, get_settings
from treg.domain.capacity import collectors, policy
from treg.domain.catalog import store as catalog_store


class _JSONStream(httpx.AsyncByteStream):
    def __init__(self, doc):
        self.body = json.dumps(doc).encode()

    async def __aiter__(self):
        yield self.body


def _response(status: int, doc: dict) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"content-type": "application/json"},
        stream=_JSONStream(doc),
    )


async def _balance(clients) -> int:
    org_id = (await clients.get("/orgs")).json()[0]["org_id"]
    return (await clients.get(f"/orgs/{org_id}/balance")).json()["balance_micro"]


async def _entries(clients) -> list[dict]:
    org_id = (await clients.get("/orgs")).json()[0]["org_id"]
    payload = (await clients.get(f"/orgs/{org_id}/balance")).json()
    return payload["entries"]["items"]


@pytest.fixture
def wiza_platform_on(monkeypatch):
    monkeypatch.setenv("TREG_PLATFORM_KEY_WIZA", "PLATFORM-WIZA")
    monkeypatch.setenv("TREG_PLATFORM_PROVIDERS", "wiza")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_wiza_registry_uses_the_free_credit_probe(monkeypatch):
    monkeypatch.setenv("TREG_PLATFORM_KEY_WIZA", "PLATFORM-WIZA")
    monkeypatch.setenv("TREG_PLATFORM_PROVIDERS", "wiza")
    settings = Settings(_env_file=None)
    provider = P.get("wiza")
    assert provider.base_url == "https://wiza.co"
    assert provider.probe_path == "/api/meta/credits"
    assert provider.probe_method == "GET"
    assert settings.platform_key_for("wiza") == "PLATFORM-WIZA"
    assert P.platform_bindings(provider) == [{
        "platform_setting": "platform_key_wiza",
        "injector": "env",
        "location": "header",
        "name": "Authorization",
        "format": "Bearer {secret}",
    }]


async def test_wiza_connection_rejects_bogus_and_accepts_valid_key(clients, monkeypatch):
    def probe(request):
        assert request.url.host == "wiza.co"
        assert request.url.path == "/api/meta/credits"
        token = request.headers["authorization"]
        if token == "Bearer bad":
            return httpx.Response(401, json={"status": {"code": 401, "message": "Invalid API key."}})
        return httpx.Response(200, json={"credits": {"api_credits": 10}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(probe)) as upstream:
        monkeypatch.setattr(A.app.state, "http", upstream)
        bad = await clients.post("/connections/token", json={"provider": "wiza", "token": "bad"})
        assert bad.status_code == 422
        good = await clients.post("/connections/token", json={"provider": "wiza", "token": "own-key"})
        assert good.status_code == 200, good.text

    tools = {tool["name"]: tool for tool in (await clients.get("/tools")).json()}
    assert set(tools) == {"wiza"}
    assert tools["wiza"]["base_url"] == "https://wiza.co"


@pytest.mark.parametrize("remaining", [5000, 0, 12.5])
async def test_wiza_capacity_reads_finite_api_credits(remaining):
    def serve(request):
        assert request.url.path == "/api/meta/credits"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"credits": {"api_credits": remaining}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as upstream:
        row = await collectors._wiza(upstream, "test-key")
    assert row["value"] == remaining
    assert row["unit"] == "API credits"
    assert "auto-top-up is not enabled" in row["note"]
    configured = policy.default_policy("wiza", has_key=True)
    assert configured.capacity_type == "credits"
    assert configured.funding_mode == "manual"
    assert configured.auto_funding_enabled is False
    assert configured.rate_limit == {"limit": 30, "window_s": 60, "source": "docs"}


@pytest.mark.parametrize("remaining", [None, True, -1, "unlimited"])
async def test_wiza_capacity_rejects_unclear_balances(remaining):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"credits": {"api_credits": remaining}}))) as upstream:
        with pytest.raises(ValueError, match="valid API credit balance"):
            await collectors._wiza(upstream, "test-key")


async def test_wiza_capacity_rejects_non_finite_balance():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"credits": {"api_credits": float("inf")}}

    class Client:
        async def get(self, *args, **kwargs):
            return Response()

    with pytest.raises(ValueError, match="valid API credit balance"):
        await collectors._wiza(Client(), "test-key")


def test_wiza_catalog_covers_every_official_path_and_blocks_async_platform_use():
    catalog = catalog_store.load()
    rows = [ep for ep in catalog.endpoints if ep["provider"] == "wiza"]
    assert len(rows) == 12
    assert {ep["path"] for ep in rows} == {
        "/api/lists",
        "/api/lists/{id}",
        "/api/lists/{id}/contacts",
        "/api/individual_reveals",
        "/api/individual_reveals/{id}",
        "/api/prospects/search",
        "/api/prospects/create_prospect_list",
        "/api/prospects/continue_search",
        "/api/accounts/search",
        "/api/meta/location_autocomplete",
        "/api/meta/technology_autocomplete",
        "/api/company_enrichments",
    }
    assert "/api/meta/credits" not in {ep["path"] for ep in rows}
    platform = {ep["id"] for ep in rows if catalog.platform_eligible(ep)}
    assert platform == {
        "wiza.people.search",
        "wiza.companies.search",
        "wiza.companies.enrich",
        "wiza.meta.locations.search",
        "wiza.meta.technologies.search",
    }
    assert {eid for eid, adapter in catalog.adapters.items()
            if eid.startswith("wiza.") and adapter.verified} == {
        "wiza.people.search", "wiza.companies.search", "wiza.companies.enrich",
    }
    assert all(catalog.by_id[eid]["input"]["body"]["size"]["enum"] == [1]
               for eid in ("wiza.people.search", "wiza.companies.search"))
    assert all(catalog.by_id[eid]["input"]["body"]["size"]["required"] is True
               for eid in ("wiza.people.search", "wiza.companies.search"))
    assert all(catalog.by_id[eid]["input"]["body"]["filters"]["required"] is False
               for eid in ("wiza.people.search", "wiza.companies.search"))


@pytest.mark.parametrize(
    "endpoint,body",
    [
        ("wiza.people.search", {"filters": {"job_title": [{"v": "Founder", "s": "i"}]}}),
        ("wiza.companies.search", {
            "filters": {"company_industry": [{"v": "Software", "s": "i"}]},
        }),
    ],
)
async def test_wiza_platform_search_rejects_an_omitted_required_size(
    clients, wiza_platform_on, endpoint, body,
):
    result = await clients.post(f"/call/{endpoint}", json=body)
    assert result.status_code == 400
    assert result.json()["detail"]["error"] == "catalog_parameter_invalid"


@pytest.mark.parametrize(
    "endpoint,request_body,response_body,expected_micro",
    [
        (
            "wiza.companies.enrich",
            {"company_domain": "example.com"},
            {"type": "company_enrichment", "data": {
                "company_name": "Example", "company_domain": "example.com",
                "credits": {"api_credits": {"total": 2, "company_credits": 2}},
            }},
            50_000,
        ),
        (
            "wiza.people.search",
            {"filters": {"job_title": [{"v": "Founder", "s": "i"}]}, "size": 1},
            {"status": {"code": 200}, "data": {
                "total": 1, "profiles": [{"full_name": "Jane Doe"}],
                "next_page_token": "next",
            }},
            12_500,
        ),
        (
            "wiza.companies.search",
            {"filters": {"company_industry": [{"v": "Software", "s": "i"}]}, "size": 1},
            {"status": {"code": 200}, "data": {
                "total": 1, "companies": [{"name": "Example"}],
                "next_page_token": "next",
            }},
            12_500,
        ),
    ],
)
async def test_wiza_platform_success_settles_the_bounded_price(
    clients, monkeypatch, wiza_platform_on, endpoint, request_body, response_body, expected_micro,
):
    def serve(request):
        assert request.headers["authorization"] == "Bearer PLATFORM-WIZA"
        sent = json.loads(request.content)
        if endpoint.endswith("search"):
            assert sent["size"] == 1
        return _response(200, response_body)

    before = await _balance(clients)
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as upstream:
        monkeypatch.setattr(A.app.state, "http", upstream)
        result = await clients.post(f"/call/{endpoint}", json=request_body)
    assert result.status_code == 200, result.text
    assert result.headers["x-treg-cost-micro"] == str(expected_micro)
    assert before - await _balance(clients) == expected_micro
    entries = await _entries(clients)
    assert [entry["kind"] for entry in entries[:2]] == ["settle", "reserve"]


@pytest.mark.parametrize(
    "endpoint,request_body,status,response_body",
    [
        ("wiza.companies.enrich", {}, 400,
         {"status": {"code": 400, "message": "Company identifier required"}}),
        ("wiza.companies.enrich", {"company_domain": "missing.example"}, 404,
         {"status": {"code": 404, "message": "Company not found"}}),
        ("wiza.people.search", {"filters": {"job_title": [{"v": "Missing", "s": "i"}]}, "size": 1}, 200,
         {"status": {"code": 200}, "data": {"total": 0, "profiles": [], "next_page_token": None}}),
        ("wiza.companies.search", {"filters": {"company_industry": [{"v": "Missing", "s": "i"}]}, "size": 1}, 200,
         {"status": {"code": 200}, "data": {"total": 0, "companies": [], "next_page_token": None}}),
    ],
)
async def test_wiza_platform_misses_and_errors_release_the_hold(
    clients, monkeypatch, wiza_platform_on, endpoint, request_body, status, response_body,
):
    before = await _balance(clients)
    monkeypatch.setattr(call_service, "relay", _fake_relay(status, response_body))
    result = await clients.post(f"/call/{endpoint}", json=request_body)
    assert result.status_code == status
    assert result.headers["x-treg-cost-micro"] == "0"
    assert await _balance(clients) == before
    entries = await _entries(clients)
    expected_close = "settle" if status == 200 else "release"
    assert [entry["kind"] for entry in entries[:2]] == [expected_close, "reserve"]


def _fake_relay(status: int, doc: dict):
    async def relay(request, upstream_url, tool, secrets, client, drop_params=None, force_identity=False):
        async def stream():
            yield json.dumps(doc).encode()

        async def close():
            return None

        return UpstreamResponse(status, ((b"content-type", b"application/json"),), stream(), close)

    return relay


async def test_wiza_byok_wins_and_is_not_metered(clients, monkeypatch, wiza_platform_on):
    await clients.post("/secrets", json={"name": "wiza", "value": "OWN-WIZA"})
    seen = []

    def serve(request):
        seen.append(request.headers["authorization"])
        return _response(200, {"type": "company_enrichment", "data": {
            "company_name": "Example", "company_domain": "example.com",
            "credits": {"api_credits": {"total": 2}},
        }})

    before = await _balance(clients)
    async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as upstream:
        monkeypatch.setattr(A.app.state, "http", upstream)
        result = await clients.post(
            "/call/wiza.companies.enrich", json={"company_domain": "example.com"}
        )
    assert result.status_code == 200, result.text
    assert seen == ["Bearer OWN-WIZA"]
    assert "x-treg-cost-micro" not in result.headers
    assert await _balance(clients) == before
