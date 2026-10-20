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
6. Run readiness preflight for provider login/session, Browserbase Context, fallback browser lane, wallet/payment descriptor, funds, phone/contact, address, traveler profile, dates, and provider-required fields. Record the readiness status or blocker in `travel-ledger`.
7. Use saved credentials, saved sessions, Browserbase, browser profiles, Live Browser fallback, connected email/SMS/device lanes, and funded/reloadable payment lanes to reach the final button.
8. For login friction, CAPTCHA, address validation, checkout staging, or provider 401s, call `browserbase-checkout-lane`: prefer `browser_session` create, `agent-browser` connect, live view handoff, and release. The user makes the final tap.
9. Store a checkout checkpoint in `travel-ledger` after each meaningful provider step. On timeout or disconnect, reattach or restore from Context/checkpoint before starting over.
10. Stop for one compact final-state confirmation before paid submit, booking, check-in submit, ride request, food order, reservation, cancellation, outbound message, phone call, or material profile/payment change.
11. Use `travel-approval-packet` as the final confirmation summary for the final action and verify live provider state after confirmation. After submit/send/request, write the receipt, ticket id, order id, confirmation id, sent-message proof, calendar event id, or blocker status to `travel-ledger`.

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
I have the item in the cart. Instacart is on the login step, so I am moving it through Browserbase with the saved account session and keeping the cart open. I will bring you the final total and confirmation before placing the order.
```

## Completion

Report the final state by action: prepared, awaiting final confirmation, completed and verified, or continuing through the next executable path. Include the travel ledger trip/action/checkpoint ids when useful. Include evidence labels and descriptors, not raw credential values.
