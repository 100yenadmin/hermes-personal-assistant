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
   To turn on a routine the owner asked for (see "Turning on a routine" below).
5. `pa.action_upsert` records brief, source gap, and follow-up; scheduled notification receipts use the contract below.
Expected outcome: a current brief or reminder receipt without duplicate notification.

## What every brief contains

Every daily brief lists what is still open in PA's own ledger, whatever the
calendar and inbox sources say. Read `pa next_action` with `loops_only: true`
and list each open loop in one line: who owes what, how old it is, and the chase
step due, for example "Cedar hasn't confirmed the tasting menu (2 days); day-2
nudge due." Say a nudge is drafted only when `next_action` shows one in progress.
Then list the remaining (non-loop) candidates from `pa next_action` as due items.
If the daily-ops collector or a source cannot be read, say so in one line
("Calendar and inbox were not read: not connected yet") and still send the open
loops and due items. Never send a brief that only reports a source gap while open
loops exist. Record a suppressed receipt and reply `[SILENT]` only when there are
no open loops, no due items and nothing useful from the sources.

Load `personal-assistant:personal-assistant` for the exact tool argument and state contract. R5 has no provider transaction, so do not use `pa.action_prepare`, `pa.action_confirm`, `pa.action_claim`, or `pa.action_result` for a brief or reminder.

## Turning on a routine

When the owner asks for the morning brief (or the due check), set it up from the
chat that should receive it. If this surface cannot receive pushed messages (the
CLI or Desktop), ask the owner to continue in that chat; never guess a chat ID.

1. Save their clock: `{"operation":"automations","data":{"action":"preferences","changes":{"timezone":"<IANA zone>","brief_time":"HH:MM"}}}`.
2. Record their acceptance: `{"operation":"automations","data":{"action":"rule","rule_id":"daily_brief","rule":{"kind":"daily_brief","accepted":true,"destination":"origin","destination_verified":true,"timezone":"<IANA zone>"}}}`.
   For the due check use `"rule_id":"due_source_check"` and `"kind":"due_source_check"`
   instead; each routine keeps its own rule.
   `"origin"` is the chat, including a Telegram topic, where `/suggestions accept`
   runs. `destination_verified: true` records the owner's explicit yes in that chat.
3. Offer the native job: `{"operation":"automations","data":{"action":"suggest","native":true}}`.
   Give the owner the returned `accept_command` (Hermes's `/suggestions accept <id>`)
   to send in that chat. When no command comes back (the job exists, was accepted,
   dismissed, or the backlog is full), follow the returned `next_step`. The owner's
   acceptance creates the job; PA never creates jobs itself.

## Scheduled notification receipt

The native precheck supplies an already claimed `occurrence_id`. Use that exact
identity; never create another claim or resend to repair a missing receipt.
In a scheduled context, record `unknown` before returning the final response:

```json
{"operation":"automations","data":{"action":"receipt","occurrence_id":"<precheck occurrence_id>","receipt":"unknown","note":"Final response handed to Hermes cron delivery"}}
```

Hermes cron delivers the final response; never use a message tool or record
`delivered` for that hand-off. If nothing is useful, record `suppressed` and reply
exactly `[SILENT]`. An uncertain outcome is never a reason to resend. A later
verified provider receipt can resolve `unknown` through the receipt operation.

## End of day and health exceptions

Read `../references/reporting.md` for reporting, one corrected tool_call retry,
progress notes, escalation and pre-send checks. For `routine_health`, report the
precheck's findings immediately in the scheduled final response; never repair jobs.
The `end_of_day` slot (default `eod_time` 18:00) runs only when it falls after `brief_time`;
an evening brief replaces it. For `end_of_day`, skip the gog morning collector. Read `pa evidence action=list`,
`pa next_action`, and `pa automations action=health`. Page relevant evidence using
focused context; missing evidence stays unknown. Write the owner's note with all
three sections: **Done / In progress / Blocked with questions**. Every blocked
item ends in a question; nothing is invented. Save a `pa:eod:<local date>` note
with `occurrence_id`, `sections` (those exact three keys, each a list), and `evidence_refs`
before recording the scheduled receipt as `unknown`.
The evening run lists `meetings_to_confirm` for tomorrow's R4 24h confirmation
and brief. Preserve `attendees_known: false` and `attendees_omitted` as gaps;
never infer all attendees were checked. Point the brief to the twice-daily R6
inbox triage digest; do not duplicate or invent inbox results.

The follow-through `escalate` step surfaces through the daily brief or radar;
there is no separate wake for escalation. Preserve the canonical loop guidance
and bring its decision question into the next report.
