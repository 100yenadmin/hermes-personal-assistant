# Personal Assistant documentation

Personal Assistant is a persistent personal-operations layer for Hermes. These
documents separate the product contract, operator procedures, workflow control
planes, and release evidence so a historical pilot detail is not mistaken for a
current product guarantee.

## Start here

- [Personal Assistant overview](personal-assistant.md) — purpose, architecture,
  capabilities, ownership, safe defaults, and current boundaries.
- [Product authority and privacy contract](customer-contract.md) — what the
  plugin may read, retain, or prepare; what requires separate authority; and
  what installation does not enable.
- [Repository README](../README.md) — quick start, installation, domain map, and
  compatibility identities.

## For users and product owners

- [Daily Ops](daily-ops.md) — optional read-only morning, priority, evening, and
  account views.
- [Daily Ops customer contract](daily-ops-customer-contract.md) — source,
  delivery, privacy, retention, and unsupported-operation boundaries for Daily
  Ops specifically.
- [Generic state-loop contract](state-loop.md) — durable event, projection,
  receipt, reconciliation, and freshness behavior.

## For workflow developers

- [Workflow-agnostic action gateway](workflow-authorization-gateway.md) — the
  opt-in exact-action protocol and enforcement model.
- [Action gateway review and activation](action-gateway-admin-happy-path.md) —
  synthetic review, installation, readback, and rollback guidance.
- [Generic state-loop contract](state-loop.md) — account-agnostic projection
  control without domain semantics or provider authority.

The action gateway and state loop are control-plane primitives. Domain workflows
remain responsible for semantic validation, confirmation, provider readback, and
canonical destination updates.

## For operators and maintainers

- [`after-install.md`](../after-install.md) — installed, enabled, loaded, and
  exercised are separate states; activation remains explicit.
- [Release process](release-process.md) — immutable-source selection, archive
  validation, publication, installation, and rollback boundaries.
- [Support Control version contract](support-control-version-contract.md) —
  compatibility package identity and enrolled-version metadata.
- [Canary scorecard](canary-scorecard.md) — bounded fixture-based evaluation;
  never a substitute for named provider or customer acceptance.

## Safe-default summary

Installation alone starts no jobs, grants no credentials or provider authority,
and enables neither Daily Ops nor conversation delivery. Ordinary unscoped tools
remain under normal Hermes policy. Stronger exact-action enforcement applies only
to an explicitly attached PA scope. Provider authentication, live routing,
customer acceptance, and fleet approval remain separate proof gates.

## Compatibility names

The current native plugin ID is `personal-assistant`. The package/archive name
`travel-agent-skills` and ledger path `state/travel-ledger/travel.sqlite` remain
for compatibility with existing installation, upgrade, and rollback records.
Travel is a supported domain pack, not the product identity.
