# Reminders, nudge drafts and wakes

## Owner reminders

A reminder names the ask, what you need from the owner and the consequence of
waiting. One line per loop; group several due loops into one message.

## Nudge drafts

A nudge draft is held for the owner's yes. Show the recipient, channel and the
exact text. Before drafting to or about a person, read their rules with
`pa(operation="profile", data={"action":"list","name":"<name>"})` and follow
them. Keep the tone polite and short; quote the original ask's date.

On a yes to the exact text and recipient, send only through
`action_prepare` with `enforcement_profile="exact_action"`, `action_confirm`
with that explicit confirmation, one provider call and `action_result`. A change
to the text or recipient needs a new prepare and confirm. If the owner says no,
record the chase with `how: "nudge declined"` and ask whether to keep, snooze
(`snoozed_until`) or cancel the loop.

## Wakes

PA adds no scheduler. The daily brief and accepted scheduled checks read
`next_action` and pick up due chases.

Inside a PA follow-through role turn (an HB2 role wake whose note starts
"PA follow-through role"), arm plain `at` wakes (no `owner_asked`) for the next
chase date or approval timeout: at most 3 per turn, none already armed for the
same loop and step, and within HB2's limits. Report a refusal; never work around it.

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
