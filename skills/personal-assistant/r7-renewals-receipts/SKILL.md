---
name: personal-assistant:r7-renewals-receipts
description: Reconcile household renewals and receipts, then prepare a confirmed decision.
metadata:
  hermes:
    namespace: personal-assistant
    recipe: R7
    lazy: true
---
# Personal Assistant R7: Renewals and receipts

Load for a household subscription, renewal date, receipt, or service decision.
1. `pa.context` retrieves the receipt source and action; `pa.next_action` finds one open commitment.
2. `pa.action_upsert` reconciles renewal dates, cancellation notice periods, currency, amount and terms against the supplied notices. Derive the decision deadline and store it in `fields.due_at`, the existing field used by next-action ordering and due checks. Keep date-only evidence as an ISO date; do not invent a cutoff time or timezone. Retain the policy/source alongside it and verify that `pa.next_action` returns this `due_at` for the pending commitment. Flag conflicting notices rather than picking a price. Put one decision commitment on Kanban and link its stable action ID in both directions. Reconciliation needs no transaction state.
3. For renewal, cancellation, or provider message, call `pa.action_prepare` with `enforcement_profile: "exact_action"`, the complete provider tool arguments and semantic target, revisions, freshness, one-call budget, preconditions, and expected readback. Show exact terms, confirm with `pa.action_confirm`, and recheck. Invoke the exact provider tool directly; the native gateway atomically claims the one matching submission. Use `pa.action_cancel` if the user withdraws approval before dispatch.
4. Read provider state and call `pa.action_result`; do not repeat unknown submits.
5. Keep source proof, decision deadline and waiting-for state in the ordinary action. When the owner decides, complete the decision task and record the decision. A decision to retain a subscription is not evidence that a payment was made; a later provider step is a separate action only when needed.
Expected outcome: a sourced decision note, one actionable commitment, and a recorded decision or verified provider outcome.

Load `personal-assistant:personal-assistant` for the exact tool argument and state contract. For non-transaction work, `pa.action_upsert` records preparation and verified evidence; `pa.action_result` is only for a provider submission already claimed by the native gateway.
