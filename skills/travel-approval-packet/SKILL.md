---
name: travel-approval-packet
description: Use before final travel booking, payment, cancellation, check-in submit, food order, rideshare request, restaurant reservation, outbound message, phone call, detailed/shared calendar write, or material profile/payment change.
metadata:
  openclaw:
    skillKey: travel-approval-packet
  hermes:
    category: travel
    tags: ["travel", "confirmation", "payment", "audit", "final-state"]
---

# Travel Final Confirmation Summary

Every `references/...` path in this skill is relative to this skill directory.

Create a short final-state confirmation summary at the final button before any paid or irreversible travel action. The legacy skill key remains `travel-approval-packet` for compatibility, but the behavior is a practical double-check, not a blocking runtime plugin.

## Read

- `references/approval-packet-fields.md` for field names.
- `references/standing-orders.md` for final confirmation rules.
- `references/final-state-double-check.md` for user-facing shape and live re-check rules.
- `references/scoring-rubric.md` when reviewing skill quality.

## Required Content

Every final-state summary must include:

- Provider and merchant.
- Exact final action label visible to the agent.
- Total amount and currency.
- Traveler name.
- Dates, route, hotel, or reservation details.
- Refund/cancellation terms or "unclear refund policy".
- Payment descriptor and any user-confirmed limit when using an already configured payment method.
- Account or credential reference descriptor if using a saved session, passkey, browser profile, or credential lane; do not print the credential value.
- Recipient, message preview, calendar visibility, changed profile fields, or data shared for non-monetary actions.
- Risk flags.
- Evidence checked before asking.

## Final Confirmation Request

Use this shape:

```text
I found it and filled it out. I'm at the final button.
Provider: Trip.com
Merchant: Example Air
Action: click "Book and pay"
Traveler: Jane Doe
Total: USD 312.40
Details: SFO -> JFK, Jun 12, 8:10 AM, 1 checked bag
Refund: nonrefundable
Payment: saved Visa ending 4242
Risk flags: outside-confirmed-limit, saved-payment-method, nonrefundable
Confirm and I'll place it.
```

## Record

Before asking, record the summary on the errand's action with `pa(operation="action_prepare")`, following the `personal-assistant` transaction contract:

- When the final step is one exact provider tool call, prepare it governed (`enforcement_profile="exact_action"` with the full scope). After a yes, `action_confirm`, then call that tool; never claim a governed action manually.
- When the final step is a website control, use the legacy prepare: `data={"action_id": ..., "summary": {"provider", "final_action", ...the fields above}}`. After a yes, `action_confirm` and `action_claim` with the same summary right before the one click (in a Browserbase session, the user's tap in the live view).

Either way the packet is stored with its material summary; read it back with `context`. A change or cancellation of an existing booking gets its own packet under a new action_id such as `<booking action_id>-cancel`, because a completed booking cannot be prepared again; put the original booking's action_id in the material summary as `booking_action_id`, so the packet names the booking it changes. Do not record a packet as a completed note, and do not confirm before the user says yes.

## After Confirmation

Before acting, compare the live page against the summary. If amount, dates, traveler, refund terms, payment method, provider, merchant, or final action changed, refresh the summary and ask again. If it still matches, submit/send/request immediately and verify provider-visible proof. In a Browserbase session the final pay/book/reserve tap is the user's, in the live view: send the link instead of clicking, wait, then verify.

## Denial Or Timeout

If the user denies, times out, or asks to change details, keep the provider state prepared when possible. Report what remains ready and the next executable path.
