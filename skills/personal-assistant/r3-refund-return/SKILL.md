---
name: personal-assistant:r3-refund-return
description: Prepare and confirm a refund or return request with provider proof.
metadata:
  hermes:
    namespace: personal-assistant
    recipe: R3
    lazy: true
---
# Personal Assistant R3: Refund or return

Load for a refund, return, exchange, or provider policy request.
1. `pa.context` retrieves the purchase source and existing action. Read the supplied policy; derive the deadline from its starting date, timezone and calendar/business-day rule. Preserve uncertain eligibility or contradictory policies.
2. `pa.action_upsert` records the policy source, deadline, amount, return method and next step. Keep one follow-up record with `action_type="return"` or `"refund"` and its native task ID in `fields.kanban_task_id`. Reuse that record and task throughout the return/refund; do not store outstanding work as a note or create another tracking task after submission. Research needs no transaction state. Call `pa.action_prepare` only for an exact request to submit, with `enforcement_profile: "exact_action"`, the complete provider tool arguments and semantic target, revisions, freshness, one-call budget, preconditions, and expected readback.
3. Require exact confirmation, `pa.action_confirm`, and a material recheck. Invoke the exact provider tool directly; the native gateway atomically claims the one matching request. Use `pa.action_cancel` if the user withdraws approval before dispatch.
4. Read provider state, then call `pa.action_result`; preserve unknown state without replay.
5. Update the same follow-up action (separate from the transaction attempt) with the expected response, shipping step or settlement deadline. An accepted request is not a received refund. Refund settlement proves payment only: preserve shipping and physical-return status as unknown unless separate evidence confirms them or the provider explicitly waives return. Never infer `return_completed` from `refunded`. Keep any unverified return obligation visible with a next step to check the provider's instructions; complete the Kanban commitment only when the recorded outcome resolves what is owed or the owner explicitly stops it. Verify `pa.next_action`: unresolved work must remain discoverable, and a completed linked task must no longer appear.
Expected outcome: a sourced deadline, prepared request and tracked outstanding outcome; provider request and refund settlement are distinct evidence.

Load `personal-assistant:personal-assistant` for the exact tool argument and state contract. For non-transaction work, `pa.action_upsert` records preparation and verified evidence; `pa.action_result` is only for a provider submission already claimed by the native gateway.
