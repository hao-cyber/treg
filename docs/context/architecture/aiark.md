---
title: AI Ark — bounded synchronous enrichment and BYOK async jobs
status: shipped
sources:
  - src/treg/catalog/aiark.yaml
  - src/treg/catalog/examples/aiark.companies.search.json
  - src/treg/catalog/examples/aiark.lists.upsert.json
  - src/treg/catalog/examples/aiark.people.email.find.bulk.submissions.json
  - src/treg/catalog/examples/aiark.people.email.find.json
  - src/treg/catalog/examples/aiark.people.enrich.json
  - src/treg/catalog/examples/aiark.people.export.submissions.json
  - src/treg/catalog/examples/aiark.people.personality.analyze.json
  - src/treg/catalog/examples/aiark.people.phone.find.json
  - src/treg/catalog/examples/aiark.people.preview.json
  - src/treg/catalog/examples/aiark.people.search.json
  - src/treg/catalog/adapters.yaml
  - src/treg/catalog/fx.yaml
  - src/treg/config.py
  - src/treg/oauth_providers.py
  - src/treg/domain/capacity/collectors.py
  - src/treg/domain/capacity/policy.py
  - src/treg/application/call/settle.py
  - src/treg/web/logos/aiark.svg
  - tests/test_catalog_validate.py
  - tests/test_capacity_collectors.py
  - tests/test_capacity_overflow_routes.py
  - tests/test_enrich_arena.py
  - tests/test_key_providers.py
  - tests/test_marketplace_call.py
  - tests/test_oauth_providers_m3.py
  - tests/test_routing.py
  - tests/conftest.py
related:
  - architecture/catalog.md
  - architecture/auth-secrets.md
  - architecture/money.md
  - interface/enrich-arena.md
  - ops/capacity.md
---

# AI Ark

AI Ark is a pasted-key enrichment provider. `oauth_providers.AIARK` injects the raw key in the
`X-TOKEN` header and targets `https://api.ai-ark.com/api/developer-portal`. It verifies a connection
through the free `GET /v1/payments/credits` route. A live bogus key returned HTTP 401 and the assigned
key returned HTTP 200 with a numeric balance. `TREG_PLATFORM_KEY_AIARK` enables the platform
credential only when `aiark` is also present in `TREG_PLATFORM_PROVIDERS`. A team's own key remains
first and treg never meters it.

## Catalog surface and boundary

`aiark.yaml` exposes 18 tools from 21 documented operations. It uses the V2 single-email and mobile
routes and omits their duplicate V1 forms. The free credits route stays internal to connection
verification and `collectors._aiark`, so catalog callers cannot inspect either their own or treg's
account balance.

Seven synchronous reads can use the platform key: people search, masked preview, company search,
single email finding, single mobile finding, reverse lookup and personality analysis. treg's people
and company search tools require `size=1`; larger pages remain available by calling AI Ark directly
with an own key. The singleton schema and `platform_request` bound give every platform search a fixed
maximum hold. Successful platform responses settle from the provider's exact `X-Credit` header.
AI Ark reports debits as negative numbers, so `_CREDIT_HEADERS` declares an explicit -1 multiplier;
positive, missing, nonnumeric and non-finite values remain untrusted and fall back to other evidence.

List mutation and ten async submission, result, status, history and webhook-resend tools are
BYOK-only. AI Ark track ids are account-scoped, a search track id is single-use, and delivery failure
can trigger a refund up to ten hours after submission. The current shared async contract does not
persist caller ownership and terminal charge/refund evidence for that lifecycle. The integration
therefore adds no AI Ark branch to the call, money, async, routing or Arena runtime.

## Pricing and settlement

`fx.yaml` records the assigned subscription rate: $79 / 15,000 credits, rounded up from
$0.005266666... to $0.005267 per credit. This is the base catalog conversion before the configured
platform margin and assumes the monthly allowance is used. The provider says unused credits roll
over up to twice the monthly allowance.

Platform search prices are bounded by the one-row input: 0.5 credit for a returned person and 0.1
credit for a returned company. Preview costs one credit per served page. A valid email costs one
credit, a mobile costs five, reverse lookup costs 0.5 on a successful profile and personality
analysis costs four on success. Fixture-verified adapters and `expect` evidence let generic
`per_success` settlement release misses; upstream rejections also release the hold. The shared
credit-header mechanism reads the exact charge without adding an AI Ark-specific settlement branch.

AI Ark's V2 email and mobile endpoints return HTTP 200 with `data: null` for an observed miss. Their
adapters test the requested email or phone field itself, so a present envelope with an empty output
array is also a zero-cost miss. The phone output is nested under `data.data[0][0]`; the adapter uses
the existing `get` expression to normalize it. A
reverse-lookup miss returned HTTP 404 and used no credit even though the public reference describes
a per-request charge, so treg conservatively settles only a successful profile.

The two async submission tools retain documented `per_result` prices as BYOK information. They do
not advertise a platform estimate, reserve a team balance or imply that delayed refunds are handled.

## Routing and Arena

Five adapters join existing capability contracts: `aiark.people.search`,
`aiark.companies.search`, `aiark.people.email.find`, `aiark.people.phone.find` and
`aiark.people.enrich`. Search adapters fix `size=1`; enrichment adapters translate only the
provider's observed response shapes. Sanitized fixtures verify every adapter when the catalog loads.
The tools become route and Enrich Arena candidates through the generic capability machinery.

Preview and personality analysis stay direct tools because the existing routed contracts do not
describe their outputs. Stateful list and async operations never enter Arena. There is no
AI Ark-specific provider choice, retry or response wrapping.

## Capacity

`collectors._aiark` calls the same free credit route and accepts only a finite nonnegative numeric
`total`. Booleans, negative values and non-finite numbers fail the observation. The default policy is
`monthly_quota / quota_reset / api` with the assigned 15,000-credit monthly allowance. The balance
response does not report a reset timestamp, so the policy describes the monthly subscription without
inventing a date. Vendor auto-top-up is not enabled.

AI Ark documents five requests per second per token. `policy._RATE_LIMITS` applies that rate to the
shared platform key; BYOK calls bypass shared-key smoothing. The funded allowance was not exhausted,
so the integration records no provider-specific exhaustion signature and claims no overflow route.

## Live evidence

The discovery and local-app passes used public or synthetic inputs and spent 15.1 credits, below the
approved 50-credit ceiling. Only sanitized fixtures are committed; keys, absolute balances, raw
contact data and generated account resources are not retained.

| Check | Result | Credit delta |
|---|---|---:|
| Balance probe, missing or bogus key | HTTP 401 | 0 |
| Balance probe, assigned key | HTTP 200 with numeric total | 0 |
| People preview, one-row page | HTTP 200 and `X-Credit: -1.0` | 1 |
| People search, two one-row pages | HTTP 200 and `X-Credit: -0.5` each | 0.5 each |
| Company search, one-row page | HTTP 200 and `X-Credit: -0.1` | 0.1 |
| V2 email finder, miss and hit | HTTP 200; null then verified output | 0, 1 |
| V2 mobile finder, miss and hit | HTTP 200; null then mobile output | 0, 5 |
| Reverse lookup, synthetic miss | HTTP 404 | 0 |
| Personality analysis, public profile | HTTP 200 and `X-Credit: -4.0` | 4 |
| Invalid search size and invalid list | HTTP 400 | 0 each |
| Valid list create | HTTP 200 | 0 |
| Async history reads | HTTP 200 with empty pages | 0 |
| Async submits with rejected webhook | HTTP 400 before queueing | 0 |

An isolated local app used the real AI Ark upstream after the catalog was installed. A platform
email hit created one reserve and one 5,267-micro-USD settlement. A routed email miss attempted
`aiark.people.email.find`, charged zero and left the team balance unchanged. The pasted-key flow
rejected a bogus key with 422, accepted the assigned key with 200 and created the `aiark` tool. A
subsequent own-key call recorded `credential_tier=tool`, emitted no treg cost header and did not move
the team balance. The two clean evidence passes spent one credit each; routed and BYOK misses were
free.

The async paid path, terminal result ownership, delayed refund behavior and empty-allowance response
remain unproved. Those gaps are the reason for the BYOK-only boundary, not undocumented platform
support.
