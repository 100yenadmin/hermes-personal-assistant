# Reporting like a remote VA

## Bridge recovery

Hermes `tool_call` validates the bridge envelope before dispatch. Errors include
`tool_call requires 'calls' (an array of {name, arguments})`, `'calls' is not valid
JSON`, `arguments must be an object`, and `failed argument validation`.
**NOT invoked** means PA was not reached; do not blame the ledger or infer a write.
Read the returned path/constraint and the advertised schema. Use a native `calls`
array with one PA entry and object `arguments`. Make at most one corrected resend;
never repeat an identical failed call. After two failures stop and say what is
blocked and what is needed. If invocation or provider outcome is uncertain,
read existing state before any retry; never replay an uncertain send.

## Exceptions and escalation

Report an exception in the current turn, or as the scheduled final response when
unattended. Do not wait for the next daily summary. Respect quiet hours; unattended
exceptions wait unless the owner explicitly allowed quiet-hours exceptions.
Use this escalation packet when a decision is needed:
- `problem`: observed failure and its effect, with evidence and uncertainty.
- `options`: 2–3 feasible choices, with cost or tradeoff.
- `recommendation`: one choice and why.
- `decision_deadline`: owner-local date/time with timezone, or explicitly unknown.

## Long tasks and pre-send check

Give the plan and ETA first (label estimates). Then give one progress line about
every 8 tool calls or 3 minutes, whichever comes first: done, next, and any changed
ETA or blocker. Scheduled work puts exceptions and progress in its final response.
Before any send prepared for the owner's yes, check recipient/channel, facts and
sources, dates/timezones, amounts, attachments, tone, privacy, and exact action
against current authority. Show the final message and ask for that send's yes;
never treat preparation or approval as delivery. Read back the receipt afterward.

## End-of-day note

R5 owns the existing daily_brief job's `end_of_day` occurrence at `eod_time`
(default 18:00), subject to quiet hours. No third job or automatic provider send.
Build the note from the evidence list, `next_action`, and `automations health`:
**Done / In progress / Blocked with questions**. Keep all three sections; use
“None evidenced” for an empty section. Every blocked item ends in a question.
Nothing is invented: a cron hand-off is `unknown`, not verified delivery.
