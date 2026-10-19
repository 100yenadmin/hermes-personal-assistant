# Generic state-loop contract

The PA state-loop module is an account-agnostic control plane for keeping durable
management state synchronized with operational events. It does not own account,
project, health, satisfaction, provider, or scheduling semantics.

```text
observe → normalize → reduce → apply → verify → reconcile
```

## Operations

### `event_upsert`

Register one material event using `source_type`, `source_id`, and an explicit
`source_revision`. Supply a non-empty `projections` list; every projection needs
`projection_key`, `target_type`, and `target_id`, with optional
`expected_revision`. A projection may also declare caller-owned
`freshness_seconds`; PA supplies no domain cadence default. Optional `payload`
must contain only bounded reducer inputs or
digests—not copied customer evidence.

The event ID is deterministic from source type and source ID. Replaying identical
content at the same revision is a no-op. Content may change only with a new source
revision. A new revision archives prior projection receipts and reopens the new
required projection set. An already superseded revision cannot become current
again.

### `projection_claim`

Claim one required projection with `event_id`, `projection_key`, and `claimed_by`.
The operation returns a random claim token and bounded lease. Pending and explicitly
failed projections may be claimed; an unexpired claim, confirmed result,
not-applicable result, or unknown outcome may not be claimed.

### `projection_result`

Finish a claim with its exact token and one outcome:

- `confirmed` — canonical/provider readback succeeded; proof is required.
- `not_applicable` — the declared projection was deliberately unnecessary; proof
  or rationale is required.
- `failed` — no successful write is claimed; the failure remains reconcilable and
  may be explicitly reclaimed.
- `unknown` — submission outcome is uncertain; it remains blocked and cannot be
  automatically reclaimed. Reconcile the provider, then record `confirmed`,
  `failed`, or `not_applicable` against the same claim token with evidence.

Result recording is idempotent for the same token, outcome, and proof. Every
attempt receipt is retained when a failed projection is explicitly retried.

### `reconcile`

Return every nonterminal projection, optionally filtered by `event_id`. An empty
result means all currently required projections are confirmed or not applicable;
it does not prove domain correctness beyond the recorded readbacks.

### `freshness`

Evaluate projection attention at an explicit timezone-aware `at` timestamp,
optionally filtered by `event_id`. The read-only result contains `issues`,
`count`, and `evaluated_at`. Machine-readable reasons are:

- `never_processed` for a pending projection;
- `overdue_projection` for a claimed projection whose lease has expired;
- `failed_projection` or `unknown_projection` for those recorded outcomes; and
- `freshness_expired` when a confirmed projection reaches its caller-declared
  deadline.

Active unexpired claims do not wake the precheck. A confirmed projection is
fresh before `fresh_until` and stale at the exact deadline. Same-revision event
replay preserves the existing deadline; a new source revision archives prior
freshness evidence and starts with no deadline until its projection is confirmed.

## Ownership and authority

PA owns event identity, source revision history, projection obligations, claims,
receipts, and reconciliation state. Domain adapters own reduction logic and
canonical destinations. Hermes owns scheduling. Provider and external writes keep
their existing confirmation and readback requirements; registering an event or
claim never grants authority to mutate a destination.

## Migration and rollback

Schema initialization is additive. Freshness state lives in separate current and
history tables so existing projection-table column layouts remain unchanged and
the previous package's positional inserts remain compatible after rollback.
Concurrent initializers use idempotent `create table if not exists` statements,
not an unlocked check-then-`alter table` sequence. Existing trip/action and
core state-loop rows are not migrated or rewritten. After a rollback changes a
source revision, re-enable archives revision-matched freshness evidence and
removes stale current freshness rows before evaluating projections. Disabling or
reverting the feature otherwise leaves freshness records intact for a later
compatible re-enable; there is no destructive down-migration.
