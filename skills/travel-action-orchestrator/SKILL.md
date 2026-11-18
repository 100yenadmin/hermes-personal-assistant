---
name: travel-action-orchestrator
description: Coordinate a multi-action travel request through one accountable owner and qualified skills.
metadata:
  hermes:
    category: travel
    tags: ["travel", "orchestration", "browser", "questions"]
---

# Travel Action Orchestrator

Every `references/...` path in this skill is relative to this skill directory.

Coordinate multi-step travel work like an executive assistant. Keep the main agent accountable for readiness, checkpoints, credential/payment/browser lanes, final-state confirmations, final actions, verification, and user-facing report.

## Read

- `references/orchestration-playbook.md` for task flow and optional parallel research.
- `references/standing-orders.md` for final confirmation rules.
- `references/browser-auth.md` before assigning browser or credential work.
- `references/checkout-checkpoints.md` before browser-heavy provider work.
- `references/final-state-double-check.md` before final submit/send/request.
- `travel-ledger` before trip capture, provider-heavy work, browser checkpoints, payment readiness, and proof reporting.

## Hermes package path

When this workflow invokes the ledger helper, resolve it from the installed
package root (the directory containing `skills/`):

```bash
python3 ./skills/travel-ledger/scripts/travel_ledger.py <command>
```

The ledger helper uses the active Hermes profile/workspace binding for its
database; do not substitute a host-specific skill path.

## Workflow

1. Build or update the active trip ledger state: traveler, destination, dates, timezone, budget, constraints, lodging, flights, accounts, payment lane, source confidence, open gaps, and known confirmations.
2. Ask only for missing facts that block action or materially change risk.
3. Keep one accountable owner. Use a separate research lane only when the user or active runtime policy explicitly requests it and the work is independent.
4. Merge findings into a short decision set. If provider facts conflict, verify directly before proceeding.
5. Load the relevant qualified skill for booking, check-in, food, rideshare, reservation, calendar, or nudges. Load payment guidance only when the user selected that optional integration.
6. Preflight provider login, session and fallback browsers, PA Browserbase readiness (`remote_browser`), wallet/payment descriptor, funds, phone/contact, address, traveler profile, dates, and provider-required fields. Record readiness or blockers in `travel-ledger`.
7. Use saved credentials and sessions, browser profiles, configured browser lanes, connected email/SMS/device lanes, and funded/reloadable payment lanes to reach the final button.
8. For login, CAPTCHA, address validation, checkout staging, or provider 401s, follow [Owner Handoff](../browserbase-checkout-lane/SKILL.md#owner-handoff) in `browserbase-checkout-lane`. Use the PA live view when available and follow the `browser_exec` fallback when needed.
9. Store a checkout checkpoint in `travel-ledger` after each meaningful provider step. On timeout or disconnect, resume in the same browser when possible or restore from the checkpoint.
10. Stop for one compact final-state confirmation before paid submit, booking, check-in submit, ride request, food order, reservation, cancellation, outbound message, phone call, or material profile/payment change.
11. Use `travel-approval-packet` as the final confirmation summary for the final action and verify live provider state after confirmation. After submit/send/request, write the receipt, ticket id, order id, confirmation id, sent-message proof, calendar event id, or blocker status to `travel-ledger`.

## Changed or cancelled leg

1. Read `pa trip_watch_plan action=disruption trip_id=…` for changed legs, affected bookings and reminders.
2. Look up 2 or 3 real replacement options on the airline or Trip.com with the existing booking skills; reach the final page without booking.
3. For each option, name the replacement leg and what happens to every affected booking (keep, move or cancel), with its cancellation deadline. Give the total cost and arrival-time difference shown on the provider pages; mark missing facts as unknown.
4. Send ONE approval packet. Change nothing until the owner names one option.
5. Then prepare the rebooking, followed by each moved or cancelled booking, as separate governed exact actions. Act on each only with its own confirm and read each provider result back.
6. Record each confirmed readback with `action_result` and `follow_through`. Record a moved booking's result with `follow_through.replaces` naming the old booking action: PA removes the old trip item and cancels its pending reminders. A cancellation records `replaces` alone.

If the owner says no, change nothing and record nothing.

## Optional parallel work

Keep one accountable agent by default. When explicitly authorized parallel work
is useful, keep it to independent research or read-only page inspection. The owning
agent keeps readiness, confirmation, final action, verification and the report.

## Question Style

Ask compact questions with a clear reason:

```text
I can do the flight, hotel, late-arrival food, and ride. I need two constraints before I start: hotel budget per night, and whether direct flights are required.
```

If the user provides app credentials, save them and acknowledge plainly: `Saved. I'll use this for the provider when you ask.` Ask only for one-time verification or missing trip constraints when the workflow cannot continue without them.

## Blocker Style

Use an executable next step, not a refusal.

```text
I prepared [items] for [address] at [time]. The last total I saw was [total]. Open [page link], sign in, and review the details. If they match and you want to order, press Place Order. I can't see your device. Please reply with the order confirmation.
```

## Completion

Report the final state by action: prepared, awaiting final confirmation, completed and verified, or continuing through the next executable path. Include the travel ledger trip/action/checkpoint ids when useful. Include evidence labels and descriptors, not raw credential values.
