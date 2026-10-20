---
name: personal-assistant:r1-trip
description: Capture, change, and export a trip through the Personal Assistant.
metadata:
  hermes:
    namespace: personal-assistant
    recipe: R1
    lazy: true
---
# Personal Assistant R1: Trip

Load only for trip import, an explicit change, or an ICS or Markdown export.
The native `pa` tool owns the record and source revision.
1. Use `pa.context` with kind `trip`, `source`, or `guide`; `pa.trip_import` applies only source facts. If `next_step.offer_trip_watch`, load `personal-assistant:trip-concierge` and ask `next_step.question` once.
2. Use `pa.next_action` for linked commitments and ask one blocking question only when needed.
3. `pa.action_upsert` records preparation and `pa.export` writes to a fresh directory. For a refresh, pass `overwrite=true` only for PA-generated files from the same profile and trip whose prior hashes still match; otherwise keep the default refusal.
4. Read the files back with the available file tool and check that shared output contains no credentials or personal booking records.
5. `pa.action_upsert` records safe readback proof and follow-up; omitted facts stay known and removed facts clear.
Expected outcome: a current trip and credential-free export receipt.

Load `personal-assistant:personal-assistant` for the exact tool argument and state contract. R1 has no provider transaction, so do not call `pa.action_prepare`, `pa.action_confirm`, `pa.action_claim`, or `pa.action_result`.
