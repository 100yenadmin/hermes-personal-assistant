---
name: rideshare-booking
description: Use to prepare and request Uber, Lyft, taxi, or rideshare trips after final confirmation, including pickup/dropoff, fare estimate, pickup zone, luggage, surge, and payment descriptor.
metadata:
  openclaw:
    skillKey: rideshare-booking
  hermes:
    category: travel
    tags: ["travel", "rideshare", "uber", "ground-transport", "confirmation"]
---

# Rideshare Booking

Every `references/...` path in this skill is relative to this skill directory.

Prepare ground transportation and ask before the final ride request.

## Read

- `references/ground-food-playbook.md` for rideshare steps.
- `references/standing-orders.md` for final confirmation rules.
- `references/browser-auth.md` for account and browser handling.
- `references/japan-korea.md` for trips in Japan or Korea (local providers and which need the user's app, login or phone).
- `travel-ledger` for ride action records, fare/payment readiness, pickup/dropoff proof, and request status.

## Workflow

1. Determine pickup, dropoff, local time, passenger count, luggage, accessibility needs, and timing target.
2. Use flight/hotel/calendar facts to choose pickup zones, terminals, hotel entrances, or meeting addresses.
3. Open or log into the connected rideshare account using saved credentials, Browserbase, persistent browser profile, app lane, or Live Browser fallback.
4. Compare reasonable ride classes when available.
5. Verify fare estimate, surge, pickup pin, dropoff, ETA, payment descriptor, cancellation/no-show terms, and final button.
6. Build a final confirmation summary with kind `rideshare`, risk flags `final-ride-request` and `pickup-location`, plus a configured-payment flag when relevant. Update the `travel-ledger` action to `awaiting-final-confirmation`.
7. After confirmation, re-check fare and pickup zone. If fare materially changes, ask again; otherwise request the ride immediately.
8. Verify ride requested, driver status, pickup point, and ETA. Record the provider-visible ride status/proof in `travel-ledger` before reporting.

If you stop earlier, at a login, the user's app, no availability or a blocked site, record that stop in `travel-ledger` before replying: the stopping URL, what is prepared, what is missing and the next step.

## Must Not

- Do not request a ride before the final-state confirmation.
- Do not change account, phone, payment, safety, or profile settings without a final-state confirmation.
- Do not share sensitive location history beyond the active trip need.
