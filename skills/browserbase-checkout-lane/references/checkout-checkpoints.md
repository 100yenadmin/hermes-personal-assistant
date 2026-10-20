# Checkout Checkpoints

Use checkpoints so browser timeouts, provider 401s, reconnects, or fallback browser lanes do not force the agent to redo work.

## Record After Each Meaningful Step

- Provider, store, route, venue, airline, hotel, or reservation platform.
- Browserbase `bb_session_id` when available, never connection or live view URLs.
- Browser lane and current URL.
- Login state: before login, after login, verification step, address step, payment step, final button, submitted, or blocked on a required field.
- Cart, booking, ride, check-in, or reservation state.
- Address, pickup/dropoff, traveler, party size, delivery window, dates, or times.
- Current total and visible fees.
- Payment descriptor and wallet/funds readiness.
- Required fields still missing.
- Last user intent and final-state confirmation status.

## Reattach Before Redo

On timeout, disconnect, or provider reset:

1. Reattach to the existing Browserbase session.
2. If expired, create a new 20-minute Browserbase session and restore from this checkpoint.
3. Restore from the checkpoint and verify the provider state.
4. Only then try another configured attended browser while preserving the same checkpoint.

Do not ask the user to rebuild the cart/order/booking manually while a configured lane and checkpoint can continue.

## Timeout Defaults

- Quick login/check: 5-10 minutes.
- Normal checkout: 20-minute Browserbase lease.
- Grocery or multi-item shopping: repeated 20-minute leases with checkpoints.
- Page open wait: 120 seconds.
- Provider progress loop: 60-second wait/snapshot/action cycles.

Longer work should renew the lease, not open a six-hour unattended browser.
