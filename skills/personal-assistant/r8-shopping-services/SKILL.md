---
name: personal-assistant:r8-shopping-services
description: Research and prepare shopping or service requests with exact confirmation.
metadata:
  hermes:
    namespace: personal-assistant
    recipe: R8
    lazy: true
---
# Personal Assistant R8: Shopping and services

Load for a shopping cart, delivery, appointment, or service request.
1. Recover ordinary preferences from native memory and use `pa.context` for the selected source/action; do not create a preferences store.
2. Compare eligible options against constraints, availability, total cost including fees/shipping/tax, timing and return/cancellation terms. Keep unknown charges explicit. Research and comparison work without a funded wallet. Prepare the chosen cart or request through existing tools and record safe facts with `pa.action_upsert`.
3. For submission, discover the provider's existing authorized payment/session capability; report readiness as ready, missing, unknown or blocked with verification time. Never invent balances or require a new wallet. Call `pa.action_prepare` with `enforcement_profile: "exact_action"`, the complete provider tool arguments and semantic target, revisions, freshness, one-call budget, preconditions, and expected readback. Show the exact provider, items/service, total, time and terms, confirm with `pa.action_confirm`, and recheck. Invoke the exact provider tool directly; the native gateway atomically claims the one matching submission. Use `pa.action_cancel` if the user withdraws approval before dispatch. Material changes require renewed confirmation.
4. Read provider state and call `pa.action_result`; preserve unknown submit and never replay it.
5. Record separate research, receipt, blocker, and follow-up facts with `pa.action_upsert`.
Expected outcome: a prepared cart or verified order or service receipt with exact scope.

Load `personal-assistant:personal-assistant` for the exact tool argument and state contract. For non-transaction work, `pa.action_upsert` records preparation and verified evidence; `pa.action_result` is only for a provider submission already claimed by the native gateway.
