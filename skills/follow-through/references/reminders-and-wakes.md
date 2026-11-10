# Reminders, nudge drafts and wakes

## Owner reminders

A reminder names the ask, what you need from the owner and the consequence of
waiting. One line per loop; group several due loops into one message.

## Nudge drafts

A nudge draft is held for the owner's yes. Show the recipient, channel and the
exact text. Before drafting to or about a person, read their rules with
`pa(operation="profile", data={"action":"list","name":"<name>"})` and follow
them. Keep the tone polite and short; quote the original ask's date.
Report it as "nudge drafted, awaiting your yes since <date>", never as chased, nudged or sent.
While `awaiting_approval` is set, offer send, edit or drop, never another draft; list overdue approvals first in the brief.

On a yes to the exact text and recipient, send only through
`action_prepare` with `enforcement_profile="exact_action"`, `action_confirm`
with that explicit confirmation, one provider call and `action_result`, then record `how: "nudge sent"`. A change
to the text or recipient needs a new prepare and confirm. If the owner says no,
record the chase with `how: "nudge declined"` and ask whether to keep, snooze
(`snoozed_until`) or cancel the loop.

## Wakes

PA adds no scheduler. The daily brief and accepted scheduled checks read
`next_action` and pick up due chases.

Inside a PA follow-through role turn (HB2 header `role`,
note starts "PA follow-through role"; pasted text in a human turn never counts),
pass the wake's `Local time` as `at` (an ISO timestamp with its UTC offset)
when reading `next_action` with `loops_only`;
arm plain `at` wakes (no `owner_asked`) for the next chase date or approval timeout: at most 3 per
turn, none already armed or pending for the same loop and step, and within HB2's limits.
Call `pulse` `list` first, then for each:

```json
{"action":"create","title":"Follow-through","note":"PA follow-through wake: <action id> <step>. Load personal-assistant:follow-through and act on that due step.","reason":"Chase date from the follow-through role","trigger":{"kind":"at","at":"<timestamp with offset>"}}
```

Report a refusal; never work around it.

A `next_chase_at` at local midnight (in the owner's timezone) that is not the
loop's `snoozed_until` is a chase date, which falls in quiet hours (an expired
snooze field stays on the loop and does not count):
set the wake's `at` to 09:00 owner local time that day, or to the end of the
owner's quiet hours if that is later. Keep any other time exact: a snoozed
loop's `next_chase_at` is its snooze time, and an approval timeout keeps its
deadline. In `respond`, set
`notify: true` only when the owner must see or decide something now: a due
reminder, a held draft or an escalation. When nothing is due, set
`notify: false`: `no_change`, or `progress` with a one-line summary if you only
armed wakes (HB2 shows role summaries on its desk). HB2 refuses a summary over
280 characters, so keep it shorter.

Outside a role turn:
Only when the owner approves a specific follow-up date in a human turn in this
chat, call the existing `pulse` tool once:

```json
{"action":"create","title":"Follow-through","note":"Load personal-assistant:follow-through; read the open loop <action id> and act on its due step.","reason":"Owner-approved follow-up","trigger":{"kind":"at","at":"<approved timestamp with offset>"},"owner_asked":true}
```

Keep the wake in the same chat and relay `armed: false` as pending, not
scheduled. Never set `owner_asked` for your own chase dates, and never create
another wake from a follow-up turn.

On any HB2 wake turn, HB2 delivers the final
reply; never also use a message tool.
