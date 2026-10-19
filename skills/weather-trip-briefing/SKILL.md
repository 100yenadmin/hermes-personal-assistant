---
name: weather-trip-briefing
description: Use to check origin and destination weather for a trip, produce packing/travel advice, and feed nudges without inventing forecasts or taking irreversible actions.
metadata:
  openclaw:
    skillKey: weather-trip-briefing
  hermes:
    category: travel
    tags: ["travel", "weather", "briefing", "packing", "nudge"]
---

# Weather Trip Briefing

Every `references/...` path in this skill is relative to this skill directory.

Check weather for the trip and turn it into practical advice. Do not take irreversible travel actions from weather alone.

## Read

- `references/weather-playbook.md` for source, freshness, and output rules.
- `references/standing-orders.md` before recommending any action that changes bookings, sends messages, or spends money.

## Workflow

1. Identify origin, destination, departure window, arrival window, and first full day.
2. Use the configured weather source or tool. Record source and retrieval time.
3. Summarize temperature, precipitation, severe weather, snow, heat, wind, and air-quality alerts.
4. Give practical advice: umbrella, coat, sunscreen, buffer time, road caution, or packing note.
5. Mark stale, missing, or preliminary data clearly.
6. Route any booking changes, messages, rideshare timing changes, or purchases through the relevant action skill and final-state confirmation summary.

## Output Shape

```text
Weather: New York arrival Wed 9 PM, light rain likely, 54 F.
Practical note: pack a compact umbrella and add a 10-15 minute pickup buffer.
Source: configured weather provider, checked today.
```

## Must Not

- Do not invent forecasts or alerts.
- Do not claim live weather was checked if no source was available.
- Do not cancel, rebook, order, message, call, or spend from a weather briefing without routing through the relevant action skill and final-state confirmation.
