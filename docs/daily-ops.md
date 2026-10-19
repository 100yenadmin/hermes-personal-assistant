# Daily Ops — scheduled PA operations

Daily Ops is an optional, read-only composition over explicitly accepted
Personal Assistant sources and the existing automation contract. It is one
feature of the broader Personal Assistant control plane, not the product as a
whole. See the [Daily Ops customer contract](daily-ops-customer-contract.md) for
its source, delivery, privacy, retention, and unsupported-operation boundaries.

## Operating model

| Operation | Suggested schedule | Output |
|---|---|---|
| Morning brief | 10:00 local | bounded JSON packet for agent formatting |
| Priority watchdog | `*/15` when travel is enabled | zero bytes when quiet; bounded JSON when firing |
| Evening register | 21:00 local | bounded JSON packet for agent formatting |
| Client sync | on request, opt-in | silent when unchanged; changed summary or failure |

The schedule is only a suggestion. The existing PA automation/R5 flow owns
acceptance, native-job limits, pause/snooze, and notification receipts. No
install hook, doctor run, or config load registers a job. These are component
capabilities, not four installed routines. R5 retains two native routines:
morning brief and due-source evening check. Client sync is on-request in this
release, not automatically invoked at 09:45. Watchdog execution requires its
own accepted host integration within existing native-job limits; this package
does not silently add a third or fourth routine.

When `delivery.verified` is true, doctor requires a read-back reference under
`delivery.verification` to an existing accepted PA automation rule and an
existing notification action claimed through `pa automations`. The reference
must name the exact `occurrence_id`, `rule_id`, and `rule_revision`. The rule's
explicit timezone-aware `accepted_at`/`verified_at` and the notification's
`delivered` receipt are checked against a canonical payload containing the
profile, account, timezone, exact destination, and rule revision. The receipt
must include provider, nonempty `receipt_reference` or `receipt_id`, and a
timezone-aware `observed_at`; generic SQLite row timestamps and a mutable
boolean are not delivery authority. Setup uses the existing claim/receipt/rule
API with synthetic receipts only in tests. The PA ledger currently trusts the
caller-provided provider evidence, so this is lifecycle/evidence binding, not
cryptographic transport attestation.

## Data contracts

Each success packet has `schema: personal-assistant.daily-ops.v3`, `kind`, a
customer-timezone window, and explicit `complete`/`truncated` booleans. Sections
are bounded at item and field boundaries and email addresses are aliased.
Provider failures produce one redacted `⚠️ daily-ops pipeline failure` line and
exit 1; a partial provider response is never labeled complete.

Calendar reads use one optional configuration block:

```json
{
  "calendar": {
    "provider": "profile_google",
    "account": "owner@example.com",
    "read_scope": {
      "accepted": true,
      "calendar_ids": ["primary"],
      "include_pa_binding": true
    }
  }
}
```

`account` may be omitted to use `accounts.work`. `profile_google` is the normal
profile path: it reuses the active profile's existing `google_token.json`, accepts
read-only or write-capable Calendar scopes, verifies the token's primary account,
and never starts OAuth. Set `provider` to `gog` only to choose the configured
alternative. Profiles without the new block retain the legacy `gog` primary
calendar behavior.

`calendar_ids` is the complete explicitly accepted read set. The PA-owned write
calendar is added only when `include_pa_binding` is the literal boolean `true`
and the binding account matches. Duplicate IDs are read once. Each packet carries
anonymous source-level coverage. Recurring events are expanded into occurrences;
typed `start`/`end`, IANA timezone, and event URL remain intact. One failed source
makes the packet incomplete while successful sources remain usable. Actual item,
field, string, or depth bounding sets `complete:false` and `truncated:true`.

Morning mail collection still uses the existing read-only `gog` path when it is
available. A `profile_google` calendar does not require a second `gog` login: if
mail collection is unavailable, the morning packet remains calendar-useful and
marks each missing mail section and the whole packet incomplete. It never claims
mailbox coverage in that state.

The morning window is the next 36 hours. The evening window is tomorrow in the
configured timezone, including all-day events as timeline facts but never as
leave-by alerts. Priority scans all unread mail, including Updates, and pages
until completion or reports bounded incomplete coverage. A new thread with the
same count has a new opaque dedup identity; suppression timestamps change only
on emission and expire.

Morning, evening, and leave-by watchdog reads resolve the same accepted calendar
scope. Calendar coverage is visible in the morning and evening calendar sections
and in a degraded watchdog packet. Reading recurring occurrences never grants a
series write or attendee-send capability.

## Travel and PA trip source

Trip context is read from the existing PA trip ledger (`Ledger`), not from a
second daily-ops itinerary file. A coordinate cache is only a derived fact with
ledger provenance. Multiple, missing, invalid, or ungeocoded origins remain
unknown. Leave-by phases are tied to event identity, occurrence start, source
revision, and phase (`heads` or `now`). Travel location sharing is off unless
all literal opt-ins and approved HTTPS/DNS/proxy/cadence checks pass.

## Client connector

The connector verifies the configured Stripe account and live/test mode before
listing, and verifies the exact Supabase project before querying. Every response,
member, page, cursor, and timestamp is validated. Failures atomically publish
an incomplete index before surfacing the error, so stale complete data cannot
remain trusted. A disabled connector performs zero provider calls.

## Privacy

Selected bounded/redacted content can reach the configured agent/model provider
for formatting and the verified delivery target. It is not accurate to say all
email stays local. Local state includes the PA ledger, notification receipts,
dedup timestamps, and optional client index. Pausing stops future work; it does
not delete local history, provider/model transcripts, host-managed output, or
messages already delivered. Those systems' deletion policies are separate.

## Explicitly unsupported/deferred

Unattended mailbox cleanup is unsupported in daily-ops: `autoclean.enabled: true`
or a non-boolean enable value fails before any provider call. Existing
interactive PA R6 and other recipes remain unchanged. Future cleanup would
require independent proof of the existing PA-ledger account/query/category,
expiry, cap, readback, concurrency, and unknown-outcome controls; this repair
adds no approval ledger or mutation system.
