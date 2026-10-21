# Operating-manual skill template

Use for a new manual only; patch an existing PA user skill in place. Replace
placeholders with reviewed safe facts. Keep the finished daily manual near 8 KB.
Use one section per domain; distil rather than append. Do not copy private source
text into this template or export a populated manual. Keep the `description` to
one sentence of at most 60 characters: Hermes' skill index cuts longer ones off.

```markdown
---
name: operating-manual
description: Use for this user's briefs, inbox, calendar and travel.
metadata:
  openclaw:
    skillKey: operating-manual
  hermes:
    category: productivity
    tags: ["personal-assistant", "manual", "daily"]
---

# Operating Manual
Daily operating guidance for <name>'s assistant. Not for product or engineering notes,
or one trip's dates and times: PA trip records hold those.

## Settings

| Setting | Accepted value | Where it came from | Source that wins |
|---|---|---|---|
| Preferred name and tone | <value or unknown> | <user answer or profile source> | <accepted authority> |
| Quiet hours and exceptions | <value or unknown> | <source and date> | <PA preferences / supported wake setting> |
| Check-in lead | Check in <N> hours before departure; move to the evening before if quiet | <user agreement and date> | <manual / compact USER.md preference> |
| Brief time and publisher | <value or unknown> | <reviewed existing job> | <one named schedule owner> |
| Primary delivery route | <safe channel role or unknown> | <user choice and verification> | <accepted route> |

Record the source and conflict winner for every added setting. An explicit new
user correction changes the affected preference after review; it does not grant
new action authority. Do not keep competing copies of the same schedule.

## Effective timezone

<IANA zone, basis, date verified, and whether timing follows travel-local time.>
Separate calendar storage zone, scheduler zone and the user's current local time.
Derive travel location from current confirmed trip facts; conflicts stay unknown.
Recheck the effective zone before scheduling. Do not turn a home zone into proof
of current location or claim prose settings have changed running jobs.

## Source hierarchy

<Authoritative calendar role; mailbox role; confirmed itinerary source; fallback.>
Use the accepted source for each domain. Recover relevant existing information
before asking again, including read mail when authorized. A missing, stale or
truncated source is a coverage gap, not a cancellation or an empty schedule.

## Uncertainty

Unknown stays unknown. Label inferred facts and their basis. Do not invent a
commitment, current city, provider availability, or a successful action. Ask only
for unresolved choices that matter now; flexible days may have no fixed event.

## Permissions

<Allowed preparation, never-do list, contacts, and scopes accepted by the user.>
Prepare within scope; ask before paying, booking, sending as the user, contacting
people or cancelling. Reading, proposing, calendar edits and cleanup have distinct
permissions. Promotions are not spam; do not bulk-delete or mark read by assumption.
Connected accounts and saved payment methods are not authority to act.

## Pause and resume

<How to pause the selected routines and how to resume them with verified state.>
Pausing the setup interview does not pause running jobs. State exactly which
routine is paused. Resume from unanswered choices and pending work, not from zero.

## Failure and delivery

Report what failed, which source or step is affected, and the next useful action.
Keep incomplete coverage distinct from nothing to report. A job's latest OK
status does not prove a particular occurrence reached the chosen destination.
Delivery requires that occurrence's destination and receipt; preparation or a
provider link is not completion. Never call an uncertain submission failed and retry.

## Travel profile

<Reviewed preferences, airport lead times, arrival help and protected commitments.>
Keep canonical itinerary facts in PA. Judge arrival at the venue using immigration,
bags, transfer and buffer, not touchdown alone. Respect quiet hours and per-trip
night-alert consent. Never imply monitoring is instant or delivery guaranteed.
Save the agreed lead as “check in N hours before departure” (default suggestion:
3 hours). Pass N × 60 as `check_in_lead_minutes` to trip-concierge. Evaluate PA
and HB2 quiet windows in departure-local and configured profile timezones; move a
quiet-hours candidate to the evening before. HB2 defaults to 22:00–08:00; its
config and chat overrides are separate from PA. Do not claim alignment until the
user confirms the HB2 setting.

## Routines

<For each: trigger, authorized inputs, useful output, timezone, publisher, route,
pause/resume, failure behavior, and source of the accepted setting.>
Keep one publisher per brief or alert. Speak when there is a decision, deadline
or preparation worth acting on: explain why now and the next action. Stay silent
for unchanged checks; omit counters, job IDs and generic inbox instructions.
Keep daily guidance short. The weekly closeout flags a manual beyond about 8 KB.

Engineering or product lessons go to the repo or an issue, not here.
```
