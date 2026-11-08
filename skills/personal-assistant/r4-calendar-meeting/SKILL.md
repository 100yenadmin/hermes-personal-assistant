---
name: personal-assistant:r4-calendar-meeting
description: Find calendar conflicts, book events with buffers, send invites after a yes, find a time across zones, and confirm tomorrow's meetings.
metadata:
  hermes:
    namespace: personal-assistant
    recipe: R4
    lazy: true
---
# Personal Assistant R4: Calendar and meeting

Load for conflict review, booking, an invite, decline or reschedule, finding a time, or a meeting brief.
Every `references/...` path in this skill is relative to this skill directory.
1. Run `pa.capabilities`; use the profile's own calendar tool, Google through `gog` first (PA holds no Google token), then verify with a read-only calendar call.
2. Accept explicit read scope and use `pa.context` for the selected source or action. Before proposing a time, read the manual's Calendar rules (meeting lengths, buffers, focus blocks, horizon) and `profile` person rules for each attendee.
3. `pa.action_upsert` stages one private packet or proposed event; do not use transaction operations for a packet.
4. Write only after the owner's yes and a conflict check, following `references/calendar-writes.md`: every time in RFC3339 with an IANA zone, buffers and focus blocks kept, `--dry-run` first. A private event that notifies nobody is written with the profile's calendar tool, then read back. An invite, a guest-notifying update, a decline or a reschedule goes through `pa.action_prepare` with `enforcement_profile: "exact_action"` and the complete command; the approval packet shows the attendees and whether guests are notified, and `--send-updates all` appears only after the yes. Confirm with `pa.action_confirm`, invoke the exact tool directly so the native gateway claims the one matching call, and use `pa.action_cancel` if the owner withdraws. Read the event back and call `pa.action_result`; never say "invited" before the readback shows the attendees.
5. To find a time across people or zones, follow `references/find-a-time.md`: freebusy per attendee, each person's working hours in their own zone, 2–3 slots labelled with every participant's local time and offset. No hold or invite without a yes.
6. For tomorrow's meetings (the evening register's `meetings_to_confirm`), follow `references/meeting-brief.md`: a one-page brief, a confirmation draft sent only after a yes, and action items captured within 24 hours.
7. `pa.action_upsert` records event reference, safe proof, conflict, and follow-up.
Expected outcome: a conflict-free proposal, meeting packet or private event with verified readback, or an invite sent after a yes with the attendees read back.

Load `personal-assistant:personal-assistant` for the exact tool argument and state contract. A meeting packet or private event uses ordinary `action_upsert`; `pa.action_result` is only for an invite or guest-notifying change already claimed by the native gateway.
