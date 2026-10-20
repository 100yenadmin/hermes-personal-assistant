---
name: travel-ledger
description: Use when travel work needs durable trip memory, upcoming itinerary capture, provider action records, Browserbase checkout checkpoints, payment readiness, receipts, refund follow-up, or proof that an agent completed a travel step.
metadata:
  hermes:
    category: travel
    tags: ["travel", "memory", "ledger", "proof", "browserbase", "payments"]
---

# Travel Ledger

Use this skill to make travel work durable. The ledger is not a gate; it is the agent's working memory and proof trail for trips, provider actions, browser sessions, payment readiness, and receipts.

## Tool

With the native Personal Assistant plugin, record trips, provider actions and
checkpoints through the `pa` tool. It writes this same ledger and needs no shell:

- Provider step, final page, handoff or blocker:
  `pa(operation="action_upsert", data={"source_id": "<trip or errand>",
  "action_kind": "<booking|reservation|food_order|ride|call>",
  "occurrence": "<step>", "action_type": "note", "provider": "<site>",
  "status": "pending|awaiting-final-confirmation|blocked|completed",
  "fields": {"url": "...", "state": "...", "total": "...", "missing": [...], "next": "..."}})`.
  The same `source_id`, `action_kind` and `occurrence` update one record.
  `note` is for preparation and evidence. An unresolved refund or return keeps
  `action_type` `refund` or `return`, and linked Kanban work uses `commitment`,
  as in `personal-assistant:personal-assistant`.
- Browser checkpoint: the same call with `action_kind="checkpoint"`, as in the
  Checkpoints rule of `personal-assistant:personal-assistant`.
- A trip from a calendar file: `pa(operation="trip_import", data={"trip_id": "...", "ics_path": "..."})`. If `next_step.offer_trip_watch`, load `personal-assistant:trip-concierge` and ask `next_step.question` once.
- Read back with `pa(operation="context", data={"kind": "action", "action_id": "<returned action_id>"})`.

The helper below covers the rest (payment readiness, connectivity profiles,
summaries) and is the fallback for these records when there is no `pa` tool.
It needs shell access. Resolve the helper from the installed package root (the directory containing
`skills/`), so the same command works for a Hermes package install and a
checkout:

```bash
python3 ./skills/travel-ledger/scripts/travel_ledger.py --help
```

Hermes must export an existing, profile-scoped `HERMES_HOME` (or an explicit
`HERMES_WORKSPACE_ROOT`) before invoking the helper. With no override, the
ledger is created at `<HERMES_HOME>/state/travel-ledger/travel.sqlite`.
When both roots are set, a valid `HERMES_HOME` is authoritative and the
workspace root is not inspected. Operators may explicitly provision
`TRAVEL_LEDGER_DB`; an absolute value is accepted only under the selected root,
and a relative value is resolved under that root. The helper fails closed when
the root is missing, insecure, or the path escapes it; symlinked path
components, non-directory parents, insecure directory permissions, and
non-regular or group/world-writable database files are rejected. Native PA
connections rerun these checks immediately before each open; this narrows
post-construction path replacement, but a pathname check/open race against a
hostile local process is not an OS sandbox guarantee. It never falls back to
`HOME` or an unbound legacy directory.

## Record Types

- Trip: durable itinerary record with destinations, dates, lodging, flights, addresses, source confidence, and open gaps.
- Action: provider-heavy work such as booking, refund request, cancellation, check-in, food order, ride, reservation, message, call, calendar write, or payment setup.
- Browser checkpoint: configured-browser continuation point with provider, opaque session or context reference, URL, cart or booking state, total, missing fields, and expiry.
- Payment readiness: wallet/card/provider payment descriptor, funds status, budget, and missing setup.
- Connectivity profile: subject-scoped dated device, workload, trip, and ownership facts. Values are allowlisted and stored with `confirmed_at` and `source`; this is not a credential store.

## Required Moments

Write or update the ledger:

1. After itinerary intake or "what trips are coming up" research.
2. Before provider-heavy work starts, with readiness gaps.
3. After every meaningful Browserbase/provider step.
4. At the final button before confirmation.
5. After submit/send/request with proof: confirmation id, order id, ticket id, receipt, sent-message copy, calendar event id, ride status, or screenshot path.
6. When blocked, with the exact next executable path.
7. After every search or availability check the user asked for, even when nothing matched or nothing was prepared.

## Commands

Initialize:

```bash
python3 ./skills/travel-ledger/scripts/travel_ledger.py init
```

Record a trip:

```bash
python3 ./skills/travel-ledger/scripts/travel_ledger.py trip-upsert \
  --trip-id trip-2026-07 \
  --title "Upcoming trip" \
  --status planning \
  --field destinations='["Destination city"]' \
  --field open_gaps='["lodging address unknown"]' \
  --field source_confidence=medium
```

Start or update an action:

```bash
python3 ./skills/travel-ledger/scripts/travel_ledger.py action-upsert \
  --action-id refund-hotel-abc123 \
  --trip-id trip-2026-07 \
  --type refund-request \
  --provider "Example Hotel" \
  --status awaiting-final-confirmation \
  --field final_action="Send refund request" \
  --field message_preview="Short factual request..."
```

Record a checkpoint with `bb_session_id` from `browser_session`:

```bash
python3 ./skills/travel-ledger/scripts/travel_ledger.py browser-checkpoint \
  --action-id food-order-checkpoint \
  --provider instacart \
  --lane browserbase \
  --session-id "<bb_session_id>" \
  --url "$CURRENT_URL" \
  --state "cart staged, address entered, awaiting final total"
```

Record payment readiness:

```bash
python3 ./skills/travel-ledger/scripts/travel_ledger.py payment-readiness \
  --provider lobster \
  --status ready \
  --descriptor "configured payment method" \
  --budget 250 \
  --currency USD
```

Record or read connectivity facts through the same ledger (never a second JSON store):

```bash
python3 ./skills/travel-ledger/scripts/travel_ledger.py connectivity-upsert \
  --subject-id traveler-context --input connectivity-facts.json
python3 ./skills/travel-ledger/scripts/travel_ledger.py connectivity-show \
  --subject-id traveler-context --format markdown
python3 ./skills/travel-ledger/scripts/travel_ledger.py connectivity-intake \
  --subject-id traveler-context --as-of 2026-09-20T12:00:00+07:00
```

Connectivity reads and freshness checks do not renew timestamps. The default recheck threshold is strictly older than 45 days; exactly 45 days remains current. Invalid or future stored timestamps need confirmation.

Remove confirmed profile facts only through the subject-scoped operation. Named
fields require `--confirm`; clearing every field requires both `--clear-all` and
`--confirm`:

```bash
python3 ./skills/travel-ledger/scripts/travel_ledger.py connectivity-remove \
  --subject-id traveler-context --field region --confirm
python3 ./skills/travel-ledger/scripts/travel_ledger.py connectivity-remove \
  --subject-id traveler-context --clear-all --confirm
```

Summarize:

```bash
python3 ./skills/travel-ledger/scripts/travel_ledger.py summary --json
```

The generic summary is intentionally unscoped and omits subject-scoped
connectivity profiles. Use `connectivity-show` or `connectivity-intake` with an
explicit `--subject-id` for those facts.

## User-Facing Style

Use ledger facts to sound capable and current:

```text
I have the trip recorded. The open gaps are lodging address and airport ride timing. I am checking lodging confirmations first, then I will stage the missing actions and bring you final confirmations where needed.
```

When blocked:

```text
Instacart timed out, but the cart checkpoint is saved. I am reattaching the same Browserbase session and continuing from the cart instead of rebuilding it.
```

## Do Not Store

Do not store raw passwords, MFA codes, raw card numbers, CVV, passport scans, cookies, session tokens, private keys, or full identity documents in the ledger. Store descriptors and proof pointers instead.
