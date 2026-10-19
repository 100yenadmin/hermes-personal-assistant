# Personal Assistant authority and privacy contract

This document describes the product-level authority, data, and proof boundaries
for the Personal Assistant Plugin. Domain workflows may narrow these rules; they
cannot widen them merely because an integration or credential is available.

## What Personal Assistant may retain

Inside the approved Hermes profile, the plugin may retain the minimum durable
state needed for continuity and safe follow-through, including:

- focused source and context records;
- stable action, event, and projection identities;
- source revisions and reconciliation obligations;
- provider-attempt state and bounded safe receipts;
- automation preferences and notification identities;
- calendar-binding metadata for an explicitly selected account and calendar;
- opt-in exact-action authorization envelopes without retained raw tool
  arguments; and
- an opt-in private conversation-evidence queue.

Native Hermes Kanban remains authoritative for commitment status. Provider and
canonical systems remain authoritative for their own results.

The compatibility ledger path is `state/travel-ledger/travel.sqlite`. Its name is
historical; the ledger now supports broader PA state. Changing the path is a
migration decision, not a documentation rename.

## What installation enables

Installation places reviewed source in the Hermes plugin directory. It does not:

- enable or load the plugin;
- start a recurring job;
- install the optional conversation-delivery startup hook;
- grant conversation-injection permission;
- authenticate a provider;
- send, purchase, book, cancel, update, or delete anything;
- change a calendar, mailbox, customer system, or provider account; or
- establish fleet approval or customer readiness.

Daily Ops, conversation delivery, and provider-facing workflows require their own
explicit setup and acceptance.

## Authority for external actions

Configuration and credential access prove neither user intent nor transaction
authority. A provider-visible action must follow the selected domain workflow's
material-detail review, confirmation, dispatch, readback, and reconciliation
contract.

Where a PA workflow uses exact-action authorization, the scope binds one tool
name and complete argument digest to trusted runtime identity, freshness,
preconditions, and one-use execution budget. This protects call integrity and
replay. It does not prove that the material summary was semantically correct or
that a human originated the approval.

A changed recipient, amount, item, itinerary, time, destination, or material term
requires refreshed review and confirmation. A timeout or lost response is an
unknown outcome. The original attempt must be reconciled against provider state
before another attempt is considered.

## Data flow and model exposure

Provider content, files, email, calendar text, webpages, and retrieved records
are untrusted data. They cannot authorize another tool call, change policy, or
request disclosure of secrets.

Selected bounded and redacted content may reach the configured agent/model
provider when the active workflow needs interpretation or formatting. Selected
output may reach an explicitly verified delivery target. It is therefore not
accurate to claim that all source content always remains local.

Credentials, private keys, tokens, raw customer datasets, full provider receipts,
and generated ledgers must not be copied into shared source, documentation,
fixtures, or exports.

## Retention and deletion

The profile may retain PA ledger state, safe receipts, deduplication state,
preferences, and optional evidence-queue records. Provider/model transcripts,
Hermes logs, host-managed output, and delivered messages follow their owning
systems' retention policies.

Pausing or disabling a workflow stops future work; it does not erase prior local
history, provider records, model transcripts, host logs, or delivered messages.
Disconnecting a calendar binding stops future synchronization but does not delete
existing provider events. Deletion and retention changes are separate operations
with their own authority and verification requirements.

## Optional features

### Daily Ops

Daily Ops reads only explicitly accepted sources and produces bounded packets. It
is configured separately and starts no jobs at installation. Its detailed source,
delivery, and privacy rules are in the
[Daily Ops customer contract](daily-ops-customer-contract.md).

### Conversation evidence delivery

Conversation delivery is disabled by default. It requires an exact existing
conversation route, a private state directory, an explicit host permission,
installation of the packaged startup hook, and an intentional restart. Queue
acknowledgement is not a provider delivery receipt.

## Proof boundaries

- `pa(status)` proves that the registered tool responded and reports recorded
  state; it does not prove every domain workflow.
- `pa(capabilities)` reports exposed integration surfaces; it does not prove
  authentication.
- Source tests and CI prove only the named behavior against the exact source or
  package under test.
- Installation identity proves which bytes were selected; it does not prove
  activation or provider access.
- Provider readback proves only the observed provider result.
- No single receipt establishes fleet approval, customer readiness, or complete
  semantic enforcement across all workflows.

Travel-specific, Daily Ops, gateway, and state-loop contracts may add stricter
requirements. When contracts differ, the more restrictive applicable workflow
boundary governs the action.
