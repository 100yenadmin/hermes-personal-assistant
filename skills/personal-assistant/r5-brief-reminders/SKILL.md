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

Load `personal-assistant:personal-assistant` for the exact tool argument and state contract. R5 has no provider transaction, so do not use `pa.action_prepare`, `pa.action_confirm`, `pa.action_claim`, or `pa.action_result` for a brief or reminder.

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
For `end_of_day`, skip the gog morning collector. Read `pa evidence action=list`,
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
