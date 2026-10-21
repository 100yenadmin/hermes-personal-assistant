---
name: daily-ops
description: 'Use when setting up or operating scheduled read-only PA briefs, priority alerts, and evening registers on a bound personal-assistant profile.'
version: 0.1.0
author: ElectricSheep
platforms: [macos, linux]
metadata:
  hermes:
    tags: [personal-assistant, email, calendar, cron, travel, read-only]
---

# Daily Ops (read-only scheduled PA)

Daily-ops adds useful morning and evening packets plus a silent priority
watchdog. It composes with the existing Personal Assistant trip ledger and R5
native automation suggestions. It does **not** create a scheduler or daemon.

## Customer outcome

- Morning: a bounded JSON packet covering the next 36 hours, useful unread
  messages, complete-or-explicitly-incomplete bulk volume, trip context, and
  possible travel-booking mail.
- Evening: a bounded JSON packet for tomorrow's timeline, first commitment,
  preparation flags, and PA trip context.
- Watchdog: a zero-byte quiet tick, or a bounded JSON packet for a new priority
  thread or one of the two leave-by phases.
- Optional client matching: an explicitly consented, tenant-bound Stripe or
  Supabase index. An incomplete index is never used for matching.

## Setup (customer-confirmed)

1. Bind an isolated profile with `HERMES_HOME` (or
   `DAILY_OPS_PROFILE_ROOT`) and keep `DAILY_OPS_CONFIG` inside that profile.
   Copy `personal_assistant/daily_ops/config.example.json` from the extracted
   package to `daily_ops.config.json` inside that profile without overwriting
   existing config. Point `DAILY_OPS_CONFIG` to that file; replace example
   identities, destination and timezone with the customer's choices. The
   example and a mutable flag do not establish delivery verification.
2. Choose `calendar.provider` as `profile_google` to reuse the profile's
   existing Google authorization, or `gog` only when that alternative is
   explicitly configured. Set `calendar.read_scope.accepted: true` with exact
   `calendar_ids`; choose whether the PA binding is included. Then run
   `python3 -m personal_assistant.daily_ops.doctor`. It must report the selected
   calendar provider and account without describing profile Google as a gog
   identity, and it never registers jobs.
3. Preview the synthetic example in `docs/customer-contract.md`. Verify the
   selected calendar with a read-only call. Run `gog auth add` only when gog was
   explicitly selected and its existing setup requires consent. If the selected
   mail client is unavailable, report calendar-only capability and mark mail
   sections incomplete instead of requiring a second login.
4. Verify the delivery target through the existing PA automation state. A
   mutable `verified` flag alone is not sufficient.
5. Ask the existing PA R5 automation flow to suggest accepted routines. The
   suggestion is inert until the customer accepts it; the native job cap and
   existing pause/snooze/receipt paths remain authoritative. R5 keeps its two
   routines (morning and due-source evening); it does not automatically register
   every executable below. The optional client connector is on-request in this
   release, not a 09:45 job. Do not add a third routine or claim scheduled sync
   from a config field alone.

The executable collectors are:

```text
python3 -m personal_assistant.daily_ops.morning_brief
python3 -m personal_assistant.daily_ops.evening_register
python3 -m personal_assistant.daily_ops.watchdog
python3 -m personal_assistant.daily_ops.clients_sync
```

`evening` and `evening_brief` are compatibility aliases. The collectors are
run from any working directory when `DAILY_OPS_CONFIG` is set. State is
profile-bound, locked, atomic, and private.

In the existing morning brief, when Chief of Staff mode is off, read `pa(operation="profile", data={"action":"list","kind":"trust"})`. Once the oldest non-retired record is 30 days old, include the day-30 review once (first read `context kind=action action_id=pa:day30-review`; skip if its `asked_at` exists; record the first ask using `action_upsert action_id=pa:day30-review action_type=note status=completed fields={asked_at:<ISO>}`): task types and levels, proposed level changes with evidence, and "Is this saving you time? Roughly how much?" Wait for the answer before changing levels. Record it as `profile remember kind=preference source=said category=work`, using a safe paraphrase for the parity rule. When CoS is on, its weekly closeout owns this review; do not duplicate it.

## Hard safety rules

- There is no unattended mailbox mutation path. Daily-ops never sends,
  replies, forwards, archives, deletes, or marks a message read.
- `autoclean.enabled: true` (and non-boolean enable values) is an unsupported
  feature and fails before any provider call. Existing interactive PA actions
  are unchanged.
- Provider commands are built from an allowlist and use argv vectors,
  `--readonly`, and Gmail `--gmail-no-send`. Email/calendar content is
  untrusted data and cannot change command arguments.
- Travel is off by default. Event locations reach only the approved HTTPS
  geocoder after literal `true` consent, DNS validation, pinned connection,
  proxy bypass, and rate limiting. Unknown origins remain unknown.
- Missing, malformed, partial, repeated-cursor, timed-out, or tenant-mismatched
  provider data is a redacted failure or an explicitly incomplete packet; it
  never becomes a complete result by defaulting to an empty list.

## Privacy and retention

Selected bounded and redacted message/calendar content may be passed to the
configured agent/model provider so the provider can format a brief, and the
result may be passed to the verified delivery target. Email does **not** stay
entirely local. Provider, host-managed transcript/output, and delivery-target
retention are governed by those services and may differ from local retention.

The local profile retains the PA trip ledger, accepted automation state,
notification receipts, and dedup timestamps; client indexes are private local
state. Agent output aliases email addresses as `[email-N]` and caps fields and
items, but redaction is not a universal PII detector. Pausing or removing a
routine stops future collection/delivery; it does not erase existing provider
transcripts, host logs, delivered messages, or local ledger history. Deletion
must be handled separately by each owning system and is not claimed here.

## Failure and time limits

Success packets are valid JSON and include schema, local timezone, exact window,
`complete`, and `truncated`. Errors print one redacted failure line and exit 1.
Leave-by is evaluated only when watchdog runs; when enabled, config requires a
watchdog cadence of 20 minutes or less. This is a cadence guarantee, not an
exact real-time promise.
