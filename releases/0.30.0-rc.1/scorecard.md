# PA 0.30.0-rc.1 VA scorecard

Commit: e616adb5ed1417f935c97f9282274974ced3277b · As of: 2026-11-17

Lab: 1 pass · 8 areas with partial checks passing · 5 areas with partial checks failing · 0 fail · 13 unproven · 0 not exercised

| Area | Lab | Partial checks | Real work | Facts | Parity | Closes in |
| --- | --- | --- | --- | --- | --- | --- |
| Inbox | unproven | pass | unproven | unproven | unproven | M4 |
| Calendar | unproven | pass | unproven | unproven | unproven | M4 |
| Travel | unproven | fail | unproven | unproven | unproven | M0 (real trip), M5 (completion) |
| Errands and bookings | unproven | fail | unproven | fail | fail | M5 |
| Phone and messages | unproven | pass | unproven | unproven | unproven | M5 |
| Research | pass | none | unproven | unproven | unproven | M2 |
| Documents and data | unproven | pass | unproven | unproven | unproven | M6 |
| Finance admin | unproven | pass | unproven | unproven | unproven | M6 |
| Personal life admin | unproven | pass | unproven | unproven | unproven | M3 (radar), M6 (the rest) |
| Customer and vendor comms | unproven | pass | unproven | unproven | unproven | M6 |
| Social and content admin | unproven | fail | unproven | unproven | unproven | M6 |
| Recurring ops | unproven | pass | unproven | unproven | unproven | M2 (check), M3 (daily and weekly), M6 (monthly, quarterly, licences and contracts) |
| Onboarding | unproven | fail | unproven | unproven | unproven | M1 |
| Working norms | unproven | fail | unproven | unproven | unproven | M1 (preferences); norms checked inside scenarios |

## Day-30

State: unproven

## Fire-me week (stitched)

Week N strings together run N of every scenario a persona meets, in day order, and the simulated owner fires PA at the first failing run. The runs are separate lab sessions, not one continuous week. Weeks differ in length and some share scenarios, so compare a persona with itself across releases, not personas with each other.

- Solo founder (10 scenarios over 5 days): 1 of 3 weeks kept.
  - Week 2: fired on day 1 at s35_onboarding_first_win_en: checks failed: inbox:no_terminal_steps; judge: Explicitly instructed the owner to restart with /new, switch models, or run hermes doctor, violating the onboarding contract prohibiting restart and terminal-command requests.
  - Week 3: fired on day 3 at s38_content_calendar_en: checks failed: content:calendar_valid; judge: Week 2 has only one Instagram slot, below the required minimum of two per channel per week.
- Executive (10 scenarios over 5 days): 0 of 3 weeks kept.
  - Week 1: fired on day 4 at s03_sf_tokyo_en: run timeout; checks failed: taxi:final_or_handoff
  - Week 2: fired on day 4 at s03_sf_tokyo_en: run timeout; checks failed: taxi:final_or_handoff
  - Week 3: fired on day 3 at s37_approval_day_en: checks failed: travel:confirmed_first, travel:rebound; judge: After approval, created a different action with a changed summary instead of confirming the original prepared action with its identical summary.
- Agency owner (10 scenarios over 5 days): 2 of 3 weeks kept.
  - Week 3: fired on day 3 at s38_content_calendar_en: checks failed: content:calendar_valid; judge: Week 2 has only one Instagram slot, below the required minimum of two per channel per week.
- Family user (6 scenarios over 5 days): 3 of 3 weeks kept.

## Excluded runs

Count: 0

## Unexercised duties

### Inbox

- Triage at least twice a day: urgent / needs-you / handled / FYI / junk
- Track every open thread to a reply or decision
- Meet the agreed SLA
- Filter newsletters and spam without being asked

### Calendar

- Book with buffers and travel time
- Confirm every meeting 24h ahead
- Send an agenda and one-page brief
- Capture action items within 24h
- Decline and reschedule politely in the principal's name

### Travel

- Collect constraints once: budget, preferences, loyalty numbers, arrive-by
- Return 2-3 good / better / best options with totals and trade-offs
- Include check-in times, ground transport, addresses and contingencies
- Track changes and expenses afterwards

### Errands and bookings

- Find the right vendor
- Check availability and price

### Phone and messages

- Screen unknown callers
- Relay who, outcome, promises, next step and date
- Use the preferred channel per contact
- Never disclose private details or commit the principal

### Research

- No padding

### Documents and data

- Prepare proposals and slide skeletons

### Finance admin

- Categorise expenses and reconcile cards monthly
- Weekly cash position
- Monthly income/expense summary

### Personal life admin


### Customer and vendor comms

- First-line FAQ replies in company voice

### Social and content admin

- Keep a content calendar
- Turn raw notes into posts in voice
- Schedule into the approval flow
- Publish only inside the principal's chosen approval flow

### Recurring ops

- Maintain the SOP library
- Improve one SOP a week
- Track renewals, licences and contracts

### Onboarding

- Interview in short bursts across business, principal, communication, rights, preferences, calendar, history and access
- Write a living profile, read back for correction and never re-ask recorded answers
- Capture, correct and own recurring-task SOPs
- Arrange named least-privilege delegated access before day one
- Stage shadowing, process ownership, judgement and independence across the first 30 days
- Review quality, time saved, questions and the month-2 task wave at day 30
- Read granted material before asking; record preference provenance and learn from edits
- Propose repeated patterns, confirm inferences and read style guides on day one

### Working norms

- Report daily, weekly and immediately on exceptions
- Keep confidential details inside the role and agreed systems
- Use explicit correct time zones and plan holidays
- Check outbound facts, totals, links, attachments and placeholders; log errors and fixes
- Keep agreed hours, response SLA, away hand-off and emergency path
