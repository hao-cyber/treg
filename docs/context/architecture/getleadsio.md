---
title: GetLeads.io — contact data with a shared treg trial
status: shipped
sources:
  - src/treg/catalog/getleadsio.yaml
  - src/treg/catalog/examples/getleadsio.people.enrich.from_email.json
  - src/treg/catalog/examples/getleadsio.people.enrich.from_linkedin.json
  - src/treg/catalog/examples/getleadsio.people.enrich.from_person.json
  - src/treg/catalog/examples/getleadsio.people.phone.lookup.json
  - src/treg/catalog/examples/getleadsio.people.phone.lookup_batch.json
  - src/treg/catalog/examples/getleadsio.people.colleagues.json
  - src/treg/catalog/examples/getleadsio.people.decision_makers.json
  - src/treg/catalog/examples/getleadsio.people.search.json
  - src/treg/catalog/examples/getleadsio.people.search.count.json
  - src/treg/catalog/examples/getleadsio.people.search.filters.json
  - src/treg/catalog/examples/getleadsio.companies.funding.feed.json
  - src/treg/catalog/examples/getleadsio.companies.acquisitions.feed.json
  - src/treg/catalog/fx.yaml
  - src/treg/config.py
  - src/treg/oauth_providers.py
  - src/treg/domain/capacity/collectors.py
  - src/treg/domain/capacity/policy.py
  - src/treg/web/logos/getleadsio.svg
  - tests/test_capacity_collectors.py
  - tests/test_capacity_overflow_routes.py
  - tests/test_catalog_api.py
  - tests/test_catalog_validate.py
  - tests/test_key_providers.py
  - tests/test_marketplace_call.py
  - tests/test_oauth_providers_m3.py
related:
  - architecture/auth-secrets.md
  - architecture/catalog.md
  - architecture/money.md
  - ops/capacity.md
---

# GetLeads.io

GetLeads.io is a pasted-key enrichment provider at `https://app.getleads.io`. Both own-key and
platform bindings use `Authorization: Bearer …`. Connection verification calls the free
`GET /api/v1/usage/fair-use` route. A 401 rejects a bad key; a successful response does not require
a positive credit balance. A team's own key wins over treg's key and is never metered by treg.

## Public surface

The catalog publishes 12 direct tools: email, LinkedIn, and person enrichment; single and batch
phone lookup; colleague and decision-maker lookup; contact search and count; filter discovery; and
funding and acquisition feeds. The fair-use and contacts-health routes remain internal. CSV upload,
asynchronous search export, and profile-monitoring state are excluded because they introduce files,
jobs, or account-owned resources that this integration does not yet model.

All 12 tools can use either a team's own key or treg's key. The catalog exposes only the original
provider operations and does not add restricted `.trial` copies. Callers choose any value that the
provider accepts for page limits, batch sizes, and other request fields. treg does not insert,
reduce, or otherwise rewrite those values. No provider-specific relay branch is added.

No GetLeads.io tool joins routed capabilities or Enrich Arena. Live synthetic misses were not a
reliable success signal: reserved invalid inputs on email, LinkedIn, and person enrichment returned
`success=true` and consumed credits. The direct catalog relays that native answer faithfully, but
treg does not normalize it into a cross-provider hit or miss.

## Trial price and capacity

GetLeads.io publishes a one-time 1,000 database-credit promotion but no ordinary USD replacement
price for those credits. The separate Live Leads wallet prices other products and is not evidence
for database-credit value. The `fx.yaml` entry therefore uses the existing `treg_trial` contract:
exactly $0, at most five successful credit-using platform calls per team per UTC day, and no claim
that $0 is the vendor's database-credit price. Free search-count and filter-discovery calls, failed
calls and BYOK calls do not consume the daily allowance. This allowance counts paid calls, not
returned records or upstream credits: one successful platform call can consume from zero to
thousands of promotional credits according to the caller's request and the provider's result.

`collectors._getleadsio` reads numeric nonnegative `credits_remaining` from the same free fair-use
route and labels it as the promotional database-credit allocation. Policy records credits with
manual replenishment and API observation. When a sweep observes zero, the shared capacity guard
refuses platform calls before reserve with a typed 503 and an own-key instruction; BYOK calls remain
available. The documented default request limit is 100 requests per minute, which is the
platform-key smoothing policy. No upstream exhaustion response was forced, so the provider remains
in the acknowledged-unrecorded capacity-signature set and has no overflow route.

## Live evidence ledger

The verification pass retained only sanitized shapes and relative balance movement. It used
synthetic inputs, spent about ten promotional credits, and did not retain keys, raw responses,
contact values, or absolute balances.

| Route | Result | Credit evidence |
|---|---|---|
| Fair-use with bad then valid key | 401 then 200 | Free probe; valid response exposed numeric remaining credits |
| Search count and filter values | 200 | Reported zero usage; balance unchanged |
| Contact search, two one-row pages | 200 | Distinct rows; one reported and consumed credit per page |
| Contact search, zero-row miss | 200 | Reported zero usage; balance unchanged |
| Phone lookup and phone batch, synthetic miss | 200 | No match; balance unchanged |
| Colleagues and decision makers, synthetic miss | 200 | Zero rows and zero reported usage; balance unchanged |
| Email, LinkedIn, and person enrichment, reserved invalid inputs | 200 | Each returned success and consumed one credit; motivates no adapter |
| Funding feed, limit one | 200 | One row and one reported/consumed credit |
| Acquisition feed, limit one | 200 | Zero rows and zero reported usage |
