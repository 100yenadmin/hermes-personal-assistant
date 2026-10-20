# Orchestration Playbook

Parse the trip, ask only blocking questions, dispatch research lanes, merge evidence, prepare provider flows, ask for confirmation, execute, verify, and report.

One agent owns the action and verification. Use a separate research lane only when explicitly authorized and independently useful; it never owns a paid or irreversible final submit.

## Action Order

1. Intake: parse itinerary, destination, dates, budget, traveler, destination address, and requested outcomes.
2. Readiness: verify provider login lane, Browserbase readiness (`remote_browser`), payment descriptor/funds, phone/contact, and any provider-specific required fields before building a cart.
3. Work: research options, pick the in-budget/default choice, fill forms, preserve session checkpoints, and reach final submit.
4. Confirm: show one compact final packet with provider, amount, address/route/dates, payment descriptor, cancellation/refund flags, and exact final action.
5. Submit: after same-conversation confirmation, re-check live state; if any amount/address/route/date/provider/payment field changed, ask for one fresh confirmation.
6. Verify: capture receipt/order id/status or report the exact required field that prevented completion.

## Failure Posture

Do not say the user must redo the whole task while a checkpoint or browser session can be recovered. Say what lane is being used next: "I am reattaching to the Browserbase session", "I am restoring from the provider Context", or "I am moving the same checkpoint into the VM browser fallback."

If payment or wallet readiness is missing, stop early and name that as the setup blocker. If a provider adds a late required field, continue from the same checkpoint after the field is supplied.
