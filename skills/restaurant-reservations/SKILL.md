---
name: restaurant-reservations
description: Use to find restaurants and submit reservations after final confirmation, including party size, time, venue policy, deposits, no-show fees, special requests, messages, or calls.
metadata:
  openclaw:
    skillKey: restaurant-reservations
  hermes:
    category: travel
    tags: ["travel", "restaurants", "reservations", "dining", "confirmation"]
---

# Restaurant Reservations

Every `references/...` path in this skill is relative to this skill directory.

Find dining options, prepare a reservation, and ask before final reservation submit.

## Read

- `references/ground-food-playbook.md` for reservation steps.
- `references/standing-orders.md` for final confirmation rules.
- `references/browser-auth.md` before using logged-in reservation accounts.
- `references/japan-korea.md` for trips in Japan or Korea (local providers and which need the user's app, login or phone).
- `travel-ledger` for reservation actions, deposits/no-show fee readiness, Browserbase checkpoints, and confirmation proof.

Use `phone-calls` when a phone call is needed.

## Workflow

1. Identify location, date/time, party size, cuisine, budget, accessibility, and calendar constraints.
2. Search reservation platforms, restaurant sites, maps, and local guides.
3. Compare at least three options when practical.
   Quote a price, price range, fee or deposit only as a page or tool result you saw shows it for that restaurant (a cart or checkout counts), with its currency and basis such as per person. Report a symbol tier such as $$$ as a tier, never as an amount; call a missing amount unknown.
4. Prepare the selected reservation with party size, seating, special requests, and contact details.
5. Use saved reservation credentials, Browserbase, persistent browser profile, and Live Browser fallback to work through login/CAPTCHA/provider friction.
6. Verify venue, address, date/time, cancellation/no-show fee, deposit, payment descriptor, account descriptor, message preview, call need, and final button.
7. Build a final confirmation summary with kind `reservation`, risk flag `final-reservation-submit`, plus no-show fee, saved payment, saved credential, outbound-message, or phone-call flags as relevant. Update `travel-ledger` to `awaiting-final-confirmation`.
8. After confirmation, re-check details and submit immediately only if they match.
9. Verify reservation id, confirmation email, or provider-visible status. Record proof/status in `travel-ledger` before reporting.

Whenever you stop before step 8 (at the reservation form because the user said not to book yet, a login, the user's app, no availability or a blocked site), save a checkpoint (`personal-assistant`, Checkpoints) before replying, with every field: `provider`, `url` (the stopping page), `state` (what is prepared: venue, date/time, party size, seating), `total` (deposit or fee, or unknown), `missing` and `next`. A later yes, even in a new chat, resumes from it.

## Changes and cancellations

Find the existing booking in `travel-ledger`, its confirmation email or the provider page; verify the venue, date and booking identity before preparing a change or cancellation.
Show the old and proposed details, fee, refund or penalty, and the deadline with its time zone in the approval packet. Stop for an explicit yes before the final change or cancel control, including free cancellations.
Never cancel in order to rebook without approval. If the change needs the user's login or app, preserve the preparation and give exact steps to the review screen and final control. Read back the result before updating the ledger or reporting completion.

## Must Not

- Do not call, message, deposit, or accept a no-show fee without final-state confirmation.
- Do not send special requests that reveal sensitive information unless the user asked for them.
