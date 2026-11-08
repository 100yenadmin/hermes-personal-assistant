---
name: personal-assistant:r5-brief-reminders
description: Prepare a daily brief and accepted reminders using native automation suggestions.
metadata:
  hermes:
    namespace: personal-assistant
    recipe: R5
    lazy: true
---
# Personal Assistant R5: Brief and reminders

Load for a daily brief, due-item review, or reminder change.
1. `pa.context` retrieves only relevant due, trip and source facts; `pa.next_action` excludes completed Kanban commitments.
2. `pa.action_upsert` prepares the brief or reminder with timing visible.
3. Read source and calendar state through existing integrations; `pa.action_upsert` records safe proof.
4. `pa.automations` suggests an accepted native routine; no job starts at install.
5. `pa.action_upsert` records brief, source gap, and follow-up; scheduled notification receipts use the contract below.
Expected outcome: a current brief or reminder receipt without duplicate notification.

## What every brief contains

Every daily brief lists what is still open in PA's own ledger, whatever the
calendar and inbox sources say. Read `pa next_action` with `loops_only: true`
and list each open loop in one line: who owes what, how old it is, and the chase
step due, for example "Cedar hasn't confirmed the tasting menu (2 days); day-2
nudge drafted, waiting for your yes." Then list due items from `pa next_action`.
If the daily-ops collector or a source cannot be read, say so in one line
("Calendar and inbox were not read: not connected yet") and still send the open
loops and due items. Never send a brief that only reports a source gap while open
loops exist. Record a suppressed receipt and reply `[SILENT]` only when there are
no open loops, no due items and nothing useful from the sources.

Load `personal-assistant:personal-assistant` for the exact tool argument and state contract. R5 has no provider transaction, so do not use `pa.action_prepare`, `pa.action_confirm`, `pa.action_claim`, or `pa.action_result` for a brief or reminder.

## Scheduled notification receipt

The native precheck supplies an already claimed `occurrence_id`. Use that exact
identity; never create another claim or resend to repair a missing receipt.
After verifying delivery through the accepted provider, call:

```json
{"operation":"automations","data":{"action":"receipt","occurrence_id":"<precheck occurrence_id>","receipt":"delivered","proof":{"provider":"<delivery provider>","receipt_reference":"<verified provider receipt reference>"}}}
```

For an explicitly accepted local file destination, read the saved file back,
use `provider: "local-file"`, and use its absolute path as `receipt_reference`.
`receipt` is `delivered`, `suppressed`, or `unknown`; it is not `status` or
`outcome`. Provider evidence belongs inside `proof`, not alongside `receipt`.
If delivery is uncertain, record `receipt: "unknown"` and do not resend.
If a previous write succeeded but receipt recording failed, recover by reading
the existing provider result and recording the same occurrence. A saved draft or
an unverified send does not establish delivery.
