"""Validate DataForSEO catalog entries match upstream API constraints.

DataForSEO has provider-specific rules that generic catalog validation can't catch:

1. Live endpoints (/live) accept exactly 1 task per POST body array — multi-task
   arrays are only supported by async task_post endpoints.

2. Google Trends explore/live does not accept item_types. Vendor docs still list
   google_trends_graph / map / topics_list / queries_list, but a live POST with
   that field returns task status 40501 Invalid Field: 'item_types' and $0.

3. Instant Pages (/on_page/instant_pages) rejects browser_preset unless
   enable_browser_rendering is true. Vendor docs still say enable_javascript *or*
   enable_browser_rendering; live returns 40501 requiring the latter.

These tests ensure catalog test_requests and documentation stay aligned with live behavior.
"""

import pytest
import yaml
from pathlib import Path


CATALOG = Path("src/treg/catalog")


def load_dataforseo_endpoints():
    """Load all DataForSEO endpoints from core and extended catalogs.

    Core is a provider document (`endpoints:` list). Extended is the same
    shape after ingest; a bare list is still accepted.
    """
    endpoints = []

    core_path = CATALOG / "dataforseo.yaml"
    if core_path.exists():
        data = yaml.safe_load(core_path.read_text())
        for ep in data.get("endpoints", []):
            ep["_source"] = "dataforseo.yaml"
            endpoints.append(ep)

    extended_path = CATALOG / "dataforseo.extended.yaml"
    if extended_path.exists():
        data = yaml.safe_load(extended_path.read_text())
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("endpoints", [])
        else:
            items = []
        for ep in items:
            ep["_source"] = "dataforseo.extended.yaml"
            endpoints.append(ep)

    return endpoints


def test_live_endpoints_have_single_task_test_requests():
    """DataForSEO Live endpoints accept exactly 1 task per POST array.

    The upstream API documentation states: "each Live API call can contain only
    one task". Async task_post endpoints support up to 100 tasks, but /live
    endpoints reject multi-task arrays.

    Ref: https://docs.dataforseo.com/v3/backlinks/summary/live/
    """
    endpoints = load_dataforseo_endpoints()
    violations = []

    for ep in endpoints:
        path = ep.get("path", "")
        method = ep.get("method", "")

        if "/live" not in path or method != "POST":
            continue

        test_req = ep.get("test_request", {})
        body = test_req.get("body")

        if body is None:
            continue

        if not isinstance(body, list):
            violations.append(f"{ep['id']}: test_request.body is not a list")
            continue

        if len(body) != 1:
            violations.append(
                f"{ep['id']}: Live endpoint test_request.body has {len(body)} tasks, "
                f"expected exactly 1 (Live endpoints do not support multi-task arrays)"
            )

    assert not violations, "DataForSEO Live endpoints must have exactly 1 task:\n" + "\n".join(violations)


GOOGLE_TRENDS_EXPLORE_LIVE_ID = "dataforseo.x.keywords-data-google-trends-explore-live"


def test_google_trends_explore_live_omits_item_types():
    """Live /keywords_data/google_trends/explore/live rejects item_types (40501).

    Vendor docs still list item_types including google_trends_queries_list.
    A live POST with that field returns HTTP 200 + task status 40501
    Invalid Field: 'item_types' and $0. Feedback #125 / #127.

    Ref: https://docs.dataforseo.com/v3/keywords_data/google_trends/explore/live/
    """
    endpoints = load_dataforseo_endpoints()
    endpoint = next((ep for ep in endpoints if ep.get("id") == GOOGLE_TRENDS_EXPLORE_LIVE_ID), None)
    assert endpoint is not None, f"{GOOGLE_TRENDS_EXPLORE_LIVE_ID} not found"

    body = (endpoint.get("input") or {}).get("body") or {}
    assert "item_types" not in body, (
        f"{GOOGLE_TRENDS_EXPLORE_LIVE_ID}: input.body must not document item_types "
        "(live API rejects the field with 40501)"
    )

    note = (endpoint.get("input") or {}).get("note", "")
    assert "item_types" in note and "do not send" in note.lower(), (
        f"{GOOGLE_TRENDS_EXPLORE_LIVE_ID}: input.note should tell agents not to send item_types"
    )
    assert "serpapi.x.google-trends" in note, (
        f"{GOOGLE_TRENDS_EXPLORE_LIVE_ID}: input.note should point related-query discovery "
        "at the documented serpapi sibling"
    )

    test_req = endpoint.get("test_request") or {}
    tasks = test_req.get("body") or []
    for i, task in enumerate(tasks):
        if isinstance(task, dict):
            assert "item_types" not in task, (
                f"{GOOGLE_TRENDS_EXPLORE_LIVE_ID}: test_request.body[{i}] must not send item_types"
            )


def test_limits_doc_mentions_single_task_for_live():
    """The provider limits string must clarify Live endpoints accept only 1 task."""
    core_path = CATALOG / "dataforseo.yaml"
    data = yaml.safe_load(core_path.read_text())
    limits = data.get("limits", "")

    assert "Live" in limits, "limits should mention Live endpoint behavior"
    assert "1 task" in limits or "exactly 1" in limits or "exactly one task" in limits.lower(), (
        "limits should state that Live endpoints accept exactly 1 task per POST"
    )


@pytest.mark.parametrize("endpoint_id", [
    "dataforseo.web.backlinks.summary",
    "dataforseo.web.backlinks.list",
    "dataforseo.web.linking_domains.list",
    "dataforseo.web.anchors.list",
    "dataforseo.web.url.metrics",
    "dataforseo.web.backlinks.competitors",
    "dataforseo.google.serp.organic",
    "dataforseo.google.keywords.volume",
    "dataforseo.google.keywords.ideas",
    "dataforseo.google.domain.ranked_keywords",
    "dataforseo.web.page.audit",
])
def test_core_live_endpoints_document_single_task_constraint(endpoint_id):
    """Each core Live endpoint's input.note must mention the single-task constraint."""
    core_path = CATALOG / "dataforseo.yaml"
    data = yaml.safe_load(core_path.read_text())

    endpoint = None
    for ep in data.get("endpoints", []):
        if ep.get("id") == endpoint_id:
            endpoint = ep
            break

    assert endpoint is not None, f"Endpoint {endpoint_id} not found"

    input_spec = endpoint.get("input", {})
    note = input_spec.get("note", "")

    assert "exactly 1" in note.lower() or "exactly one task" in note.lower() or "do not support multi-task" in note.lower(), (
        f"{endpoint_id}: input.note should clarify Live endpoints accept exactly 1 task"
    )


PAGE_AUDIT_ID = "dataforseo.web.page.audit"


def test_instant_pages_browser_preset_requires_browser_rendering():
    """Instant Pages rejects browser_preset without enable_browser_rendering (40501).

    Vendor Instant Pages docs still say set enable_javascript *or*
    enable_browser_rendering. Live POST with browser_preset and neither (or
    only enable_javascript) returns HTTP 200 + task status 40501 requiring
    enable_browser_rendering. Feedback #234 / #235: catalog_get advertised
    browser_preset as "desktop | mobile | tablet" with enable_browser_rendering
    as an unrelated Core Web Vitals toggle, so agents sent the preset alone.

    Workaround: omit browser_preset and use enable_javascript only.

    Ref: https://docs.dataforseo.com/v3/on_page/instant_pages/
    """
    core_path = CATALOG / "dataforseo.yaml"
    data = yaml.safe_load(core_path.read_text())
    endpoint = next((ep for ep in data.get("endpoints", []) if ep.get("id") == PAGE_AUDIT_ID), None)
    assert endpoint is not None, f"{PAGE_AUDIT_ID} not found"

    body = (endpoint.get("input") or {}).get("body") or {}
    preset = body.get("browser_preset") or {}
    rendering = body.get("enable_browser_rendering") or {}
    javascript = body.get("enable_javascript") or {}
    note = (endpoint.get("input") or {}).get("note", "")

    assert "enable_browser_rendering" in (preset.get("note") or ""), (
        f"{PAGE_AUDIT_ID}: browser_preset.note must require enable_browser_rendering=true"
    )
    assert "40501" in (preset.get("note") or ""), (
        f"{PAGE_AUDIT_ID}: browser_preset.note should name the live 40501"
    )
    js_note = (javascript.get("note") or "").lower()
    assert "not sufficient" in js_note and "browser_preset" in js_note, (
        f"{PAGE_AUDIT_ID}: enable_javascript.note should say it is not enough for browser_preset"
    )
    assert "browser_preset" in (rendering.get("note") or ""), (
        f"{PAGE_AUDIT_ID}: enable_browser_rendering.note should name browser_preset"
    )
    assert "browser_preset" in note and "enable_browser_rendering" in note, (
        f"{PAGE_AUDIT_ID}: input.note should tell agents not to send browser_preset "
        "without enable_browser_rendering=true"
    )

    test_req = endpoint.get("test_request") or {}
    tasks = test_req.get("body") or []
    for i, task in enumerate(tasks):
        if isinstance(task, dict):
            assert "browser_preset" not in task, (
                f"{PAGE_AUDIT_ID}: test_request.body[{i}] must not send browser_preset "
                "(cheap probe; the field is paid browser-rendering only)"
            )
