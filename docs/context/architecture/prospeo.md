---
title: Prospeo — people and company enrichment
status: shipped
sources:
  - src/treg/catalog/prospeo.yaml
  - src/treg/catalog/examples/prospeo.people.email.find.json
  - src/treg/catalog/examples/prospeo.people.phone.find.json
  - src/treg/catalog/examples/prospeo.people.enrich.json
  - src/treg/catalog/examples/prospeo.people.enrich.bulk.json
  - src/treg/catalog/examples/prospeo.people.search.json
  - src/treg/catalog/examples/prospeo.companies.enrich.json
  - src/treg/catalog/examples/prospeo.companies.enrich.bulk.json
  - src/treg/catalog/examples/prospeo.companies.search.json
  - src/treg/catalog/examples/prospeo.search.suggestions.json
  - src/treg/catalog/adapters.yaml
  - src/treg/catalog/fx.yaml
  - src/treg/config.py
  - src/treg/oauth_providers.py
  - src/treg/application/call/resolve.py
  - src/treg/application/call/settle.py
  - src/treg/domain/capacity/collectors.py
  - src/treg/domain/capacity/policy.py
  - src/treg/web/logos/prospeo.svg
  - scripts/provider_balances.py
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

# Prospeo

Prospeo is a pasted-key enrichment provider using the raw `X-KEY` header and
`https://api.prospeo.io`. `oauth_providers.PROSPEO` verifies a connected key with the provider's
free `GET /account-information` route. The data routes are POST; account information is the
documented exception. `TREG_PLATFORM_KEY_PROSPEO` enables the registry-owned credential only when
`prospeo` is also present in `TREG_PLATFORM_PROVIDERS`. A team's own key remains first and is never
metered by treg.

## Public surface and routing

The public catalog contains nine tools: email finding, phone finding, person enrichment, 50-person
bulk enrichment, person search, company enrichment, 50-company bulk enrichment, company search and
search suggestions. `/account-information` remains internal to connection verification and capacity
collection; callers cannot use the catalog to inspect either their own or treg's account balance.

Six fixture-verified adapters join routed capabilities: `people.email.find`, `people.phone.find`,
`people.enrich`, `people.search`, `companies.enrich` and `companies.search`. The corresponding
single-record tasks participate in Enrich Arena where that capability has a task. Bulk endpoints and
suggestions remain direct tools because their contracts are not scalar enrichment results.

The three single-person tools deliberately share `/enrich-person` with different fixed selectors.
Email finding requires a verified email and disables mobile enrichment. Phone finding requires a
verified mobile. General person enrichment disables mobile enrichment. `_enforce_platform_request`
prevents a platform caller from reserving the email price and switching to the mobile mode. BYOK
still relays the caller's request without treg metering.

## Pricing, reservation and settlement

The platform conversion in `fx.yaml` is the public Starter list price: $49 / 2,000 credits, or
$0.0245 per credit before the configured platform margin. Single email, person and company hits cost
one credit. A non-free phone hit has a fixed ten-credit platform price. Search charges one credit for
a non-empty page; suggestions are free. Bulk responses report the authoritative `total_cost`.

The phone response does not expose whether Prospeo internally charged nine incremental credits after
a prior email reveal or ten credits for a fresh combined reveal. treg therefore advertises, reserves
and settles a predictable ten-credit price for every non-free phone hit. `free_enrichment=true`
still settles zero. Bulk mobile reservation reads the nine-credit rider from
`cost.modifiers.enrich_mobile.add_credits_per_result`; `resolve._credit_modifiers` owns the generic
arithmetic, so Python contains no Prospeo credit multiplier.

`settle._prospeo_cost_micro` requires endpoint-specific success evidence. Email finding requires a
non-empty `person.email.email`; person enrichment charges one credit for a non-empty person object
when `free_enrichment=false`, because email is optional in profile mode; phone finding requires a
non-empty `person.mobile.mobile_international`; company enrichment requires a company object. A
recognizable email- or phone-finder field-level miss settles zero even when an envelope contains
`free_enrichment=false`. A malformed or wrongly typed single-enrichment object returns no
observation and retains the frozen estimate for reconciliation. Explicit provider errors settle
zero, searches use `free` plus the result list, and bulk calls use finite, nonnegative `total_cost`.

The non-free person-with-null-email shape was not observed in the live evidence pass. Treating
`free_enrichment=false` plus a non-empty person as one charged credit is the conservative billing
rule; it avoids silently subsidizing a profile match if Prospeo charges it despite returning no
email. A follow-up controlled pass tried three fresh public profiles: all three returned a non-empty
person with no email, `free_enrichment=true`, and no balance change. This strengthens the evidence
that Prospeo marks null-email profile matches free, but does not prove the false-plus-null shape is
impossible.

## Capacity

`collectors._prospeo` calls the same free account-information route, validates `error=false`, and
reads a finite nonnegative `response.remaining_credits`. Its note carries plan, used credits and the
reported renewal timestamp. Policy is `monthly_quota / quota_reset / api`. The balance script needs
no Prospeo branch: the typed setting and `BALANCE_ROUTES` registration make automatic discovery work.
No empty allowance was forced, so the actual exhaustion response remains acknowledged as unrecorded
and no overflow route is claimed.

Starter request limits are 5/second, 300/minute and 2,000/day for enrichment; 1/second, 30/minute and
1,000/day for search. Suggestions reported a separate free allowance. These request limits are
operational facts, while the account-information balance is the shared monthly credit allowance.
Because capacity smoothing is currently provider-wide, `policy._RATE_LIMITS` uses the stricter
1/second search rate for every platform-key Prospeo call; enrichment is conservatively slower than
its own 5/second allowance. Own-key calls bypass platform metering and this shared-key limiter.

## Live evidence ledger

The verification pass used public company/profile targets, retained only sanitized fixtures and
never committed keys, raw responses, contact values or absolute account balances.

`B` denotes the balance immediately before each call; absolute account balances stay in the private
operator record.

| Catalog id / internal check | Target class | HTTP | Balance before → after | Evidence retained |
|---|---|---:|---:|---|
| Internal account information | Account | 200 | `B → B` | plan, numeric remaining/used credits, renewal timestamp |
| Internal account information, invalid key | Account | 400 | `B → B` | `INVALID_API_KEY`; proves GET probe rejection |
| `prospeo.search.suggestions` | Public location query | 200 | `B → B` | root-level suggestion array and free response |
| `prospeo.companies.search` | Public company domain | 200 | `B → B-1` | `free=false`, non-empty results and pagination |
| `prospeo.people.search` | Public company and role | 200 | `B → B-1` | `free=false`, non-empty results and pagination |
| `prospeo.companies.enrich` | Public company domain | 200 | `B → B-1` | company object and `free_enrichment=false` |
| `prospeo.people.email.find` | Documented public profile | 200 | `B → B-1` | verified revealed email and `free_enrichment=false` |
| `prospeo.people.enrich` | Public profile with unavailable email | 200 | `B → B` | person object and `free_enrichment=true` |
| `prospeo.people.enrich` | Three fresh public profiles with unavailable email | 200 each | `B → B` each | non-empty person, null/absent email and `free_enrichment=true` in all three |
| `prospeo.people.phone.find` | Prior email-reveal profile | 200 | `B → B-9` | mobile present, no numeric charge field; motivates fixed ten-credit platform price |
| `prospeo.people.enrich.bulk` | One-record repeat | 200 | `B → B` | exact `total_cost=0` |
| `prospeo.companies.enrich.bulk` | One-record repeat | 200 | `B → B` | exact `total_cost=0` |

A second end-to-end pass went through local treg rather than directly to Prospeo. Suggestions returned
`X-Treg-Cost-Micro: 0`; a company enrichment reserved and settled 24,500 micro-USD; a deduplicated
phone reveal reserved 245,000 micro-USD, observed zero and settled zero. Audit rows named
`credential_tier=platform`, proving server-side key selection, and each hold had exactly one matching
settlement. `tests/test_marketplace_call.py` separately pins the non-free phone charge and explicit
email/phone field-level misses.
