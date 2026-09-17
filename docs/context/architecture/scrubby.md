---
title: Scrubby — quick and deep email verification
status: implemented; live authentication, billing and asynchronous behavior verified
sources:
  - src/treg/catalog/scrubby.yaml
  - src/treg/catalog/examples/scrubby.people.email.verify.json
  - src/treg/catalog/examples/scrubby.people.email.verify.bulk.json
  - src/treg/catalog/examples/scrubby.people.email.verify.bulk.results.json
  - src/treg/catalog/examples/scrubby.people.email.verify.deep.json
  - src/treg/catalog/examples/scrubby.people.email.verify.deep.results.json
  - src/treg/catalog/adapters.yaml
  - src/treg/catalog/fx.yaml
  - src/treg/config.py
  - src/treg/oauth_providers.py
  - src/treg/application/call/settle.py
  - src/treg/domain/capacity/collectors.py
  - src/treg/domain/capacity/policy.py
  - src/treg/web/logos/scrubby.svg
  - tests/test_scrubby.py
  - tests/test_key_providers.py
  - tests/test_oauth_providers_m3.py
  - tests/test_capacity_overflow_routes.py
  - tests/test_capacity_collectors.py
  - tests/conftest.py
related:
  - architecture/catalog.md
  - architecture/auth-secrets.md
  - architecture/money.md
  - interface/enrich-arena.md
  - ops/capacity.md
---

# Scrubby

Scrubby is a pasted-key email-verification provider at `https://api.scrubby.io`. It uses the
`x-api-key` header. `oauth_providers.SCRUBBY` verifies a key by posting a fixed nonexistent identifier
to `/fetch_bulk_results`: a bogus key returns 401, while a valid key returns the expected 404 without
spending a credit. A constant descriptive User-Agent avoids the provider edge rejecting the default
Python urllib client profile. `TREG_PLATFORM_KEY_SCRUBBY` enables shared-key access only when
`scrubby` is also present in `TREG_PLATFORM_PROVIDERS`; a team's own key remains first and unmetered.

## Surface and routing

The catalog exposes the complete five-operation OpenAPI surface: synchronous single verification,
quick-bulk submit and fetch, and deep-bulk submit and fetch. The single tool adapts to the existing
`people.email.verify` contract and therefore participates in normal routing and Enrich Arena.
`Valid` maps to `valid=true`; `Invalid`, `Risky`, and `Unknown` are useful negative or uncertain
answers rather than misses.

Only the single tool can use treg's shared key. The four bulk lifecycle tools are BYOK-only. Scrubby
publishes no batch-size maximum, so treg cannot bound a shared-key reservation. Its poll identifier
is also carried in a JSON body, while the existing shared-key ownership guard authorizes declared
request parameters. The catalog does not invent a limit or weaken task ownership to add bulk
platform access.

## Pricing and settlement

The supplied acquisition cost is $50 / 6,250 credits, or $0.008 per credit. Quick verification costs
one credit per fresh address; deep verification costs three. A provider-specific settlement branch,
matching the established Sumble and QuickEnrich pattern, reads Scrubby's top-level `credits_used`.
It accepts only non-negative integers and multiplies them by the frozen per-credit rate. This honors
zero-cost cached retries and exact multi-credit responses; malformed or missing evidence retains the
reserved estimate for reconciliation.

Scrubby support confirmed that a client-side timeout does not automatically refund a credit. The
same email can be retried within 24 hours for free and returns the cached result. Live requests with
50-second diagnostic timeouts consumed one credit, while exact retries returned in under one second
with `credits_used=0`. treg's real upstream timeout is 180 seconds: a fresh reserved-domain request
completed successfully after 108.5 seconds and reported one credit. The public OpenAPI statement
that the server returns a refunded 408 after 15 seconds does not match this observed behavior.

## Async behavior and capacity

Quick bulk returned 202, charged exactly the number of fresh inputs, and exposed an identifier plus
a 30-second retry interval. Immediate polling returned processing; a later cached batch returned
completed results. Deep submission returned 202 and charged three credits for one input. Deep polling
returned pending `results_24`, `results_48`, and `results_72` windows with a live 259,200-second retry
interval. Poll responses exposed no charge field; Scrubby's pricing assigns credits at submission.

The documented request rate is 25 requests per second (1,500 per minute). No free standalone
account-balance or usage endpoint is documented, so capacity is manual and `NO_BALANCE_API` reports
that deliberate limitation instead of the misleading `no fetcher written yet`. Verification
responses expose `remaining_credits`, but treg does not spend a verification merely to collect
capacity. No exhaustion response was forced and no overflow route is claimed.

## Live evidence ledger

Only public or reserved-domain addresses were used. Fixtures remove identifiers, contact values, and
absolute balances. The assigned key and canonical environment file were never printed or changed.

| Check | HTTP / transport | Observed credit result |
|---|---:|---:|
| No key / bogus key fetch probe | 401 / 401 | 0 |
| Valid key nonexistent fetch probe | 404 | 0 |
| Invalid email syntax | 400 | 0 |
| Fresh synchronous verification | 200 | 1 |
| Exact retry within 24 hours | 200 | 0 |
| Fresh request under production timeout | 200 after 108.5s | 1 |
| Quick bulk, two inputs | 202 | 2 |
| Quick bulk polling | 200 processing/completed | 0 |
| Deep bulk, one input | 202 | 3 |
| Deep polling | 200 processing | 0 |

The bounded discovery and recheck passes stayed below the authorized 25-credit maximum.
