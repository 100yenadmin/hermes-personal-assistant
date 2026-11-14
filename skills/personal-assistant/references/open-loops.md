# Open loops

An open loop is anything still waiting on someone: a question you put to the
owner, work the owner delegated, a promise we made, or a reply we are waiting
for. Keep each loop on one existing commitment action. There is no separate
table; `next_action` reads these fields.

After a verified vendor request or any sent message awaiting a reply, pass `follow_through.loop` with the counterparty and our next step in `action_result`, without a separate `action_upsert` loop. This opens the ordinary `waiting_on_them` commitment `<action id>:loop`; report that the reply is now chased. A nudge or any other step on an existing loop never gets its own `follow_through.loop`: record it as a chase on that loop.

## Fields

| Field | Values | Meaning |
|---|---|---|
| `loop_kind` | `ask_owner`, `delegated`, `our_promise`, `waiting_on_them` | What kind of loop this is. |
| `counterparty` | text | Who must answer or act (the owner for `ask_owner`). |
| `next_actor` | `owner`, `us`, `them` | Who moves next. |
| `opened_at` | timestamp with offset | When the loop opened. The chase ladder counts days from here. |
| `next_step` | text | The next concrete step. |
| `chase_at` | timestamp with offset | The owner's own time for the next chase, set only from the owner's words. |
| `last_chased_at` | timestamp with offset | Latest completed ladder step, including a held draft. |
| `chase_log` | list of `{at, step, how}` | Short log of chases; PA keeps the latest 10. |
| `awaiting_approval` | `{step, since, days, overdue}` | Computed `next_action` item field, present only when the last log entry's `how` contains `held` (case-insensitive). |
| `confirmation` | `{by, at, evidence}` | Written only when the other side confirms. |
| `loop_cancelled` | `{by, at}` | The owner withdrew the loop. |

`next_chase_at` is computed by `next_action`; read it there and never set it by
hand. Do not put chase dates in `due_at`: renewals and other recipes use
`due_at` as the decision deadline.

Chase-log `how` values include `reminder`, `nudge draft held`, `nudge sent` and
`nudge declined`. A held draft is not contact: report "nudge drafted, awaiting
your yes since <date>", never as chased, nudged or sent. Record a new `nudge sent`
entry after the owner's yes and the governed send, or `nudge declined` on a no.
In `awaiting_approval`, `step` and `since` are the last entry's step and timestamp;
`days` counts owner-local calendar days and `overdue` is true from 2 days.
Any later entry whose `how` does not contain `held` ends the wait.

## Record an ask to the owner

Whenever you ask the owner a question or for a decision, record it in the same turn.
A Chief of Staff recommendation (`cos:*` note) is the exception: its own review and
the radar already track it, so it gets no loop.

`pa(operation="action_upsert", data={"source_id":"<chat or task>","action_kind":"ask_owner","occurrence":"<short key>","action_type":"commitment","fields":{"title":"<safe summary of the ask>","loop_kind":"ask_owner","counterparty":"owner","next_actor":"owner","opened_at":"<now with offset>","next_step":"<what you do after the answer>"}})`

Use `waiting_on_them` with `next_actor: "them"` for a reply you await from a
third party, `delegated` for work the owner handed to someone else, and
`our_promise` with `next_actor: "us"` for something we promised.

## Close

- A loop closes on the other side's confirmation, or when the owner cancels it. Record confirmation with the same
  action: `fields.confirmation = {"by": "<who confirmed>", "at": "<timestamp>", "evidence": "<safe source: reply, receipt, readback>"}`.
  Non-empty strings `by` and `evidence`, and an ISO timestamp `at`, are required.
- Kanban done is not confirmation. A loop whose Kanban task is done, or whose
  status is completed, stays in `next_action` with `loop_state: "done_unconfirmed"`
  until `confirmation` is written.
- If the owner withdraws the loop, set `status: "cancelled"`. That is not a
  confirmation; say so in the next brief.
- Prepare every provider step for a loop (a nudge, booking, payment or order) as
  its own action, `<loop action id>:<purpose>`, never on the loop's own action.
  If one was prepared on the loop's own action, that row is now a transaction:
  `action_upsert` there accepts only `confirmation`, `loop_cancelled`,
  `last_chased_at`, `chase_log`, `snoozed_until`, `chase_at` and `next_step`. Record the
  owner's withdrawal as `loop_cancelled: {"by": "owner", "at": "<timestamp>"}`.
  A step that is not approval-governed and was never attempted (prepared,
  authorized or paused) can be withdrawn directly; PA then refuses to confirm or
  submit it until it is prepared again. Cancel an approval-governed action with
  `action_cancel` first, and settle an attempt in flight with `action_result`
  first; PA refuses to close the loop before then.

## Chase ladder

`next_action` returns `chase: {step, next_chase_at, age_days, escalated}` for each
loop. Steps fall on owner-local calendar days counted from `opened_at` (the
profile timezone in `pa:preferences`): `day2`, `day5`, `day10`, then `escalate`
from day 11. When several steps are overdue, only the latest one is due.
Recording `last_chased_at` completes every chase step due by that local date,
and a `chase_log` entry completes the step it names. An owner's time before the
loop opens is an extra chase: record step `owner_time`; day 2 stays.
On or after the opening date, a `chase_at` moves the next
chase to the owner's exact time, earlier or later than the ladder; a chase at or
after it completes the steps it replaced. Escalation never comes earlier; when
the owner's time is after it, it comes a day after the owner's chase.
An escalation is recorded as a `chase_log` entry with `step: "escalate"`;
after it, the loop waits for the owner's decision with no further chase.
A future `snoozed_until` holds the ladder. Use
`pa(operation="next_action", data={"loops_only": true})` to read only loops.
