# Final State Double-Check

Use this reference at the natural final button for any paid or irreversible travel action. This is not a blocking runtime plugin. It is the agent's last live provider read before asking one concise confirmation.

## Required Fields

- Provider and merchant.
- Exact visible final action label.
- Total amount, currency, taxes, fees, tip, deposit, or no-show charge when present.
- Address, route, dates, times, traveler, party size, delivery window, or pickup/dropoff.
- Payment descriptor and any user-confirmed limit when using an already configured payment method.
- Refund, cancellation, no-show, delivery, baggage, incidentals, or check-in terms.
- Account/session descriptor when using saved credentials, Browserbase Context, browser profile, passkey, or provider account.
- Evidence checked immediately before asking.

## User-Facing Shape

```text
I found it and filled it out. I'm at the final button.
Provider: Instacart / Food Lion
Action: click "Place order"
Total: USD 14.35
Delivery: the confirmed delivery address on file
Payment: configured card descriptor
Terms: delivery fees and tip included, cancelable until shopper starts
Confirm and I'll place it.
```

## After The User Confirms

Re-read the live page. If the amount, merchant, address, route, dates, traveler, payment descriptor, refund/no-show policy, delivery window, or final action label changed, refresh the summary and ask once again. If it matches, submit immediately and verify provider-visible proof. In a Browserbase session the final pay/book/reserve tap is the user's, in the live view: send the link instead of clicking, wait, then verify.

## Tone

Do not say the agent cannot execute when the workflow is merely at login, verification, address, payment selection, or another provider step. Say where the workflow is and what lane is continuing.
