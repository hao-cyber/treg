---
title: Dropleads — synchronous people and company enrichment
status: implemented; live upstream behavior verified
sources:
  - src/treg/catalog/dropleads.yaml
  - src/treg/catalog/examples/dropleads.people.email.find.json
  - src/treg/catalog/examples/dropleads.people.phone.find.json
  - src/treg/catalog/examples/dropleads.people.email.verify.json
  - src/treg/catalog/examples/dropleads.people.search.json
  - src/treg/catalog/examples/dropleads.people.search.count.json
  - src/treg/catalog/examples/dropleads.people.enrich.verified.json
  - src/treg/catalog/examples/dropleads.people.enrich.verified.bulk.json
  - src/treg/catalog/examples/dropleads.people.enrich.json
  - src/treg/catalog/examples/dropleads.people.enrich.bulk.json
  - src/treg/catalog/examples/dropleads.companies.search.json
  - src/treg/catalog/examples/dropleads.companies.search.count.json
  - src/treg/catalog/examples/dropleads.companies.enrich.json
  - src/treg/catalog/adapters.yaml
  - src/treg/catalog/fx.yaml
  - src/treg/config.py
  - src/treg/oauth_providers.py
  - src/treg/application/call/resolve.py
  - src/treg/application/call/settle.py
  - src/treg/domain/capacity/collectors.py
  - src/treg/domain/capacity/policy.py
  - src/treg/web/logos/dropleads.svg
  - tests/test_catalog_validate.py
  - tests/test_key_providers.py
  - tests/test_marketplace_call.py
  - tests/test_routing.py
  - tests/test_capacity_collectors.py
related:
  - architecture/catalog.md
  - architecture/auth-secrets.md
  - architecture/money.md
  - interface/enrich-arena.md
  - ops/capacity.md
---

# Dropleads

Dropleads is a pasted-key enrichment provider using `X-API-Key`. One connection provisions a
`dropleads` tool for `https://prime.dropleads.io` and a `dropleads-contact` companion for
`https://api.dropleads.io`; both bind the same secret. The catalog can select the second host only
because `CatalogTarget` explicitly allow-lists it. The platform credential is
`TREG_PLATFORM_KEY_DROPLEADS`, enabled only when `dropleads` is also present in
`TREG_PLATFORM_PROVIDERS`. A team's own key remains first and is never metered by treg.

## Public surface

The catalog exposes twelve synchronous tools: email finding, mobile finding, email verification,
people search and count, verified person enrichment and its 10-item bulk form, simple person
enrichment and its 10-item bulk form, and company search, count and enrichment. Company enrichment
accepts at most 50 combined domains and company names. These are synchronous bulk requests, so they
fit the ordinary relay; no asynchronous task model was added.

The two single-person Try requests use a neutral name, organization and domain combination. They
show a documented identity shape without storing a user's email or LinkedIn profile in the catalog.

`GET /api/v2/prime-db/credits/balance` is an internal connection/capacity check only.
`POST /api/v2/prime-db/leads/export/cost` is deliberately excluded entirely. Neither endpoint is
searchable or callable through the public catalog on BYOK or platform credentials.

Seven adapters join existing routed tools and therefore the corresponding Enrich Arena tasks:
work-email finding, phone finding, email verification, people search, simple person enrichment,
company search and company enrichment. Count and bulk endpoints remain direct tools. Verified
person enrichment has a distinct catalog capability rather than silently changing the ordinary
person-enrichment contract. Company count reuses the existing `companies.search.count` capability,
so it compares with other providers that count the same search result set.

## Pricing and settlement

Platform calls convert Dropleads credits at the public PAYG price of $18 per 1,000 credits, or
$0.018 per credit. Free promotional credits do not set the customer-facing rate. Email finding is
1 credit on a hit, mobile finding 3, email verification reserves 0.1, people enrichment 0.2 per
returned person, and company data 0.1 per returned company. Search/count routes that return no
metered data are free as documented in the catalog.

Dropleads settlement is provider-specific. `credits_charged` is read for finder/verifier responses,
`credits_consumed` for person enrichment, and `credits.creditsDeducted` for company responses. A
finite, nonnegative reported value—including zero—replaces the reservation estimate. Email Finder's
documented `status: not_found` response omits its numeric field and settles at zero explicitly.
Missing or malformed charge evidence falls back to the catalog estimate rather than inventing a
free call. Request-time reservation counts `details` for 10-item people batches, combines
`domains + companyNames` up to 50 for company enrichment, and caps company-search pagination at 50.
Numeric string limits use the same bound, so a request for `"50"` cannot reserve only the default
20 rows. People search sends `filters.countries` as a list; company search sends the provider's
different `{include: [...]}` country object. Live three-way count checks proved both shapes.
For people, the list reduced the total while the include object matched the unfiltered total. For
companies, the include object reduced the total while the list matched the unfiltered total. Both
APIs therefore return 200 but silently ignore the other API's country shape.

## Capacity and observed behavior

The free balance collector reads numeric nonnegative `credits.totalAvailable`; subscription,
PAYG and `usePayg` fields are descriptive only. The default policy is `credits / manual / api`.
`scripts/provider_balances.py` requires no provider branch: it discovers the typed platform-key
setting and calls the shared collector table. Do not expose its balance call as a catalog tool.

Live verification on 2026-09-15 exercised all fourteen documented routes from a 100-credit free
account and ended at 94.6 credits. The retained PR ledger proves positive charges for email
verification and simple person enrichment, so those two price blocks use observed provenance.
The other paid rates remain documented until equivalent endpoint-specific billing evidence is
retained; their response shapes still support exact settlement when they report a charge. Tested
misses were free. People search and count agreed on totals. People search accepted a requested
limit above 50 but returned at most 50.
Both people bulk routes rejected 0 and 11 inputs; company enrichment rejected more than 50 combined
identities. Prime balance and API-host consumption can reconcile with delay, so per-call settlement
uses response evidence rather than before/after wallet reads.

The same live checks confirmed that both count routes return root-level `{success, count}`. Their
saved examples keep that current response shape; they contain no person or account data.

A live request with a deliberately invalid key on 2026-09-16 returned HTTP 401 with
`{"error":"Unauthorized","message":"Invalid API key format"}`. This confirms that Dropleads
rejects a bogus credential before the catalog connection tests interpret its response.

Observed headers were 60/minute on the Prime host and 30,000 on the contact host for this account.
They are catalog notes, not universal provider limits and not a new shared limiter policy. No empty
wallet was forced, so no Dropleads-specific exhaustion signature or overflow route is claimed.
