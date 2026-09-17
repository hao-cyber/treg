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

4. LLM Mentions single-target `target` is an AND-combined filter that yields one
   metrics series, not one series per brand. Brand comparison is
   multi-target-metrics-live (`targets` with keys) or one call per brand.

5. LLM Mentions multi-target-metrics-live `targets` must contain between 2 and 10
   keyed sets. Extra items return task status 40501. The live route is a rolling
   window, not monthly history.

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


GOOGLE_AI_MODE_LIVE_ID = "dataforseo.x.serp-google-ai-mode-live-advanced"


def test_google_ai_mode_live_documents_single_task_constraint():
    """Feedback #94: /serp/google/ai_mode/live/advanced accepts exactly one task.

    catalog_get reused the generic "ARRAY of task objects — one object per task"
    note, so agents batched keywords and got HTTP 200 with the first task OK and
    per-task 40000 "You can set only one task at a time" on the rest. Same class
    as backlinks/summary/live (#102 / #487). Settlement is unchanged; do not
    auto-split a multi-task array.

    Ref: https://docs.dataforseo.com/v3/serp/google/ai_mode/live/advanced/
    """
    endpoints = load_dataforseo_endpoints()
    endpoint = next((ep for ep in endpoints if ep.get("id") == GOOGLE_AI_MODE_LIVE_ID), None)
    assert endpoint is not None, f"{GOOGLE_AI_MODE_LIVE_ID} not found"
    assert endpoint.get("path") == "/serp/google/ai_mode/live/advanced"

    note = (endpoint.get("input") or {}).get("note", "")
    assert "exactly one task" in note.lower() or "exactly 1 task" in note.lower(), (
        f"{GOOGLE_AI_MODE_LIVE_ID}: input.note must name the single-task cap"
    )
    assert "40000" in note, (
        f"{GOOGLE_AI_MODE_LIVE_ID}: input.note should name the live 40000"
    )
    assert "one object per task" not in note.lower(), (
        f"{GOOGLE_AI_MODE_LIVE_ID}: generic 'one object per task' wording still "
        "reads as multi-task batching"
    )

    test_req = endpoint.get("test_request") or {}
    tasks = test_req.get("body")
    assert isinstance(tasks, list) and len(tasks) == 1, (
        f"{GOOGLE_AI_MODE_LIVE_ID}: test_request.body must be a one-element array"
    )


CLAUDE_LLM_RESPONSES_LIVE_ID = (
    "dataforseo.x.ai-optimization-claude-llm-responses-live"
)
LLM_RESPONSES_LIVE_IDS = (
    "dataforseo.x.ai-optimization-chat-gpt-llm-responses-live",
    CLAUDE_LLM_RESPONSES_LIVE_ID,
    "dataforseo.x.ai-optimization-gemini-llm-responses-live",
    "dataforseo.x.ai-optimization-perplexity-llm-responses-live",
)


def test_claude_llm_responses_live_documents_working_model():
    """Feedback #358: Claude live model_name example must be a currently accepted name.

    catalog_get advertised claude-opus-4-0 (and implied bare aliases resolve to
    the latest version). Live POST with those values returns HTTP 200 + task
    status 40501 Invalid Field: 'model_name'. Reporter verified claude-sonnet-4-5
    works. The captured example_response was that 40501 body and must not ship
    as a normal example.

    Ref: https://docs.dataforseo.com/v3/ai_optimization/claude/llm_responses/models/
    """
    endpoints = load_dataforseo_endpoints()
    endpoint = next(
        (ep for ep in endpoints if ep.get("id") == CLAUDE_LLM_RESPONSES_LIVE_ID), None
    )
    assert endpoint is not None, f"{CLAUDE_LLM_RESPONSES_LIVE_ID} not found"
    assert endpoint.get("path") == "/ai_optimization/claude/llm_responses/live"

    body = (endpoint.get("input") or {}).get("body") or {}
    model = body.get("model_name") or {}
    assert model.get("example") == "claude-sonnet-4-5", (
        f"{CLAUDE_LLM_RESPONSES_LIVE_ID}: model_name.example must be a currently "
        "accepted name, not claude-opus-4-0"
    )
    note = model.get("note") or ""
    assert "40501" in note or "llm_responses/models" in note, (
        f"{CLAUDE_LLM_RESPONSES_LIVE_ID}: model_name.note must mention 40501 or "
        "the Models endpoint"
    )

    test_req = endpoint.get("test_request") or {}
    tasks = test_req.get("body")
    assert isinstance(tasks, list) and len(tasks) == 1, (
        f"{CLAUDE_LLM_RESPONSES_LIVE_ID}: test_request.body must be a one-element array"
    )
    assert tasks[0].get("model_name") == "claude-sonnet-4-5", (
        f"{CLAUDE_LLM_RESPONSES_LIVE_ID}: test_request.body[0].model_name must be "
        "claude-sonnet-4-5"
    )

    example_rel = endpoint.get("example_response")
    if example_rel:
        example_path = CATALOG / example_rel
        assert example_path.is_file(), (
            f"{CLAUDE_LLM_RESPONSES_LIVE_ID}: declared example_response is missing"
        )
        payload = example_path.read_text()
        assert "40501" not in payload, (
            f"{CLAUDE_LLM_RESPONSES_LIVE_ID}: example_response must not advertise "
            "the 40501 Invalid Field failure"
        )
    else:
        leftover = CATALOG / "examples" / f"{CLAUDE_LLM_RESPONSES_LIVE_ID}.json"
        assert not leftover.is_file(), (
            f"{CLAUDE_LLM_RESPONSES_LIVE_ID}: leftover 40501 example JSON still on disk"
        )
        assert not endpoint.get("verified"), (
            f"{CLAUDE_LLM_RESPONSES_LIVE_ID}: verified requires a real success "
            "example_response; do not keep the 40501 capture"
        )


def test_llm_responses_live_documents_single_task_constraint():
    """Feedback #141 (catalog): LLM-responses Live routes accept exactly one task.

    catalog_get reused the generic "ARRAY of task objects — one object per task"
    note, so agents batched prompts and got HTTP 200 with the first task OK and
    per-task 40000 "You can set only one task at a time" on the rest. Same class
    as ai_mode/live/advanced (#94) and backlinks/summary/live (#102 / #487).
    Settlement is unchanged; do not auto-split a multi-task array.

    Ref: https://docs.dataforseo.com/v3/ai_optimization/claude/llm_responses/live/
    """
    endpoints = {ep.get("id"): ep for ep in load_dataforseo_endpoints()}
    for endpoint_id in LLM_RESPONSES_LIVE_IDS:
        endpoint = endpoints.get(endpoint_id)
        assert endpoint is not None, f"{endpoint_id} not found"
        note = (endpoint.get("input") or {}).get("note", "")
        assert "exactly one task" in note.lower() or "exactly 1 task" in note.lower(), (
            f"{endpoint_id}: input.note must name the single-task cap"
        )
        assert "40000" in note, (
            f"{endpoint_id}: input.note should name the live 40000"
        )
        assert "one object per task" not in note.lower(), (
            f"{endpoint_id}: generic 'one object per task' wording still "
            "reads as multi-task batching"
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


LLM_MENTIONS_MULTI_TARGET_ID = (
    "dataforseo.x.ai-optimization-llm-mentions-multi-target-metrics-live"
)
LLM_MENTIONS_HISTORICAL_ID = (
    "dataforseo.x.ai-optimization-llm-mentions-historical-live"
)
STALE_LLM_MENTIONS_TARGET_NOTE = (
    "array of objects containing target entities required field you can specify up to 10 entities"
)


def test_llm_mentions_target_is_and_combined_filter():
    """Feedback #218: single-target llm-mentions `target` is AND-combined, not multi-series.

    Agents read "up to 10 entities" as one series per brand and sent many brands
    in one call. Upstream AND-combines include/exclude entities into one filter /
    one metrics series. Official docs:
    https://docs.dataforseo.com/v3/ai_optimization/llm_mentions/historical/live/
    (exclude wikipedia + keyword bmw as a filter combo). Brand comparison is
    multi-target-metrics-live (`targets` with keys) or one call per brand.
    Settlement is unchanged.

    Ref: https://docs.dataforseo.com/v3/ai_optimization/llm_mentions/historical/live/
    """
    endpoints = load_dataforseo_endpoints()
    mentions = [ep for ep in endpoints if "llm-mentions" in (ep.get("id") or "")]
    assert mentions, "expected llm-mentions endpoints in the DataForSEO catalog"

    multi = next((ep for ep in mentions if ep.get("id") == LLM_MENTIONS_MULTI_TARGET_ID), None)
    assert multi is not None, f"{LLM_MENTIONS_MULTI_TARGET_ID} not found"
    multi_body = (multi.get("input") or {}).get("body") or {}
    assert "targets" in multi_body, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: brand comparison uses `targets`, not `target`"
    )
    assert "target" not in multi_body, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: must keep the `targets` field; do not rewrite as `target`"
    )

    single_series = []
    for ep in mentions:
        if ep.get("id") == LLM_MENTIONS_MULTI_TARGET_ID:
            continue
        body = (ep.get("input") or {}).get("body") or {}
        if "target" in body:
            single_series.append(ep)

    assert len(single_series) >= 14, (
        f"expected ~14 single-target llm-mentions routes with `target`, got "
        f"{len(single_series)}: {[ep['id'] for ep in single_series]}"
    )

    for ep in single_series:
        field = ((ep.get("input") or {}).get("body") or {}).get("target") or {}
        note = field.get("note") or ""
        assert STALE_LLM_MENTIONS_TARGET_NOTE not in note, (
            f"{ep['id']}: stale target.note still reads as multi-series"
        )
        lower = note.lower()
        assert "up to 10" in lower, f"{ep['id']}: target.note should keep the 10-entity cap"
        assert "domain" in lower and "keyword" in lower, (
            f"{ep['id']}: target.note should keep domain-OR-keyword entity shape"
        )
        assert "and-combined" in lower, (
            f"{ep['id']}: target.note must say target entities are AND-combined"
        )
        assert "one series" in lower or "one metrics series" in lower, (
            f"{ep['id']}: target.note must say one filter / one metrics series"
        )
        assert LLM_MENTIONS_MULTI_TARGET_ID in note, (
            f"{ep['id']}: target.note should point brand comparison at "
            f"{LLM_MENTIONS_MULTI_TARGET_ID}"
        )

        example = field.get("example") or []
        if example:
            # keep the documented exclude-wikipedia + bmw filter combo where present
            domains = [item.get("domain") for item in example if isinstance(item, dict)]
            keywords = [item.get("keyword") for item in example if isinstance(item, dict)]
            if "en.wikipedia.org" in domains:
                assert "bmw" in keywords, (
                    f"{ep['id']}: wikipedia example must stay paired with keyword bmw "
                    "(filter combination, not multi-brand series)"
                )


def test_llm_mentions_historical_summary_names_and_semantics():
    """Feedback #218: historical-live summary must not imply multi-entity measurement."""
    endpoints = load_dataforseo_endpoints()
    endpoint = next((ep for ep in endpoints if ep.get("id") == LLM_MENTIONS_HISTORICAL_ID), None)
    assert endpoint is not None, f"{LLM_MENTIONS_HISTORICAL_ID} not found"
    summary = (endpoint.get("summary") or "").lower()
    assert "and-combined" in summary, (
        f"{LLM_MENTIONS_HISTORICAL_ID}: summary should name AND-combined target filter"
    )
    assert "one series" in summary, (
        f"{LLM_MENTIONS_HISTORICAL_ID}: summary should say one series, not one per brand"
    )


def test_llm_mentions_multi_target_targets_bound():
    """Feedback #490: multi-target-metrics-live `targets` is 2-10 keyed sets.

    catalog_get documented the array shape/example but omitted the length
    constraint, so agents sent 14 targets and got upstream 40501. Official
    docs require at least 2 and at most 10 keyed target sets; each nested
    target can hold up to 10 entities; at least one include filter is
    required. The live route is a rolling window, not monthly buckets.
    Settlement is unchanged.

    Ref: https://docs.dataforseo.com/v3/ai_optimization/llm_mentions/multi_target_metrics/live/
    """
    endpoints = load_dataforseo_endpoints()
    endpoint = next((ep for ep in endpoints if ep.get("id") == LLM_MENTIONS_MULTI_TARGET_ID), None)
    assert endpoint is not None, f"{LLM_MENTIONS_MULTI_TARGET_ID} not found"

    body = (endpoint.get("input") or {}).get("body") or {}
    field = body.get("targets") or {}
    assert field.get("required") is False, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: keep required: false (DataForSEO body-field convention)"
    )
    note = field.get("note") or ""
    lower = note.lower()
    assert "required" in lower, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: targets.note must say the field is required"
    )
    assert "2" in note and "10" in note, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: targets.note must name the 2-10 keyed-set bound"
    )
    assert "40501" in note, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: targets.note must name upstream 40501"
    )
    assert "include" in lower, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: targets.note must require at least one include filter"
    )
    assert LLM_MENTIONS_HISTORICAL_ID in note, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: targets.note should point monthly series at "
        f"{LLM_MENTIONS_HISTORICAL_ID}"
    )
    assert "rolling" in lower or "trailing" in lower, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: targets.note should say this is a rolling window"
    )

    example = field.get("example") or []
    assert len(example) == 4, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: keep the documented 4-key example, got {len(example)}"
    )
    keys = [item.get("key") for item in example if isinstance(item, dict)]
    assert keys == ["chat_gpt", "claude", "gemini", "perplexity"], (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: 4-key example keys must stay chat_gpt/claude/gemini/perplexity"
    )

    summary = (endpoint.get("summary") or "").lower()
    assert "2" in summary and "10" in summary, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: summary should name 2-10 comparison keys"
    )
    assert "rolling" in summary or "not monthly" in summary, (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: summary should say this is a live rolling window"
    )

    input_note = ((endpoint.get("input") or {}).get("note") or "").lower()
    assert "40501" in input_note or ("2" in input_note and "10" in input_note), (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: input.note should surface the 2-10 / 40501 bound"
    )
    assert LLM_MENTIONS_HISTORICAL_ID in ((endpoint.get("input") or {}).get("note") or ""), (
        f"{LLM_MENTIONS_MULTI_TARGET_ID}: input.note should point monthly charts at "
        f"{LLM_MENTIONS_HISTORICAL_ID}"
    )
