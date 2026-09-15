"""Financial Datasets v1: catalog surface, routing, metering and BYOK precedence."""

from __future__ import annotations

import json

import pytest

from treg.application.call import service as call_service
from treg import providers as env_providers
from treg.config import get_settings
from treg.domain.capacity import signatures
from treg.domain.capacity.collectors import NO_BALANCE_API, all_platform_providers, provider_balance
from treg.domain.capacity.policy import default_policy, policy_population
from treg.domain.catalog import store as catalog_store

from test_marketplace_call import _balance, _fake_relay, _telemetry


DATA = {
    "financialdatasets.company.facts",
    "financialdatasets.financials",
    "financialdatasets.financials.income-statements",
    "financialdatasets.financials.balance-sheets",
    "financialdatasets.financials.cash-flow-statements",
    "financialdatasets.financials.income-statements.segments",
    "financialdatasets.financial-metrics",
    "financialdatasets.financial-metrics.snapshot",
    "financialdatasets.earnings",
    "financialdatasets.filings",
    "financialdatasets.prices",
    "financialdatasets.prices.snapshot",
    "financialdatasets.news",
    "financialdatasets.insider-trades",
    "financialdatasets.institutional-holdings",
    "financialdatasets.financials.search.screener",
    "financialdatasets.macro.interest-rates",
    "financialdatasets.kpi.metrics",
    "financialdatasets.kpi.guidance",
    "financialdatasets.kpi.non-gaap",
    "financialdatasets.ipos",
}

DISCOVERY = {
    "financialdatasets.company.facts.tickers",
    "financialdatasets.company.facts.ciks",
    "financialdatasets.prices.tickers",
    "financialdatasets.prices.snapshot.tickers",
    "financialdatasets.earnings.tickers",
    "financialdatasets.filings.tickers",
    "financialdatasets.filings.ciks",
    "financialdatasets.filings.types",
    "financialdatasets.financial-metrics.snapshot.tickers",
    "financialdatasets.financials.search.screener.filters",
    "financialdatasets.macro.interest-rates.banks",
    "financialdatasets.institutional-holdings.tickers",
    "financialdatasets.institutional-holdings.investors",
}

STANDARD = DATA - {
    "financialdatasets.kpi.metrics",
    "financialdatasets.kpi.guidance",
    "financialdatasets.kpi.non-gaap",
    "financialdatasets.ipos",
}
PREMIUM = {
    "financialdatasets.kpi.metrics",
    "financialdatasets.kpi.guidance",
    "financialdatasets.kpi.non-gaap",
    "financialdatasets.ipos",
}

PAGINATED = {
    "financialdatasets.financials",
    "financialdatasets.financials.income-statements",
    "financialdatasets.financials.balance-sheets",
    "financialdatasets.financials.cash-flow-statements",
    "financialdatasets.financials.income-statements.segments",
    "financialdatasets.financial-metrics",
    "financialdatasets.earnings",
    "financialdatasets.filings",
    "financialdatasets.prices",
    "financialdatasets.news",
    "financialdatasets.insider-trades",
    "financialdatasets.institutional-holdings",
    "financialdatasets.kpi.metrics",
    "financialdatasets.kpi.guidance",
    "financialdatasets.kpi.non-gaap",
    "financialdatasets.ipos",
}


@pytest.fixture
def financialdatasets_on(monkeypatch):
    monkeypatch.setenv("TREG_PLATFORM_KEY_FINANCIALDATASETS", "PLATFORM-FD-KEY")
    monkeypatch.setenv("TREG_PLATFORM_PROVIDERS", "financialdatasets")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_v1_catalog_is_the_locked_34_tool_surface():
    cat = catalog_store.load()
    endpoints = cat.for_provider("financialdatasets")
    assert {ep["id"] for ep in endpoints} == DATA | DISCOVERY
    assert len(endpoints) == 34
    assert all(ep["domain"] == "stocks" and ep["platform"] == "stocks" for ep in endpoints)
    assert all(ep["scope"] == "any_account" and not ep["status"] for ep in endpoints)

    paths = {ep["path"] for ep in endpoints}
    assert "/earnings/press-releases" not in paths
    assert not any(path.startswith("/filings/items") for path in paths)
    assert "/agent/signup" not in paths and "/agent/checkout-link" not in paths


def test_env_import_recognizes_financialdatasets_and_builds_the_raw_header(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FINANCIALDATASETS_API_KEY=never-read-by-scan\n", encoding="utf-8")
    [detection] = env_providers.scan_env(str(env))
    assert detection.provider == "Financial Datasets" and detection.kind == "matched"
    [action] = env_providers.plan_actions([detection])
    assert action.tool_name == "financial-datasets"
    assert action.base_url == "https://api.financialdatasets.ai"
    assert action.binding == {
        "injector": "env", "location": "header", "name": "X-API-KEY", "format": "{secret}",
    }


def test_v1_prices_match_the_observed_provider_ledger_charges():
    cat = catalog_store.load()
    for endpoint_id in DISCOVERY:
        ep = cat.by_id[endpoint_id]
        cost = cat.cost_view(ep["cost"], ep["provider"])
        assert cost["usd"] == 0
        assert cost["source"] == "observed" and cost["confidence"] == "verified"
        assert cat.platform_eligible(ep)
        assert ep["platform_auth"] == "anonymous"
    for endpoint_id in STANDARD:
        ep = cat.by_id[endpoint_id]
        cost = cat.cost_view(ep["cost"], ep["provider"])
        assert cost["type"] == "per_success" and cost["usd"] == 0.02
        assert cost["source"] == "observed" and cost["confidence"] == "verified"
        assert cat.platform_eligible(ep)
    for endpoint_id in PREMIUM:
        ep = cat.by_id[endpoint_id]
        cost = cat.cost_view(ep["cost"], ep["provider"])
        assert cost["type"] == "per_success" and cost["usd"] == 0.16
        assert cost["source"] == "observed" and cost["confidence"] == "verified"
        assert cat.platform_eligible(ep)


def test_only_snapshot_joins_the_existing_quote_route():
    cat = catalog_store.load()
    adapter = cat.adapters["financialdatasets.prices.snapshot"]
    assert adapter.verified, adapter.verify_note
    query, body = adapter.to_upstream({"symbol": "aapl"})
    assert query == {"ticker": "AAPL"} and body == {}
    upstream = {"snapshot": {"ticker": "AAPL", "price": 334.48, "day_change": 2.21}}
    assert adapter.from_upstream(upstream) == {
        "price": 334.48,
        "quote": upstream["snapshot"],
    }
    routed = cat.by_id["treg.stocks.quote.live"]
    assert routed["routed_children"].count("financialdatasets.prices.snapshot") == 1
    assert "treg.stocks.company.profile" not in cat.by_id


def test_coverage_copy_is_scoped_and_discovery_is_supporting_utility():
    cat = catalog_store.load()
    assert all(cat.by_id[eid]["kind"] == "utility" for eid in DISCOVERY)
    for ep in cat.for_provider("financialdatasets"):
        ticker = (ep["input"].get("queryParams") or {}).get("ticker")
        if ticker:
            assert "US stock ticker" in ticker.get("note", ""), ep["id"]
    assert "central bank" in cat.by_id["financialdatasets.macro.interest-rates"]["summary"]


def test_data_inputs_name_their_matching_discovery_utilities():
    cat = catalog_store.load()
    expected = {
        "financialdatasets.company.facts": (
            "financialdatasets.company.facts.tickers",
            "financialdatasets.company.facts.ciks",
        ),
        "financialdatasets.financial-metrics.snapshot": (
            "financialdatasets.financial-metrics.snapshot.tickers",
        ),
        "financialdatasets.earnings": ("financialdatasets.earnings.tickers",),
        "financialdatasets.filings": (
            "financialdatasets.filings.tickers",
            "financialdatasets.filings.ciks",
            "financialdatasets.filings.types",
        ),
        "financialdatasets.prices": ("financialdatasets.prices.tickers",),
        "financialdatasets.prices.snapshot": (
            "financialdatasets.prices.snapshot.tickers",
        ),
        "financialdatasets.institutional-holdings": (
            "financialdatasets.institutional-holdings.tickers",
            "financialdatasets.institutional-holdings.investors",
        ),
        "financialdatasets.financials.search.screener": (
            "financialdatasets.financials.search.screener.filters",
        ),
        "financialdatasets.macro.interest-rates": (
            "financialdatasets.macro.interest-rates.banks",
        ),
    }
    for endpoint_id, utility_ids in expected.items():
        guidance = json.dumps(cat.by_id[endpoint_id]["input"])
        assert all(utility_id in guidance for utility_id in utility_ids), endpoint_id


def test_paginated_inputs_explain_how_to_continue_from_next_page_url():
    cat = catalog_store.load()
    actual = {
        endpoint_id
        for endpoint_id in DATA
        if "cursor" in (cat.by_id[endpoint_id]["input"].get("queryParams") or {})
    }
    assert actual == PAGINATED
    for endpoint_id in PAGINATED:
        note = cat.by_id[endpoint_id]["input"]["queryParams"]["cursor"]["note"]
        assert "next_page_url" in note
        assert "omit the original filters" in note


async def test_capacity_uses_the_existing_no_balance_api_policy_and_generic_402_signal(
    financialdatasets_on,
):
    assert "financialdatasets" in NO_BALANCE_API
    assert "financialdatasets" in all_platform_providers()
    assert "financialdatasets" in policy_population()
    balance = await provider_balance("financialdatasets")
    assert balance["no_api"] is True and balance["value"] is None
    policy = default_policy("financialdatasets", has_key=True)
    assert (policy.capacity_type, policy.funding_mode, policy.source) == (
        "credits", "auto_recharge", "manual",
    )
    signal = signatures.classify("financialdatasets", 402, {}, b'{"detail":"Insufficient credits"}')
    assert signal.kind == "balance"


@pytest.mark.parametrize(("endpoint", "params", "body", "charge"), [
    (
        "financialdatasets.prices.snapshot", {"ticker": "AAPL"},
        b'{"snapshot":{"ticker":"AAPL","price":334.48}}', 20_000,
    ),
    (
        "financialdatasets.company.facts", {"ticker": "AAPL"},
        b'{"company_facts":{"ticker":"AAPL"}}', 20_000,
    ),
    (
        "financialdatasets.kpi.metrics", {"ticker": "DAL", "limit": 1},
        b'{"kpi_metrics":[{"ticker":"DAL","value":84.0}]}', 160_000,
    ),
])
async def test_platform_success_settles_the_rate_card(
    clients, financialdatasets_on, monkeypatch, endpoint, params, body, charge,
):
    monkeypatch.setattr(call_service, "relay", _fake_relay(200, body))
    before = await _balance(clients)
    response = await clients.get(f"/call/{endpoint}", params=params)
    assert response.status_code == 200, response.text
    assert response.headers["X-Treg-Cost-Micro"] == str(charge)
    assert await _balance(clients) == before - charge


async def test_anonymous_discovery_uses_no_provider_key_and_does_not_change_the_balance(
    clients, financialdatasets_on, monkeypatch,
):
    seen = {}
    fake = _fake_relay(200, b'{"tickers":["AAPL"]}')

    async def capture(*args, **kwargs):
        seen["bindings"] = args[2].bindings
        seen["secrets"] = args[3]
        return await fake(*args, **kwargs)

    monkeypatch.setattr(call_service, "relay", capture)
    before = await _balance(clients)
    response = await clients.get("/call/financialdatasets.prices.tickers")
    assert response.status_code == 200, response.text
    assert "X-Treg-Cost-Micro" not in response.headers
    assert await _balance(clients) == before
    assert seen == {"bindings": [], "secrets": {}}
    assert (await _telemetry(clients))["credential_tier"] == "anonymous"

    access = (await clients.get(
        "/catalog/endpoints/financialdatasets.prices.tickers/access"
    )).json()
    assert access["tier"] == "anonymous" and access["metered"] is False
    detail = (await clients.get(
        "/catalog/endpoints/financialdatasets.prices.tickers"
    )).json()
    assert detail["endpoint"]["platform_auth"] == "anonymous"
    assert any("no provider key required" in hint for hint in detail["hints"])


async def test_anonymous_discovery_needs_the_provider_allowlist_but_not_a_platform_key(
    clients, monkeypatch,
):
    monkeypatch.setenv("TREG_PLATFORM_PROVIDERS", "financialdatasets")
    monkeypatch.setenv("TREG_PLATFORM_KEY_FINANCIALDATASETS", "")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(call_service, "relay", _fake_relay(200, b'{"tickers":["AAPL"]}'))
        response = await clients.get("/call/financialdatasets.prices.tickers")
        assert response.status_code == 200
        assert (await _telemetry(clients))["credential_tier"] == "anonymous"
    finally:
        get_settings.cache_clear()


async def test_own_financialdatasets_key_still_wins_for_an_anonymous_capable_tool(
    clients, financialdatasets_on, monkeypatch,
):
    await clients.post("/secrets", json={"name": "financialdatasets", "value": "OWN-FD-KEY"})
    seen = {}
    fake = _fake_relay(200, b'{"tickers":["AAPL"]}')

    async def capture(*args, **kwargs):
        seen["bindings"] = args[2].bindings
        seen["secrets"] = args[3]
        return await fake(*args, **kwargs)

    monkeypatch.setattr(call_service, "relay", capture)
    before = await _balance(clients)
    response = await clients.get("/call/financialdatasets.prices.tickers")
    assert response.status_code == 200
    assert await _balance(clients) == before
    assert seen["bindings"] and seen["secrets"]
    assert (await _telemetry(clients))["credential_tier"] == "credential"


async def test_existing_router_can_plan_a_generic_anonymous_child(
    clients, monkeypatch,
):
    cat = catalog_store.load()
    endpoint = cat.by_id["financialdatasets.prices.snapshot"]
    monkeypatch.setitem(endpoint, "platform_auth", "anonymous")
    monkeypatch.setitem(endpoint, "cost", {
        "type": "free", "value": 0, "currency": "USD", "unit": "call",
    })
    monkeypatch.setenv("TREG_PLATFORM_PROVIDERS", "financialdatasets")
    monkeypatch.setenv("TREG_PLATFORM_KEY_FINANCIALDATASETS", "")
    get_settings.cache_clear()
    try:
        monkeypatch.setattr(
            call_service, "relay",
            _fake_relay(200, b'{"snapshot":{"ticker":"AAPL","price":334.48}}'),
        )
        response = await clients.post(
            "/call/treg.stocks.quote.live", json={"symbol": "AAPL"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["_treg"]["tier"] == "anonymous"
        assert await _balance(clients) == 1_000_000
        access = (await clients.get(
            "/catalog/endpoints/treg.stocks.quote.live/access"
        )).json()
        assert access["tier"] == "routed"
        assert "verified public upstream route, no provider key" in access["detail"]
        assert "treg's financialdatasets key" not in access["detail"]
    finally:
        get_settings.cache_clear()


async def test_platform_402_releases_the_hold_without_charging(
    clients, financialdatasets_on, monkeypatch,
):
    monkeypatch.setattr(
        call_service, "relay",
        _fake_relay(402, b'{"detail":"Insufficient credits"}'),
    )
    before = await _balance(clients)
    response = await clients.get(
        "/call/financialdatasets.prices.snapshot", params={"ticker": "AAPL"},
    )
    assert response.status_code == 402
    assert response.headers["X-Treg-Cost-Micro"] == "0"
    assert await _balance(clients) == before


async def test_existing_quote_route_can_serve_through_financialdatasets(
    clients, financialdatasets_on, monkeypatch,
):
    snapshot = {"snapshot": {"ticker": "AAPL", "price": 334.48, "day_change": 2.21}}
    monkeypatch.setattr(call_service, "relay", _fake_relay(200, json.dumps(snapshot).encode()))
    before = await _balance(clients)
    response = await clients.post("/call/treg.stocks.quote.live", json={"symbol": "AAPL"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["output"] == {"price": 334.48, "quote": snapshot["snapshot"]}
    assert body["raw"] == snapshot
    assert body["_treg"]["served_by"] == "financialdatasets.prices.snapshot"
    assert body["_treg"]["charged_micro"] == 20_000
    assert await _balance(clients) == before - 20_000


async def test_byok_wins_and_is_unmetered(clients, financialdatasets_on):
    await clients.post(
        "/secrets", json={"name": "financialdatasets", "value": "OWN-FD-KEY"},
    )
    before = await _balance(clients)
    response = await clients.get(
        "/call/financialdatasets.prices.snapshot", params={"ticker": "AAPL"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["headers"]["x-api-key"] == "OWN-FD-KEY"
    assert "X-Treg-Cost-Micro" not in response.headers
    assert await _balance(clients) == before
