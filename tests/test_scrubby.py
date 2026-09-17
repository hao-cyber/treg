from __future__ import annotations

import json

import httpx
import pytest

from treg import api as A
from treg import oauth_providers as providers
from treg.application.call import service as call_service
from treg.application.call import settle as call_settle
from treg.application.call.resolve import MarketplaceCall
from treg.application.call.types import UpstreamResponse
from treg.config import Settings, get_settings
from treg.domain.capacity import collectors
from treg.domain.catalog import store as catalog_store


def _mk(*, endpoint_id="scrubby.people.email.verify", unit_micro=8_000):
    return MarketplaceCall(
        tool=None, upstream="https://api.scrubby.io/validate_email", consumed=set(),
        provider="scrubby", endpoint_id=endpoint_id, tier="platform",
        estimate_micro=unit_micro, cost_type="per_success", unit_micro=unit_micro,
        request_data={},
    )


def _relay(status: int, doc: dict):
    async def relay(*args, **kwargs):
        async def stream():
            yield json.dumps(doc).encode()

        async def close():
            return None

        return UpstreamResponse(status, ((b"content-type", b"application/json"),), stream(), close)
    return relay


async def _balance(clients):
    org_id = (await clients.get("/orgs")).json()[0]["org_id"]
    return (await clients.get(f"/orgs/{org_id}/balance")).json()["balance_micro"]


def test_scrubby_catalog_covers_the_documented_surface():
    catalog = catalog_store.load()
    endpoints = {eid: ep for eid, ep in catalog.by_id.items() if eid.startswith("scrubby.")}
    assert set(endpoints) == {
        "scrubby.people.email.verify",
        "scrubby.people.email.verify.bulk",
        "scrubby.people.email.verify.bulk.results",
        "scrubby.people.email.verify.deep",
        "scrubby.people.email.verify.deep.results",
    }
    assert endpoints["scrubby.people.email.verify"]["path"] == "/validate_email"
    assert "ownership" in endpoints["scrubby.people.email.verify.bulk"]["platform_blocked"]
    assert "ownership" in endpoints["scrubby.people.email.verify.deep"]["platform_blocked"]
    assert catalog.cost_view(endpoints["scrubby.people.email.verify"]["cost"], "scrubby")["usd"] == 0.008
    assert catalog.cost_view(endpoints["scrubby.people.email.verify.deep"]["cost"], "scrubby")["usd"] == 0.024


@pytest.mark.parametrize("credits,expected", [(0, 0), (1, 8_000), (3, 24_000), (-1, None), (True, None), (1.5, None), (None, None)])
def test_scrubby_settles_from_reported_credits(credits, expected):
    body = json.dumps({"result": "Valid", "credits_used": credits}).encode()
    assert call_settle._observed_cost_micro(_mk(), body) == expected


def test_scrubby_registry_and_platform_key(monkeypatch):
    monkeypatch.setenv("TREG_PLATFORM_KEY_SCRUBBY", "PLATFORM-SCRUBBY")
    monkeypatch.setenv("TREG_PLATFORM_PROVIDERS", "scrubby")
    provider = providers.get("scrubby")
    settings = Settings(_env_file=None)
    assert provider.base_url == "https://api.scrubby.io"
    assert provider.probe_path == "/fetch_bulk_results"
    assert provider.probe_json == {"identifier": "treg-probe-not-found"}
    assert provider.token_ok_value == "No results found for this identifier."
    assert provider.probe_reject_statuses == (401, 403)
    assert settings.platform_key_for("scrubby") == "PLATFORM-SCRUBBY"
    assert providers.platform_bindings(provider) == [
        {
            "platform_setting": "platform_key_scrubby", "injector": "env",
            "location": "header", "name": "x-api-key", "format": "{secret}",
        },
        {
            "platform_setting": "platform_key_scrubby", "injector": "env",
            "location": "header", "name": "User-Agent", "format": "treg/1.0 (+https://treg.to)",
        },
    ]


async def test_scrubby_balance_report_names_the_absent_standalone_api(monkeypatch):
    monkeypatch.setenv("TREG_PLATFORM_KEY_SCRUBBY", "PLATFORM-SCRUBBY")
    get_settings.cache_clear()
    row = await collectors.provider_balance("scrubby")
    assert row["no_api"] is True
    assert row["value"] is None
    assert "no free standalone balance or usage endpoint" in row["note"]
    assert "no fetcher written yet" not in row["note"]
    get_settings.cache_clear()


async def test_scrubby_connection_rejects_bogus_and_accepts_valid(clients, monkeypatch):
    def probe(request):
        assert request.url.path == "/fetch_bulk_results"
        assert request.headers["user-agent"] == "treg/1.0 (+https://treg.to)"
        if request.headers["x-api-key"] == "bad":
            return httpx.Response(401, json={"detail": "Invalid API key"})
        return httpx.Response(404, json={"detail": "No results found for this identifier."})

    async with httpx.AsyncClient(transport=httpx.MockTransport(probe)) as upstream:
        monkeypatch.setattr(A.app.state, "http", upstream)
        bad = await clients.post("/connections/token", json={"provider": "scrubby", "token": "bad"})
        assert bad.status_code == 422
        good = await clients.post("/connections/token", json={"provider": "scrubby", "token": "own-key"})
        assert good.status_code == 200, good.text


async def test_scrubby_platform_settles_exact_usage_and_byok_wins(clients, monkeypatch):
    monkeypatch.setenv("TREG_PLATFORM_KEY_SCRUBBY", "PLATFORM-SCRUBBY")
    monkeypatch.setenv("TREG_PLATFORM_PROVIDERS", "scrubby")
    get_settings.cache_clear()
    monkeypatch.setattr(call_service, "relay", _relay(200, {
        "email": "a@example.com", "result": "Invalid", "status": "HARD_BOUNCE",
        "quick_status": "HARD_BOUNCE", "credits_used": 1, "remaining_credits": 9,
    }))
    before = await _balance(clients)
    response = await clients.post("/call/scrubby.people.email.verify", json={"email": "a@example.com"})
    assert response.status_code == 200, response.text
    assert response.headers["x-treg-cost-micro"] == "8000"
    assert await _balance(clients) == before - 8_000

    await clients.post("/secrets", json={"name": "scrubby", "value": "OWN-SCRUBBY"})
    before_byok = await _balance(clients)
    response = await clients.post("/call/scrubby.people.email.verify", json={"email": "a@example.com"})
    assert response.status_code == 200
    assert "x-treg-cost-micro" not in response.headers
    assert await _balance(clients) == before_byok
    get_settings.cache_clear()


def test_scrubby_adapter_maps_all_verdicts_as_answers():
    adapter = catalog_store.load().adapters["scrubby.people.email.verify"]
    for result, valid in (("Valid", True), ("Invalid", False), ("Risky", False), ("Unknown", False)):
        doc = {"result": result}
        assert not adapter.is_miss(doc)
        assert adapter.from_upstream(doc)["valid"] is valid
        assert adapter.from_upstream(doc)["status"] == result
    assert adapter.is_miss({})
