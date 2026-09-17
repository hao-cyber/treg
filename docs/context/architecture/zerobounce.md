---
title: ZeroBounce — email validation, finding, patterns, and account capacity
status: implemented; live authentication and response shapes verified
sources:
  - src/treg/catalog/zerobounce.yaml
  - src/treg/catalog/examples/zerobounce.people.email.verify.json
  - src/treg/catalog/examples/zerobounce.people.email.find.json
  - src/treg/catalog/examples/zerobounce.companies.email_pattern.json
  - src/treg/catalog/adapters.yaml
  - src/treg/catalog/fx.yaml
  - src/treg/config.py
  - src/treg/oauth_providers.py
  - src/treg/domain/capacity/collectors.py
  - src/treg/domain/capacity/policy.py
  - src/treg/web/logos/zerobounce.svg
  - tests/conftest.py
  - tests/test_archive.py
  - tests/test_capacity_collectors.py
  - tests/test_catalog_validate.py
  - tests/test_enrich_arena.py
  - tests/test_key_providers.py
  - tests/test_marketplace_call.py
  - tests/test_oauth_providers_m3.py
  - tests/test_capacity_overflow_routes.py
  - tests/test_routing.py
related:
  - architecture/catalog.md
  - architecture/auth-secrets.md
  - architecture/money.md
  - interface/enrich-arena.md
  - ops/capacity.md
---

# ZeroBounce

ZeroBounce is a pasted-key email-data provider at `https://api.zerobounce.net`. The selected
operations use an `api_key` query parameter. A team's connected key has priority and is unmetered.
`TREG_PLATFORM_KEY_ZEROBOUNCE` enables shared-key calls only when `zerobounce` is also in
`TREG_PLATFORM_PROVIDERS`.

## Safe catalog surface

The catalog exposes synchronous single validation, person email finding, and company email-pattern
search. All three are read-only GET operations and work with a team's key or the shared platform
key. Credit balance and API usage remain internal because they support registry health rather than
an agent job. They do not appear in catalog search, provider pages, platform pages, or `/call/`.

The wider documented API includes batch and file validation, scoring, Activity Data, filters, and
list evaluation. Batch is excluded because the endpoint needs `api_key`
in its JSON body. Live tests on the three official hosts accepted the documented body shape and
rejected the query-bound shape with HTTP 403. The shared relay does not add secrets to request
bodies. File lifecycles need multipart and binary contracts. Mutating filters and deletion are not
safe read operations. Activity Data has no stable public per-call rate. The catalog does not guess
at these contracts.

## Routing, Arena, and settlement

The verified adapter joins `zerobounce.people.email.verify` to the existing
`treg.people.email.verify` route. It maps the contract email to `queryParams.email`, returns the
provider status, and sets valid only for `status=valid`. Invalid, catch-all, spamtrap, abuse, and
do-not-mail are useful answers. Unknown or a missing status is a miss, so a waterfall can continue.
Arena discovers the same adapter without provider-specific code.

The Email Finder is deliberately not given a routing adapter. At $0.276 per successful result it is
about 3.45 times the next-most-expensive routed contender and roughly 57 times the cheapest, so it
stays an explicit platform/BYOK catalog choice rather than an automatic `treg.people.email.find`
fallback or Enrich Arena contender. `zerobounce.companies.email_pattern` uses the same upstream
`/v2/guessformat` path with domain-only input and likewise stays a direct catalog tool because
`companies.email_pattern` has no routed contract or Arena task.

The supplied acquisition rate is $69 / 5,000 credits, or $0.0138 per credit. Official material says
a completed non-unknown single validation uses one credit and an unknown result uses none. The tool
therefore uses `per_success`. The existing verified-adapter settlement rule releases an unknown
hold and settles other HTTP-200 verdicts at 13,800 micro-USD. Common failure handling releases the
hold on upstream errors. No ZeroBounce branch is added to money code.

Email Finder and Domain Search each document 20 credits per successful result and zero for an
undetermined result. At the same replacement rate, each successful result reserves and settles
276,000 micro-USD. Neither tool has a routing adapter, so each declares the same provider success
rule: an empty `failure_reason` is billable, while an undetermined response releases the hold. The
account's first 10 successful
Finder/Domain Search calls used a promotional allocation. The next successful Email Finder call
reduced the PAYG balance by exactly 20 credits, so Finder pricing is live-verified. Domain Search
retains documented price confidence until its own paid result is observed.

## Connection and capacity

The free connection probe reads API usage for a fixed closed date range directly from
`/v2/getapiusage`. A missing or invalid key returned HTTP 403; the supplied key returned HTTP 200.
The operation stays in the provider registry and is not a catalog tool. The balance route is not
used for connection validation because a bad key can return HTTP 200 with `Credits=-1`.

The capacity collector reads `/v2/getcredits` directly. The operation is not a catalog tool. The
collector accepts nonnegative integers and decimal strings. It rejects Boolean, missing, malformed,
and negative values. It also removes the query key from error reporting by replacing upstream HTTP
errors with a safe provider message. The policy is `credits / manual / api`: the API does not
expose the account's Auto-Pay setting, so treg does not claim automatic replenishment. Shared-key
calls start at the conservative policy rate of 25 requests per second.

## Live evidence and operations

Sandbox valid, invalid, and unknown requests returned the documented shapes. Two fresh real
validations then proved the retail rule: an invalid mailbox reduced the balance from 5,098 to 5,097,
and a valid mailbox reduced it from 5,097 to 5,096. A live person finder returned an email and a live
domain search returned a primary format plus alternatives; both initially used a shared 10-call
promotional allocation. After that allocation was exhausted, the next successful person finder
reduced the balance by exactly 20 credits.

No empty-account response was forced and no overflow route is claimed. Production serving still
needs the normal platform key and provider allow-list configuration. This change does not enable
either. The committed examples are sanitized and contain no key, account balance, address from the
account, or raw live response.
