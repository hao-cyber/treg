---
title: Wiza — synchronous search and company enrichment, BYOK async jobs
status: shipped
sources:
  - src/treg/catalog/wiza.yaml
  - src/treg/catalog/examples/wiza.people.search.json
  - src/treg/catalog/examples/wiza.companies.search.json
  - src/treg/catalog/examples/wiza.companies.enrich.json
  - src/treg/catalog/examples/wiza.meta.locations.search.json
  - src/treg/catalog/examples/wiza.meta.technologies.search.json
  - src/treg/catalog/adapters.yaml
  - src/treg/catalog/fx.yaml
  - src/treg/config.py
  - src/treg/oauth_providers.py
  - src/treg/domain/capacity/collectors.py
  - src/treg/domain/capacity/policy.py
  - src/treg/web/logos/wiza.svg
  - tests/test_wiza.py
  - tests/test_key_providers.py
  - tests/test_oauth_providers_m3.py
  - tests/test_capacity_overflow_routes.py
  - tests/test_capacity_collectors.py
  - tests/test_routing.py
  - tests/conftest.py
related:
  - architecture/catalog.md
  - architecture/auth-secrets.md
  - architecture/money.md
  - interface/enrich-arena.md
  - ops/capacity.md
---

# Wiza

Wiza is a pasted-key enrichment provider. `oauth_providers.WIZA` injects the raw key as an
`Authorization: Bearer` header on `https://wiza.co`. It verifies a connection with the free
`GET /api/meta/credits` route. A live invalid key returned HTTP 401 and the assigned key returned
HTTP 200. `TREG_PLATFORM_KEY_WIZA` enables the platform credential only when `wiza` is also in
`TREG_PLATFORM_PROVIDERS`. A team's own key remains first and treg does not meter it.

## Surface and platform boundary

`wiza.yaml` accounts for all 13 official API paths. Twelve are caller-facing catalog tools. The
credit endpoint remains internal to connection verification and capacity collection, so a catalog
caller cannot inspect either its own or treg's Wiza balance.

Five synchronous tools allow platform access: one-row prospect search, one-row company search,
company enrichment, location autocomplete and technology autocomplete. Each search input declares
`size` as a required singleton value of 1. The request constraint rejects an omitted or different
value rather than applying a default. This bounds the hold before the request and makes the
advertised half-credit price exact for a non-empty result. Callers can follow `next_page_token` one
row at a time. The two autocomplete helpers are authenticated but free.

Seven operations are BYOK-only: start and get an individual reveal; create, inspect and export a
list; and create or continue a prospect list. These operations create or retrieve asynchronous,
account-scoped jobs. Wiza returns a numeric result id without a caller ownership token. The final
individual-reveal response reports the charge, but the kickoff response does not. Platform access
would therefore need a durable owner link between the submission, result id and terminal charge.
The current integration does not add a Wiza branch to the shared async or money runtime.

## Prices and settlement

`fx.yaml` uses Wiza's public one-time API credit price: $0.025 per non-expiring credit before the
configured platform margin. This is the defensible replacement rate for the promotional 5,000-credit
grant. It is not a claim about the later custom commercial agreement.

Company enrichment costs two credits when it finds a company. Prospect and company search cost
0.5 credit per returned row. The platform variants return at most one row, so their frozen estimate
is 0.5 credit. Their fixture-verified route adapters let the generic `per_success` settlement rule
recognize an empty response and settle zero. An upstream 400 or 404 releases the hold. A successful
non-empty HTTP 200 settles the estimate. No Wiza-specific function exists in `call/settle.py`.

Individual reveals are documented and live-verified at one credit for a matched profile, two for a
valid email, five for a phone and seven when a full response returns both. A failed profile match
reported no charge and left the balance unchanged. Those prices describe BYOK tools only; treg does
not reserve or settle them on the platform credential.

Wiza does not publish a separate charge for downloading completed-list contacts or the final
per-row charge for asynchronous prospect-list creation and continuation. The catalog marks those
BYOK-only prices as unknown. It does not copy the observed synchronous search price into them.

## Routing and Arena

Three adapters use existing contracts: `wiza.people.search`, `wiza.companies.search` and
`wiza.companies.enrich`. The search adapters fix `size=1` and preserve the provider's total and next
page token. The company-enrichment adapter accepts a domain or name. Sanitized fixtures verify all
three adapters at catalog load. They become route and Enrich Arena candidates through the existing
capability machinery; no Wiza-specific route or Arena code exists.

The async reveal endpoint does not join email, phone or person-enrichment routes. A route child must
return and settle one result in the same owned call lifecycle. Wiza's reveal requires a later result
fetch and does not satisfy that contract.

## Capacity and live evidence

`collectors._wiza` reads the finite, nonnegative `credits.api_credits` value and reports API credits.
Malformed, Boolean, negative or non-finite values fail the observation instead of becoming an
allowance. The default policy is `credits / manual / api`; vendor auto-top-up is not enabled. The
funded grant was not exhausted, so no exhaustion response or overflow route is claimed.

Wiza does not publish search or autocomplete rate limits. As a provisional policy, `_RATE_LIMITS`
reuses the documented company-enrichment ceiling of 30 calls per minute for every Wiza platform
call because the shared-key limiter is not endpoint-aware. This is not a claim that search or
autocomplete has the same upstream limit. It spaces sequential platform calls by about two seconds:
the first call can proceed immediately, while fetching 20 one-row search pages adds about 38 seconds
of waiting. BYOK bypasses the shared-key limiter.

This smoothing reduces ordinary shared-key bursts but is not a strict quota gate. `Limiter.acquire`
waits at most `DEFAULT_MAX_WAIT_MS` (two seconds), lets calls that would wait longer proceed, and is
process-local, so concurrent load or multiple replicas can exceed 30 calls per minute. Relax this
provisional ceiling after real 429 evidence, or replace it when smoothing becomes endpoint-aware.
Removing `wiza` from `TREG_PLATFORM_PROVIDERS` remains the immediate serving kill switch; a team's
own key continues to win.

The live discovery pass used public or synthetic targets and consumed 18.5 API credits. The later
local dataplane check consumed four more credits: two through the platform key and two after BYOK
precedence took effect. Total live spend was 22.5 credits, below the 100-credit ceiling. Absolute
balances, keys, contact values and raw responses were not retained.

| Check | Result | Credit delta |
|---|---|---:|
| Credit probe, invalid key | HTTP 401 | 0 |
| Credit probe, valid key | HTTP 200 | 0 |
| Company enrichment, invalid input | HTTP 400 | 0 |
| Company enrichment, synthetic miss | HTTP 404 | 0 |
| Company enrichment, documented public company | HTTP 200, response reported 2 | 2 |
| Company search, first one-row page | HTTP 200, next token present | 0.5 |
| Company search, second one-row page | HTTP 200 | 0.5 |
| Prospect search, one-row page | HTTP 200 | 0.5 |
| Location and technology autocomplete | HTTP 200 | 0 each |
| Individual reveal: profile, email, phone, full | HTTP 200 terminal results | 1, 2, 5, 7 |
| Individual reveal: synthetic miss | terminal `failed` | 0 |
| Local platform company miss and invalid input | HTTP 404 and 400; holds released | 0 each |
| Local platform company hit | HTTP 200; one reserve and one 50,000 micro-USD settlement | 2 |
| Local BYOK company hit | HTTP 200; no treg cost header or team-balance change | 2 |

An isolated local server also exercised `POST /connections/token` against the real Wiza probe. The
bogus key was rejected with 422 after Wiza's 401; the assigned key connected with 200 and created
the expected `wiza` tool.
