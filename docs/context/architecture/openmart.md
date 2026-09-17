---
title: Openmart — metered synchronous data and BYOK lifecycle boundaries
status: shipped
sources:
  - src/treg/catalog/openmart.yaml
  - src/treg/catalog/examples/openmart.businesses.search.json
  - src/treg/catalog/examples/openmart.businesses.search.ids.json
  - src/treg/catalog/examples/openmart.businesses.lookup.openmart.json
  - src/treg/catalog/examples/openmart.businesses.lookup.google-place.json
  - src/treg/catalog/examples/openmart.companies.enrich.json
  - src/treg/catalog/examples/openmart.companies.search.json
  - src/treg/catalog/examples/openmart.people.find.batch.json
  - src/treg/catalog/examples/openmart.technologies.find.batch.json
  - src/treg/catalog/examples/openmart.companies.email.find.batch.json
  - src/treg/catalog/examples/openmart.people.enrich.batch.json
  - src/treg/catalog/examples/openmart.tasks.batch.status.json
  - src/treg/catalog/examples/openmart.tasks.batch.ids.json
  - src/treg/catalog/examples/openmart.tasks.get.json
  - src/treg/catalog/examples/openmart.deny-rules.create.json
  - src/treg/catalog/examples/openmart.deny-rules.check.json
  - src/treg/catalog/examples/openmart.deny-rules.delete.json
  - src/treg/catalog/adapters.yaml
  - src/treg/catalog/fx.yaml
  - src/treg/oauth_providers.py
  - src/treg/providers.py
  - src/treg/config.py
  - src/treg/application/call/access.py
  - src/treg/application/call/resolve.py
  - src/treg/application/call/settle.py
  - src/treg/domain/catalog/store.py
  - src/treg/domain/capacity/collectors.py
  - src/treg/domain/capacity/policy.py
  - src/treg/web/logos/openmart.svg
  - tests/test_capacity_overflow_routes.py
  - tests/test_capacity_collectors.py
  - tests/test_catalog_api.py
  - tests/conftest.py
  - tests/test_key_providers.py
  - tests/test_marketplace_call.py
  - tests/test_mcp.py
  - tests/test_oauth_providers_m3.py
  - tests/test_enrich_arena.py
  - tests/test_routing.py
related:
  - architecture/catalog.md
  - architecture/auth-secrets.md
  - architecture/money.md
  - interface/enrich-arena.md
  - ops/capacity.md
---

# Openmart

Openmart is a pasted Bearer-key enrichment provider at `https://api.openmart.ai`. The free
`GET /api/v2/credit-balance` operation verifies a connection and supplies the capacity collector.
The catalog exposes 16 caller-facing operations: business and brand search, two ID lookups, company
enrichment, four batch submission types, three task reads, and three deny-rule operations. The
balance route is deliberately not a tool: it is internal connection/capacity infrastructure.

## Shared-key boundary

Five synchronous data operations support both a team's own key and treg's metered platform key:
business search, both full-record ID lookups, company enrichment, and brand search. The team's key
still wins and is never metered. Openmart's provider-specific settlement path counts only the
verified returned-record containers: a root array or `data[]` for search/enrichment, `data[]` for
brand search, and values in the ID-keyed lookup maps. It charges
`ceil(0.3 × returned_records)` credits per operation; a present empty container settles at zero.

Shared-key requests require an explicit count from 1 to 25 before reserve or relay: `limit` for
business search and company enrichment, `pagination.limit` for brand search, and raw array
cardinality for both ID lookups. The reserve applies the same rounded formula, so 25 requested
records hold eight credits. Own-key calls bypass the guard and retain the upstream limits. The
catalog access check prices each endpoint's runnable example with this same Openmart-specific
formula instead of the generic 20-row estimate.

The other 11 operations remain BYOK-only. Fast ID search has no proven fractional price. The four
batch submissions and three task reads are one delayed, account-owned lifecycle whose charges
cannot be assigned safely by a synchronous response. The three deny-rule operations read or mutate
private account state and forbid caching. The shared balance route is absent from the catalog so no
caller can inspect operational inventory.

The catalog records the active subscription conversion of $149 for 5,000 credits, or $0.0298 per
credit, before configured platform margin. Openmart support confirmed that search, full-record
lookup, and company enrichment are priced at three credits per ten returned records, rounded up per
operation. Ten live one-result searches each returned one record and deducted one credit, matching
that rule. A 25-record platform call therefore reserves at most eight credits ($0.2384 raw). People
data costs 3 credits for email and 8 for phone; a technology result costs 2. The catalog does not
claim auto-top-up.

## Routing and Arena

Openmart tools are direct-call only: none has a routing adapter and none appears in Enrich Arena.
The direct platform-eligible tools remain callable with treg's key. A live nonsense business query
returned an unrelated fallback row with `match_score: 0`, so direct callers must treat that score as
a miss; the result is not safe for automatic selection. Company enrichment can return several
location matches, so choosing the first would also change semantics. People operations are
asynchronous and do not join the synchronous people routes or Arena tasks.

## Capacity and evidence

`collectors._openmart` calls the free balance endpoint, accepts only a non-negative integer balance,
and reports subscription credits with the current period end when available. The default policy is
`credits / subscription / api`. A provider-wide 15 requests per second policy uses the strictest
published endpoint-family limit. Direct BYOK calls bypass shared-key smoothing.

Live checks used synthetic inputs and stayed within the task cap. They covered authentication,
search pagination, hits, misses, validation, every data operation, the full batch lifecycle, deny
checks, and internal balance reads. Stored examples use reserved synthetic identities only. No key
or raw live response is stored.
