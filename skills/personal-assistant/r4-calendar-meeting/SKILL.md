---
name: personal-assistant:r4-calendar-meeting
description: Find calendar conflicts and prepare appointments or meeting packets.
metadata:
  hermes:
    namespace: personal-assistant
    recipe: R4
    lazy: true
---
# Personal Assistant R4: Calendar and meeting

Load for conflict review, appointment preparation, or a meeting brief.
1. Run `pa.capabilities`; use the profile's own calendar tool (PA holds no Google token), then verify with a read-only calendar call.
2. Accept explicit read scope and use `pa.context` for the selected source or action.
3. `pa.action_upsert` stages one private packet or proposed event; do not use transaction operations for a packet.
4. Write any approved event with the profile's calendar tool after a conflict check, then read the event back. Recurring series writes and attendee sends are outside this candidate.
5. `pa.action_upsert` records event reference, safe proof, conflict, and follow-up.
Expected outcome: a conflict-free proposal or meeting packet with verified readback.

Load `personal-assistant:personal-assistant` for the exact tool argument and state contract. R4 uses calendar conflict/readback guards and ordinary `action_upsert`; `pa.action_result` is reserved for a claimed provider submission and is not used for a meeting packet or calendar event.
