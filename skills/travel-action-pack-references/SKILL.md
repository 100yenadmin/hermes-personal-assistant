---
name: travel-action-pack-references
description: Use when an agent needs the Travel Agent Skills v0.1 customer-pilot operating model, rollout status, package assumptions, support matrix, or customer-facing explanation of travel skills.
metadata:
  openclaw:
    skillKey: travel-action-pack-references
  hermes:
    category: travel
    tags: ["travel", "references", "support", "rollout", "v0.1"]
---

# Travel Agent Skills References

This is the v0.1 customer-pilot reference surface for Travel Agent Skills.

## Operating Model

- The agent acts first on delegated travel work: research, compare, log in, fill forms, stage carts/bookings/messages, and reach final pages.
- The agent stops for one compact final-state confirmation before paid or irreversible actions.
- The agent records durable state with `travel-ledger`: trips, provider actions, Browserbase checkpoints, payment readiness, and proof.
- Browserbase is the first checkout/friction lane; persistent browser profile and Live Browser are fallbacks.
- Payment readiness uses any already configured payment method; no wallet vendor is required.

## Pilot Status

This pack is available only for enrolled pilot customers. Do not describe it as broad-customer ready until the customer-pilot canary matrix passes:

- upcoming trip capture
- provider-message/refund proof
- Browserbase timeout/reattach proof
- payment readiness proof
- food delivery final-summary proof
- hotel/flight final-page or draft proof

## User-Facing Summary

```text
Your travel agent can help manage trips end to end: capture your itinerary, find flights and hotels, prepare food delivery and rides, check weather, draft calendar entries, handle provider messages or refund requests, and work through browser checkout. The agent will do the work up to the final button, show the exact amount/address/route/provider/action, ask for confirmation, then submit and verify proof.
```

## Follow-On Skills

Use the specific action skill for the actual workflow:

- `travel-mode`
- `itinerary-intake`
- `travel-action-orchestrator`
- `travel-ledger`
- `browserbase-checkout-lane`
- `agent-wallet-payments` only when the user explicitly selected that optional integration
- `provider-message-refund`
- `tripcom-flight-hotel-booking`
- `food-delivery-to-hotel`
- `rideshare-booking`
- `restaurant-reservations`
- `airline-check-in`
- `hotel-check-in`
- `travel-email-calendar`
- `weather-trip-briefing`
