---
title: BounceBan — email verification, billing boundaries and capacity
status: shipped
sources:
  - src/treg/catalog/bounceban.yaml
  - src/treg/catalog/examples/bounceban.people.email.verify.json
  - src/treg/catalog/examples/bounceban.people.email.verify.waterfall.json
  - src/treg/catalog/examples/bounceban.people.email.verify.status.json
  - src/treg/catalog/examples/bounceban.people.email.verify.bulk.json
  - src/treg/catalog/examples/bounceban.people.email.verify.bulk.status.json
  - src/treg/catalog/examples/bounceban.people.email.verify.bulk.emails.json
  - src/treg/catalog/examples/bounceban.people.email.verify.bulk.dump.json
  - src/treg/catalog/examples/bounceban.people.email.verify.bulk.export.json
  - src/treg/catalog/examples/bounceban.account.usage.json
  - src/treg/catalog/adapters.yaml
  - src/treg/catalog/fx.yaml
  - src/treg/config.py
  - src/treg/oauth_providers.py
  - src/treg/domain/capacity/collectors.py
  - src/treg/domain/capacity/policy.py
  - src/treg/web/logos/bounceban.svg
  - tests/test_key_providers.py
  - tests/test_oauth_providers_m3.py
  - tests/test_capacity_collectors.py
  - tests/test_capacity_overflow_routes.py
  - tests/test_catalog_validate.py
  - tests/test_marketplace_call.py
  - tests/test_routing.py
  - tests/test_enrich_arena.py
related:
  - architecture/catalog.md
  - architecture/auth-secrets.md
  - architecture/money.md
  - interface/enrich-arena.md
  - ops/capacity.md
---

# BounceBan

BounceBan supplies email verification through two hosts. The standard API uses
`https://api.bounceban.com`; the waterfall tool overrides the host with
`https://api-waterfall.bounceban.com`. Both inject the pasted API key as the raw value of the
`Authorization` header. There is no `Bearer` prefix.

## Catalog boundary

The catalog exposes nine safe operations: standard and waterfall single verification, single-task
status, JSON bulk creation, four bulk read/export operations, and account usage. The documented
multipart CSV upload is omitted because the catalog has no file-upload contract. Bulk destruction
is omitted because it is destructive. `/v1/check` is omitted because it uses a separate Check Plan
whose acquisition price and capacity were not supplied.

Only `bounceban.people.email.verify` is platform eligible. It uses the standard host and does not
expose `disable_catchall_verify` or webhook inputs. Every accepted request therefore has the proven
one-credit price. Its `per_call` settlement charges an accepted HTTP 2xx submission even when the
body says `status=verifying`; malformed input returned HTTP 400 with no reported charge and releases
the hold through the shared settlement rule. One credit costs $0.004 from the supplied $40 / 10,000
purchase. No provider-specific money branch is added.

Waterfall and bulk operations are BYOK only. Waterfall same-address retries inside 30 minutes do
not deduct a new credit, but the repeated response reports the original credit count. A waterfall
catch-all skipped with `disable_catchall_verify=1` can also cost zero. Bulk submission reserves
credits first and refunds unknown results only when the task finishes. Those delayed and ambiguous
rules cannot be settled exactly on a shared key, and task identifiers belong to the connected
account. The related status, result, dump, and export operations stay with that account.

## Routing and Arena

The verified adapter adds only the standard single endpoint to `treg.people.email.verify`. It maps
the contract email to `queryParams.email`, returns `result` as the status, maps `score`, and treats
a missing result as a routing miss. A provider-native `deliverable` result is valid. Other verdicts
remain false with their original status so callers and Arena can distinguish risky, undeliverable,
and unknown answers.

The existing route planner and Arena catalog discovery pick up that adapter. There is no direct
BounceBan registration in routing or Arena. Pending `verifying` bodies are misses for waterfall
progress, but the accepted standard request is still charged its fixed upstream cost.

## Credentials and health

`TREG_PLATFORM_KEY_BOUNCEBAN` supplies the optional shared platform binding. A team's connected key
still wins and is unmetered by treg. The connection probe calls the free `GET /v1/account` route;
the real connection flow rejected a bogus key with HTTP 401 and accepted a valid key with HTTP 200.
Provisioning installs the standard base tool and the waterfall-host tool without copying the key
into catalog data, logs, or examples.

## Capacity

The capacity collector also uses the free account route and reads `available_credits`. Zero and
finite nonnegative integer or floating-point values are valid. Missing, Boolean, string, negative,
or non-finite values are unknown. The policy is `credits / manual / api`; no renewal or auto-top-up
behavior is inferred. The only platform-served tool is standard single verification, documented at
100 requests per second; the conservative shared-key rate is one quarter of that allowance at 25
requests per second. BYOK calls do not use the shared-key limiter.

The account endpoint reported the expected deductions during bounded discovery. Standard accepted
requests used one credit, a repeated waterfall request did not deduct again, a skipped catch-all
used zero, and a completed two-row bulk task retained one credit after refunding its unknown row.
The Check API returned HTTP 403 because the account had no Check Plan. Discovery and the final
platform-path check used four verification credits in total, below the 25-credit limit.

## Operational limits

The observed account limits were 100 requests per second for single verification and single status,
5 per second for bulk creation, 25 per second for bulk reads, and 5 per second for account usage.
BounceBan retains verification results for 90 days. These facts describe upstream behavior; treg
does not add its own task store or webhook receiver.

No overflow route or alternate provider adapter is claimed by this integration. Production serving
still requires the normal platform key and provider allow-list configuration; this change does not
enable either.

The dashboard logo wraps BounceBan's official 32-pixel favicon in the repository's SVG asset
contract. Its source URL is recorded in the asset itself.
