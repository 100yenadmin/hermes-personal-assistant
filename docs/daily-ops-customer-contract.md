# Daily Ops customer contract

Daily Ops is an optional, read-only composition over explicitly accepted
Personal Assistant sources. This contract narrows the broader
[Personal Assistant authority and privacy contract](customer-contract.md).

## What Daily Ops reads

Depending on approved configuration, Daily Ops may read:

- an explicitly accepted set of Google Calendars;
- configured Gmail accounts through the supported read-only collector;
- Personal Assistant trip context from the existing PA ledger; and
- an explicitly consented customer-owned account connector.

The preferred calendar path reuses existing profile Google authorization and
verifies the account. `gog` is an explicitly selected alternative, not a
mandatory second login. The PA-owned write calendar joins the read set only when
`include_pa_binding` is the literal boolean `true` and the binding account
matches.

## What Daily Ops does not do

Daily Ops does not send, reply, forward, archive, delete, or mark mail read. It
does not move money, accept meetings, write recurring calendar series, send
attendee updates, or register jobs. Existing interactive PA workflows are
separate and retain their own authority contracts.

Unattended mailbox cleanup is unsupported. `autoclean.enabled` must be omitted or
the literal JSON boolean `false`; any other value is rejected before a provider
call.

## Output and completeness

Morning, priority, and evening outputs are bounded and redacted. A success packet
identifies its schema, customer timezone, exact time window, completeness, and
truncation. Per-source coverage remains visible. A partial provider response is
never labeled complete.

A calendar source may remain useful when an optional mail collector is
unavailable, but the packet must identify missing mail coverage and remain
incomplete. Recurring calendar occurrences may be read; that does not grant
series-write authority.

A verified destination is selected through the accepted PA automation or
conversation-delivery path. A mutable configuration flag is not delivery proof.
Admission to asynchronous conversation scheduling is not a transport receipt.

## Synthetic example

A synthetic morning packet can show the next 36 hours of calendar commitments,
a bounded list of priority human messages, a bulk-message count, and trip context
from one active PA trip. An evening packet can show the next local day's timeline,
first commitment, and preparation flags. Fixture examples are not live customer
success claims.

## Travel and location

Trip context comes from the existing PA ledger, not a second itinerary store.
Location sharing is off by default. Any enabled travel-location workflow requires
literal consent and its own approved endpoint, network, cadence, and origin
checks. Multiple, missing, invalid, or overlapping origins remain unknown.

## Optional account connectors

An optional connector verifies tenant, account, project, and live/test identity
before reading. Malformed, partial, repeated-cursor, timeout, or incomplete reads
invalidate the published index rather than leaving stale complete data trusted. A
disabled connector performs no provider calls.

## Privacy and retention

Selected bounded and redacted email and calendar content may reach the configured
agent/model provider for formatting and the verified delivery target. Email does
not therefore remain entirely local.

Local state may include the PA ledger, accepted automation state, notification
receipts, deduplication timestamps, and an optional account index. Provider/model
transcripts, host output, and delivered messages follow their owning services'
retention policies. Pausing stops future collection and delivery; it does not
erase prior local history, provider transcripts, host logs, or delivered
messages.

See [Daily Ops](daily-ops.md) for configuration and operating details.
