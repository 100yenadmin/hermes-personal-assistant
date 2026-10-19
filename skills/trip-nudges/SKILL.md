---
name: trip-nudges
description: Use to proactively nudge the user during a trip about airport timing, weather, check-in windows, hotel arrival, local suggestions, food timing, and next travel actions.
metadata:
  openclaw:
    skillKey: trip-nudges
  hermes:
    category: travel
    tags: ["travel", "nudges", "schedule", "weather", "proactive"]
---

# Trip Nudges

Every `references/...` path in this skill is relative to this skill directory.

Send practical travel nudges that help the user move through the trip. Nudges should be timely, concise, and actionable.

## Inputs

Use itinerary facts from `itinerary-intake`, confirmed calendar events, weather data, provider check-in windows, and user preferences. Read `references/nudge-schedule.md` for lead times, quiet hours, and stale-data suppression.

## Nudge Types

- Airport departure timing.
- Online check-in window open.
- Boarding pass reminder.
- Baggage or document reminder.
- Weather and packing note.
- Hotel check-in timing.
- Meal or food-delivery suggestion after arrival.
- Local activity suggestion when there is open time.

## Rules

- Do not book, order, reserve, call, cancel, send, or pay from a nudge without a relevant action skill and final-state confirmation.
- If the nudge recommends an action, include the next executable agent action: search, compare, draft, prepare, or ask for final confirmation at the final button.
- Keep messages short enough for SMS or chat.
- Do not nudge from stale, contradicted, missing, or unverifiable trip facts.

## Example

```text
You should leave for SFO around 5:35 AM for your 8:10 AM flight. Traffic is normal, and online check-in is open. I can check you in now if you want.
```
