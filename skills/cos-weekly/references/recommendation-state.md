# Shared CoS recommendation state

Use this protocol in all four CoS skills. Keep safe summaries and source
references, never credentials or raw inbox contents.

## Identity

Each recommendation or offer is one PA note action with a stable ID:
daily `cos:daily:<local date>`, weekly `cos:weekly:<local ISO week>`,
radar `cos:radar:<local ISO week>`, scout `cos:scout:<stable need key>`.
Keep the same ID across retries, replies and outcome updates. Include the
timezone and date or week; never infer the week from UTC alone.

## Record or update

Record with one call. PA merges top-level fields, so an update sends only the
fields that changed (and `history` with the new entry appended):

`pa(operation="action_upsert", data={"action_id":"<stable ID>","action_type":"note","status":"completed","fields":{"title":"CoS: <safe summary>","cos_skill":"<cos-daily|cos-weekly|cos-scout|cos-radar>","offered_at":"<timestamp with offset>","timezone":"<IANA>","summary":"...","evidence":"...","benefit":"...","next_action":"...","review_at":"<timestamp with offset>","stage":"draft","outcome":"unknown"}})`

Add `week`, `disposition`, `follow_up_at`, `wake_id`, `armed`, `usefulness`,
`calendar_readback` or `history` when they apply. `completed` means the note was
written, never that the recommendation was used. Read the note back with
`pa(operation="context", data={"kind":"action","action_id":"<stable ID>"})`
and check the fields you wrote before you deliver or report.

## Retrieval

List notes with `pa(operation="context", data={"kind":"action","limit":20,"offset":0})`,
follow `next_offset` until the period is covered, and read each relevant `cos:`
note by ID. An incomplete list is not proof that no offer exists.

## Outcomes and stages

`outcome` is `used`, `declined`, `ignored` or `unknown`. Record `used` only from
observed execution or the owner's report, `declined` from an explicit no,
`ignored` from an explicit skip, or no owner reply by `review_at` for an offer
known to have reached the owner: a chat reply, or a scheduled report visible in
this chat's history. A scheduled report with only the `unknown` hand-off receipt
and no such evidence stays `unknown`. Record `unknown` when evidence is missing.
`stage` is `draft`, then
`approved` on a yes, `applied` after a completed change is read back, and
`verified` once the promised result is checked. Approval is not use, and use is
not usefulness.

## Scheduled delivery receipts

In a scheduled CoS run, the run's final response IS the owner message. Hermes
delivers it to the job's verified destination. Never use a message tool in a scheduled run.
Use only the job's already claimed `occurrence_id`.

Report: write and read back the note first. Then call
`pa(operation="automations", data={"action":"receipt","occurrence_id":"<claimed occurrence_id>","receipt":"unknown","note":"Final response handed to Hermes cron delivery"})`
and give the report as the final response. `delivered` needs a provider receipt
the run cannot see.

Silence: record `receipt: "suppressed"` with a safe note, and make the final
response exactly `[SILENT]` (nothing else).
Never resend a handled occurrence or invent proof.
Cos-weekly includes radar in its single final response and owns that one receipt.
On-demand chat replies and HB2 wakes do not claim cron occurrences.

## Optional follow-up

Offer a follow-up date, skill and purpose. Only after the owner approves that
specific wake in a human turn in this chat, call the existing `pulse` tool:

```json
{"action":"create","title":"CoS follow-up","note":"Load personal-assistant:cos-scout; read the cos:scout:<stable need key> PA note and check whether the agreed trial helped.","reason":"Owner-approved trial follow-up","trigger":{"kind":"at","at":"<approved timestamp with offset>"},"owner_asked":true}
```

Substitute the actual CoS skill, recommendation ID and approved purpose. Keep
the wake in the same chat. Record returned `wake.id` and `armed` on the same note. Relay any confirmation or hold receipt;
`armed: false` is pending, not scheduled. If unavailable or outside HB2's supported
window/chat, retain `follow_up_at` for cos-weekly; create no replacement scheduler.
Never create another wake from a follow-up turn. On an HB2 wake, use `pulse`
`{"action":"respond","outcome":"done","notify":false,"summary":"No useful change."}`
for silence, or `notify:true` with a safe summary for one useful final reply.
HB2 delivers that final reply; never also use a message tool on the HB2 turn.
