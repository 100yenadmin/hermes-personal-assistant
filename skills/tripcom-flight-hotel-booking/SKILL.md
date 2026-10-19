---
name: tripcom-flight-hotel-booking
description: Use when finding, comparing, preparing, or booking flights and hotels through Trip.com or direct airline/hotel fallback with final-state confirmations.
metadata:
  openclaw:
    skillKey: tripcom-flight-hotel-booking
  hermes:
    category: travel
    tags: ["travel", "trip.com", "flights", "hotels", "booking"]
---

# Trip.com Flight And Hotel Booking

Every `references/...` path in this skill is relative to this skill directory.

Use Trip.com as the default user-friendly aggregator when the user asks to find or book flights/hotels and does not name a different provider.

## Preparation

Read `references/browser-workflows.md`, `references/tripcom-playbook.md`, and `references/checkout-checkpoints.md` before using a browser. Use `travel-mode` standing orders for authority and final confirmations. Use `travel-ledger` for trip records, booking actions, Browserbase checkpoints, payment readiness, and confirmation proof.

- Read `references/japan-korea.md` for trips in Japan or Korea (local providers and which need the user's app, login or phone).

Collect or infer:

- Origin, destination, dates, traveler count, cabin or hotel class, bags, budget, preferred times, stop limits, loyalty preferences.
- Hotel area, room count, bed type, cancellation preference, accessibility needs, and arrival time.
- Whether the user already gave a spend cap such as "book it if under USD 300". Treat spend caps as delegated authority to choose, fill, and reach the final button; still ask the compact final confirmation before paid submit.

## Hotel constraints

- A named area (Shinjuku, Myeongdong) is a hard constraint unless the user said nearby is fine: check the property's address on its details page. Among the results within budget, prepare one inside the area; go outside it only when none inside fits, and name the closer ones you passed over.
- "Hotel" means a hotel. Ask once before offering an apartment, hostel, capsule or shared room, unless the user already accepted one.
- A per-night cap applies to every night. Read the per-night breakdown on the room or review page; if the site shows only an average, say so and do not claim the cap is met. Check the cap against the all-in nightly price, mandatory taxes and fees included; if those are not shown, the cap is unverified.

## Agentic Search Behavior

Do without asking when safe:

- Search Trip.com.
- Filter and sort results.
- Compare at least three reasonable options when available.
- Open fare or room details.
- Check taxes, baggage, resort fees, and cancellation terms.
- Fill reversible preference fields such as cabin filter, hotel class, seat preference, bag count, refundable-room filter, or loyalty preference display.
- Save/use user-provided Trip.com credentials, saved sessions, browser profile state, traveler/profile fields, and payment descriptors needed to reach the final booking button.
- Use the configured browser route for checkout and CAPTCHA friction, with another attended browser fallback when it cannot complete the provider step.

## Final-State Confirmation

Use `travel-approval-packet` before:

- Clicking final booking, pay, reserve, cancel, or send buttons.
- Booking over USD 100.
- Accepting nonrefundable or unclear refund terms.
- Changing passenger, passport, contact, loyalty, or billing profile fields.
- Filling new, missing, or changed legal identity, passport, DOB, contact, loyalty number, billing, known-traveler, redress, accessibility, or emergency-contact fields.
- Sending messages to providers or calling providers.

## Direct Fallback

Use direct airline or hotel websites when Trip.com is missing the requested option, materially worse on price or terms, blocked, ambiguous, or inconsistent with the user's constraints.

## Changes and cancellations

Find the existing booking in `travel-ledger`, its confirmation email or the provider page; use the original seller's manage-booking route and verify passenger/property, dates and booking identity.
Prepare the change or cancellation, then show old versus proposed details, fare/room difference, fees, refund amount or penalty, refund method and deadline with its time zone. Mark unclear terms as unknown and resolve them before submission.
Stop for an explicit yes before the final change or cancel control, including free cancellations. Never cancel in order to rebook without approval. If the user's login or app is required, preserve the preparation and give exact steps to the review screen and final control. Verify the result before updating the ledger or reporting completion.

## Final Report

After action, report:

- Provider and confirmation id.
- Route or hotel details.
- Total amount and currency.
- Refund/cancellation terms.
- Calendar/email updates made or still pending.
- Evidence used to verify completion.

Record every flight or hotel step in `travel-ledger` before replying, including a search that found no match, a CAPTCHA or login wall, and a stop before guest details: a `note` action through the `pa` call (`operation="action_upsert"`, `action_type="note"`) with the URL, state, the fares or rooms you saw, what is missing and the next step, and no secrets. These step notes are separate from the final approval packet, which `travel-approval-packet` prepares with `action_prepare`; never update a transaction through `action_upsert`. Describe the state as prepared/draft, awaiting final confirmation, booked and verified, blocked with next executable path, or abandoned with cleanup proof.

Name airlines, hotels and flights exactly as the page shows them; do not translate or guess a carrier name from its code.

Report each flight time or fare only when a page or tool result you saw (a results list, cart or checkout) shows it for that flight and travel date, or when the user gave it (say it came from them). Report what you saw even when other details are missing, and call the missing ones unknown; your own ledger note alone does not show that you saw a detail.
