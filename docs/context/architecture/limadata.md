---
title: LimaData — Basic v2 enrichment, research, and bounded shared-key calls
status: shipped
sources:
  - src/treg/catalog/limadata.yaml
  - src/treg/catalog/examples/limadata.people.enrich.json
  - src/treg/catalog/examples/limadata.companies.enrich.json
  - src/treg/catalog/examples/limadata.database.autocomplete.json
  - src/treg/catalog/examples/limadata.companies.count.json
  - src/treg/catalog/examples/limadata.people.count.json
  - src/treg/catalog/examples/limadata.companies.search.json
  - src/treg/catalog/examples/limadata.people.search.json
  - src/treg/catalog/examples/limadata.people.employees.search.json
  - src/treg/catalog/examples/limadata.people.audience.resolve.json
  - src/treg/catalog/examples/limadata.people.audience.email-hash.json
  - src/treg/catalog/examples/limadata.people.email.find.personal.json
  - src/treg/catalog/examples/limadata.people.email.verify.json
  - src/treg/catalog/examples/limadata.people.email.find.name.json
  - src/treg/catalog/examples/limadata.people.email.find.linkedin.json
  - src/treg/catalog/examples/limadata.companies.linkedin.find.json
  - src/treg/catalog/examples/limadata.people.phone.find.json
  - src/treg/catalog/examples/limadata.people.identity.resolve.json
  - src/treg/catalog/examples/limadata.people.identity.from-email.json
  - src/treg/catalog/examples/limadata.web.extract.json
  - src/treg/catalog/examples/limadata.web.research.json
  - src/treg/catalog/examples/limadata.google.serp.organic.json
  - src/treg/catalog/examples/limadata.people.audience.batch.start.json
  - src/treg/catalog/examples/limadata.people.email.verify.batch.start.json
  - src/treg/catalog/examples/limadata.people.batch.results.json
  - src/treg/catalog/adapters.yaml
  - src/treg/catalog/fx.yaml
  - src/treg/config.py
  - src/treg/oauth_providers.py
  - src/treg/providers.py
  - src/treg/domain/capacity/collectors.py
  - src/treg/domain/capacity/policy.py
  - src/treg/web/logos/limadata.svg
  - tests/test_catalog_validate.py
  - tests/test_enrich_arena.py
  - tests/test_key_providers.py
  - tests/test_marketplace_call.py
  - tests/test_oauth_providers_m3.py
  - tests/test_providers.py
  - tests/test_routing.py
  - tests/test_capacity_collectors.py
  - tests/test_capacity_overflow_routes.py
  - tests/conftest.py
related:
  - architecture/catalog.md
  - architecture/auth-secrets.md
  - architecture/money.md
  - interface/enrich-arena.md
  - ops/capacity.md
---

# LimaData

LimaData is a pasted-key enrichment provider. `oauth_providers.LIMADATA` injects the raw key in
`x-api-key` on `https://api.limadata.com`. Connection verification sends `{}` to the web-search
route. The assigned key receives a free HTTP 400 validation response, while a bogus key receives
HTTP 401. The provider's `probe_reject_statuses` accepts the former and rejects 401 and 403.
`TREG_PLATFORM_KEY_LIMADATA` supplies the optional shared credential only when deployment also
allows `limadata`. A team's own key remains first and treg never meters it.

## Surface and shared-key boundary

`limadata.yaml` catalogs all 24 operations in the official Basic v2 OpenAPI document. Connected
teams can call every operation. Fourteen synchronous operations can use the shared key because their
successful charge is fixed and bounded: company enrichment, database autocomplete, company count,
five contact and identity lookups, email verification, company LinkedIn lookup, phone lookup, AI
research, and web search.

Ten operations stay BYOK-only:

- Person enrichment varies from one to 15 credits based on the identifier and optional results.
- People count requires People Database API access, which is not enabled on treg's shared account.
  Teams whose own LimaData plan includes that access can still call the endpoint directly.
- Three database searches charge by returned rows, in whole-credit blocks with a one-credit
  minimum.
- Identity resolution costs two credits even on HTTP 404. Generic settlement releases a hold on an
  upstream error, so shared service would undercharge.
- URL extraction varies by URL count and JavaScript-rendering mode.
- Both batch submissions and batch result reads use account-scoped job identifiers. Advertising
  batches refund misses only after completion.

The batch-results route is free. A live completed-job response carried `x-credits-cost: 1`, but the
dashboard showed no polling activity or debit. That header describes task evidence and must not be
used as the current request price. No LimaData branch is added to the shared settlement runtime.

## Prices and settlement

The assigned account is on Starter: $50 per month for 2,500 credits, or $0.02 per included credit
if fully used. `fx.yaml` uses that $0.02 entry-plan rate as treg's stable LimaData cost basis. The
account's enabled automatic top-up adds 6,667 credits for $100, or about $0.015 each, but that
marginal replenishment price does not lower the catalog rate.

The generic `per_success` rule settles fixed-price HTTP success and releases the hold for an HTTP
error. Examples include 20,000 micro-USD for one company-enrichment credit and 6,000 micro-USD for
0.3 email-verification credit, before any configured platform margin. BYOK calls have no treg cost
header and do not change the team balance. The integration adds no provider-specific function in
the relay, reserve, or settlement paths.

## Routing and Enrich Arena

Five sanitized fixtures verify adapters at catalog load: work email by name and company, work email
by LinkedIn URL, email verification, phone finding, and company enrichment. They join the existing
`people.email.find`, `people.email.verify`, `people.phone.find`, and `companies.enrich` contracts.
The route builder and Enrich Arena discover them through the normal verified-adapter list. No
LimaData-specific router or Arena code exists. Person enrichment remains directly callable with a
team's own LimaData key, but has no adapter and therefore never appears in automated routing or
Enrich Arena while it is BYOK-only.

## Capacity and live evidence

The official Basic v2 API exposes no free standalone balance or usage route. Capacity therefore
reports `credits / auto_recharge / manual`, with a dashboard-only meter instead of spending a paid
request merely to learn the balance. The final dashboard balance after discovery was 2,590 credits.
The account's existing automatic top-up was observed as enabled; discovery did not change it. The
shared-key capacity policy depends on that setting remaining enabled. If it is disabled, operators
must update the policy rather than continuing to report automatic replenishment.

The default documented account limit is one request per second. Several operations say they are
exempt but give no numeric ceiling. `_RATE_LIMITS` uses the conservative provider-wide 1/s value for
the shared key because smoothing is not endpoint-aware. BYOK bypasses this shared limiter. No empty
balance was manufactured, no exhaustion signature is claimed, and no overflow route is enabled.

The live discovery pass used ten credits, below the 30-credit ceiling. Values below are the net
charges shown by response evidence and the account activity page.

| Check | Result | Credit delta |
|---|---|---:|
| Missing and bogus key probes | HTTP 401 | 0 |
| Authenticated empty web-search probe | HTTP 400 | 0 |
| Web search | HTTP 200 | 0.1 |
| Database autocomplete | HTTP 200 | 1 |
| Company LinkedIn lookup | HTTP 200 | 1 |
| Work-email synthetic misses | HTTP 404 | 0 |
| Identity-resolution synthetic miss | HTTP 404 | 2 |
| Company count | HTTP 200 | 0.1 |
| People count on the shared account | HTTP 403; People Database API access is not enabled | 0 |
| Two one-row company-search pages | HTTP 200 | 1 each |
| Email verification | HTTP 200 | 0.3 |
| Extract without and with JavaScript | HTTP 200 | 0.1 and 0.2 |
| AI research | HTTP 200 | 0.3 |
| Company and person enrichment | HTTP 200 | 1 each |
| Batch email verification | HTTP 202 | 0.3 |
| Batch advertising-audience miss | HTTP 202 then completed; refund applied | 0 net |
| Batch result polling | HTTP 200; no activity row | 0 |
| Work-email found | HTTP 200 | 1 |

An isolated local server exercised the real `POST /connections/token` path with the free probe. A
bogus key was rejected with 422 after the upstream 401. The assigned key connected with 200 after
the upstream authenticated 400. The key and raw upstream bodies were not printed or committed.
