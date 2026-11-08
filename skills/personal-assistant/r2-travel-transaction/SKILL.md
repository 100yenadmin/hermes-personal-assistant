---
name: personal-assistant:r2-travel-transaction
description: Prepare booking, check-in, ground, or reservation work with safe submit recovery.
metadata:
  hermes:
    namespace: personal-assistant
    recipe: R2
    lazy: true
---
# Personal Assistant R2: Travel transaction

Load for booking, airline or hotel check-in, ground request, or reservation.
Provider skills own browser details; `pa` owns action state and confirmation.
1. `pa.context` captures the selected trip, source and action; `pa.next_action` selects one open commitment.
2. Use `pa.action_upsert` for research. When ready to submit, call `pa.action_prepare` with `enforcement_profile: "exact_action"`, the complete material summary, exact provider tool and arguments, semantic target, revisions, freshness, one-call budget, preconditions, and expected readback.
3. Require exact confirmation, call `pa.action_confirm` with the same summary, and recheck it. Invoke the exact provider tool directly; the native gateway atomically claims the one matching call. Do not claim it manually. Use `pa.action_cancel` if the user withdraws approval before dispatch.
4. Read provider state and call `pa.action_result` with confirmed, failed, or unknown plus safe proof when known.
   With a confirmed readback, pass `follow_through` with its own item values and reminders such as leave-by, check-in or the cancellation deadline. Never add a fact the readback does not show. Reminders are your own timing: set leave-by from the readback's start minus the known travel time, or assume 60 minutes and say so.
   Include `follow_through.expense` when the readback states the total charged or due.
   Do the returned `next_step`. Report exactly what is on the itinerary, which reminders are set, and whether the booking is on the calendar or only in the ICS file.
5. Never change a transaction through `action_upsert`; after timeout or restart, read provider state and never replay an unknown submit.
Expected outcome: a prepared or verified travel action. Provider reference links
are resolved relative to the selected provider skill directory.

Load `personal-assistant:personal-assistant` for the exact tool argument and state contract. For non-transaction work, `pa.action_upsert` records preparation and verified evidence; `pa.action_result` is only for a provider submission already claimed by the native gateway.
