# Roadmap

[VISION.md](VISION.md) sets the goal and the bar. This file sets the order of
work.

**How milestones work.**
- Each milestone has a target release, with release candidates first. M6 (1.0)
  and M9 (2.0) are major releases.
- Milestones run in order. The one allowed overlap is the M7 pilot, at its gate.
- It names the bar areas it closes and has an exit test.
- A milestone is done when its exit test passes, not when its code is merged.
- The order is committed; dates are not.

## Where we are (0.8.0-rc.3, 21 October 2026)

**Live proof.** PA is live on one internal pilot agent, which serves the owner.
That pilot has shown:
- trip import from the calendar;
- weather offers during a trip;
- guided setup, both the core and the Chief of Staff sections;
- two Chief of Staff daily reports delivered;
- a restaurant search that stopped correctly before booking.

**Strong:**
- travel prep (hotels and restaurants on real sites up to the final review page);
- the safe-action gateway and the durable ledger;
- quiet-by-default reporting;
- Japan and Korea provider routing;
- simulated phone calls in Korean and Japanese.

**Missing against the VA bar:**
- inbox management;
- calendar work for others (invites, finding times);
- chasing open loops;
- office work: documents, data and finance admin;
- messaging contacts for the owner;
- completed transactions and real phone calls;
- learning from corrections between setups.

**Missing against the Chief of Staff bar:** everything that involves the team.
That is the roster, reading team systems, delegation across people, a decision
log, meeting capture, a scorecard, L2 envelopes and a project register.

### Status against the VA bar

| VA bar area | Today | Closed in |
|---|---|---|
| Onboarding interview ("grill me") | partial: 8 core and 6 Chief of Staff questions, weighted to travel | M1 |
| Preference and voice learning | missing | M1, plus the voice test in M6 |
| Recurring ops | partial: routines run, but they are not scored and not proven unattended | M2, M3 |
| Research | partial: adopt-or-build research only | M2 |
| Travel | partial: prep up to the final page, nothing completed | M0 (real trip), M5 (completion) |
| Personal life admin | partial: no renewal or birthday radar | M3 |
| Follow-up, reporting, escalation | missing or partial | M3 |
| Inbox | missing | M4 |
| Calendar | partial: reads and conflict checks | M4 |
| Errands and bookings | partial: stops correctly before booking, nothing completed | M5 |
| Phone and messages | partial: call brief and simulator; the post-call poller ran on one real inbound call. PA cannot place or answer live calls yet | M5 |
| Documents and data | missing | M6 |
| Finance admin | missing | M6 |
| Customer and vendor messages | missing | M6 |
| Social and content admin | missing | M6 |

## Milestones

### M0: Finish the 0.8 pilot (0.8.0)

**Why.** It proves the travel concierge on a real trip and gets PA into the
plugin catalog.

**Scope.**
- Travel concierge on the owner's real trip (#1).
- PA's own Daily Ops jobs reach the user on Hermes v0.22.2 (#21).
- Browser handoff: `agent-browser` reachable where PA runs (#39).
- Small fixes on the current path: #17, #35, #36.
- Shared-group setup (#37) waits until shared groups are in scope or a pilot
  report needs it. The pilot uses a direct message.

**Exit.**
- #1 passes on the real trip.
- 0.8.0 is published.
- The catalog pull request is submitted (#2).

### M1: Knows you, with self-onboarding and "grill me" (target 0.9.0)

**Why.** Every VA task depends on what the agent knows about the owner. A top VA
spends the first weeks learning the principal. Our pilot agent re-asked a known
name and forgot corrections until the next setup review. Fixing this first
avoids rebuilding every later workflow.

**Scope.**
- **"Grill me".** The owner can ask for the deep interview at any time. The
  question bank covers the bar's eight groups:
  1. the business;
  2. you;
  3. communication;
  4. decision rights and spending limits;
  5. preferences and voice;
  6. calendar rules;
  7. history and worries;
  8. access.

  The interview runs in short sittings, one group at a time. The agent reads
  each answer back.
- **Read before asking.** With consent, the agent reads sent mail, past
  itineraries and the calendar. It then proposes answers instead of asking.
- **Never re-ask.** One record holds what was asked and answered. A test fails
  any question whose answer is already on file. This fixes three pilot faults:
  - the re-asked name;
  - the core section restarting uninvited;
  - inconsistent records of what was asked.
- **Preferences with sources.** Each preference is recorded as said, inferred or
  corrected. A correction is captured when it happens, not at the next review.
- **People.** Key contacts and VIPs, each with:
  - their role;
  - their preferred channel;
  - rules such as "never call before 10" or "always copy my partner".
- **SOPs.** After doing a recurring task once, the agent writes its SOP for the
  owner to correct: trigger, steps, tools, what done looks like, escalation.
- **Authority and trust.**
  - Decision rights and spending limits per category.
  - A written list of what the agent may access.
  - A trust level per task type: shadow, then own, then independent.
  - A day-30 review in the weekly closeout.
- **Availability.** Working hours, response expectations, an away handoff and
  the emergency route are recorded and used in reporting and escalation.

**Exit.**
- The persona-rig tests pass for zero re-asked facts and for corrections that
  persist.
- On the pilot agent:
  - the owner completes the eight-group interview, with no confirmed fact asked
    again;
  - in a fresh session, the agent recalls one corrected preference, uses one
    contact rule and retrieves one captured SOP;
  - the owner confirms the profile read-back, the access list, the trust levels
    and the day-30 time baseline.
- The day-30 outcome itself is judged later, at parity.

### M2: Measured, with the VA scorecard (target 0.10.0)

**Why.** Parity needs a measuring stick. Without one, every claim stays at
unit-test level.

**Scope.**
- **Lab fixtures.** The Capability Lab gets one seeded fixture per VA bar area:
  - a 40-email inbox;
  - a calendar week;
  - a Singapore trip;
  - a dinner and a repair errand;
  - three calls;
  - a payroll research question;
  - a 300-row contact list and a meeting recording;
  - 60 transactions;
  - a renewals profile;
  - 15 customer messages;
  - five voice notes;
  - a 10-day ops run.

  Each fixture checks the bar's pass rule with fixed checks plus a judge. Any
  factual error counts as a failure.
- **Scorecard.** A pass or fail per area for every release candidate, published
  with the release evidence.
- **Live evidence.** For each real task on a pilot agent, record:
  - the owner and task area;
  - start and due dates, and the agreed outcome;
  - pass, fail or pending;
  - whether the owner accepted it, and any correction they made;
  - the source used to check each fact.

  Each owner's onboarding time baseline and day-30 review are captured too. The
  scorecard evaluates the four parity conditions in VISION.md and shows missing
  evidence as unproven.
- **Chief of Staff edit check (#6).** Before keeping a consequential Chief of
  Staff proposal, compare old and new text on the frozen failure and one
  ordinary case, with the same model and settings.
  - A tie means "no regression detected".
  - An edit whose inputs cannot be frozen cheaply is labelled unchecked.
  - This is not a gate on every skill edit.
- **First checks.**
  - General research, through a new research skill, is the first full VA area
    to pass.
  - Three partial checks run now and do not count as passes for their full
    areas:
    - recurring routines running;
    - travel prep;
    - calendar reads and conflicts.
  - The full areas close later: recurring ops in M3, calendar in M4, travel in
    M5.

**Exit.**
- The scorecard runs on every release candidate.
- It publishes a 0.9 baseline for all 12 VA areas, with failures and
  not-yet-exercised checks shown.
- General research and the three partial checks pass 3 of 3.
- Live task recording and the day-30 baseline are exercised on the existing
  pilot.

### M3: Closes every loop (target 0.11.0)

**Why.** Closing loops without being chased sets a top VA apart. Today PA leaves
its own open asks as "unknown".

**Scope.**
- **Open-loop ledger.** Every ask, delegation and promise has an owner, a next
  step and a date.
- **Chase ladder.** It runs on HeartBeat 2.0 and cron:
  1. chase on day 2;
  2. chase on day 5;
  3. chase on day 10;
  4. then escalate to the owner with options and a recommendation.

  An item closes only when the other side confirms.
- **Radar** for:
  - renewals: passport, visas, insurance, subscriptions;
  - birthdays and gifts;
  - deadlines found in mail and the calendar;
  - unanswered offers.
- **Reporting.**
  - An end-of-day note: done, in progress, and blocked with questions.
  - Exceptions reported straight away.
  - Progress notes during long tasks.
- **Reliability.**
  - The agent handles Hermes `tool_call` failures.
  - Daily Ops are proven live.
  - A 10-day unattended run fills the canary scorecard.

**Exit.**
- The chase and personal-admin radar fixtures pass.
- The pilot's open asks are chased or escalated, under the existing approval
  rules. Before M4, reminders to the owner and approved nudge drafts are enough;
  automatic sends to third parties are not required.
- Over ten working days with no owner rescue:
  - every due routine runs on time;
  - each daily report has done, in progress, and blocked with questions;
  - a deliberately broken routine is caught within one cycle;
  - at least two SOP improvements are recorded.

### M4: Runs the inbox and calendar (target 0.12.0)

**Why.** The inbox and calendar take up most of a VA's day, and a Chief of Staff
needs both.

**Scope.**
- **Inbox.**
  - Triage twice a day into urgent, needs you, handled, FYI and junk.
  - A digest of five lines or fewer.
  - Every thread tracked to a reply or a decision.
  - Drafts in the owner's voice, which stop before sending.
- **Calendar.**
  - Write events with buffers and focus blocks.
  - Invite attendees.
  - Find a time with other people across time zones.
  - Confirm each meeting 24 hours ahead with a one-page brief.
- **Tools.** Everything runs through Hermes' existing mail and calendar tools,
  Google through `gog` first.

**Exit.**
- The inbox and calendar fixtures pass 3 of 3.
- On the pilot agent, after the owner's yes, three things happen live: a triage
  digest is delivered, an in-voice draft is sent, and an invite is sent.

### M5: Finishes the job: transactions, calls and vendors (target 0.13.0)

**Why.** A VA finishes errands. PA still stops at the handoff.

**Scope.**
- **Browser handoff.** A live browser handoff inside Hermes for card, OTP,
  passport and CAPTCHA steps (#25, #39), plus payment readiness (#11).
- **A completed booking.** One real booking done after the owner's yes, with a
  readback and a calendar entry (#10).
- **Real calls.**
  - A real phone transport (#4).
  - A mid-call check with the owner, and an answering service (#30).
- **Errands and vendors.** Errands and vendor requests land on the calendar with
  a reminder after the yes. Calls end with a structured note.
- **Travel after booking.**
  - Keep the complete itinerary.
  - Handle a changed or cancelled leg with options.
  - Record trip expenses for M6's finance work.

  Live flight updates may come from authorised mail and calendar sources. The
  AeroAPI route (#3) is optional.

**Exit.**
- One real booking, explicitly approved, completes with the provider's readback,
  a correct itinerary and calendar entry, and a reminder.
- The travel, errand and outbound phone fixtures pass 3 of 3.
- With consenting test callers:
  - one outbound call returns a structured note;
  - one inbound call follows the answering rules;
  - one mid-call question reaches the owner, or takes the stated
    timeout-and-callback path.

  This proves calling works. It is not VA parity.

### M6: Remote VA parity (target 1.0.0)

**Scope.**
- **Documents and data.** Minutes, agendas, spreadsheets, and a de-duplicated
  contact list with a log of every change.
- **Finance admin.** Categorise, reconcile and send invoice reminders. It never
  pays.
- **Customer and vendor messages,** answered under the owner's written policy.
- **Content admin,** inside the owner's approval flow.
- **The rest of the VA duties behind the fixtures.**
  - Filing and CRM updates.
  - Invoice preparation, expense reports, the weekly cash position, monthly
    reconciliation and income and expense summaries, and the accountant's tax
    pack.
  - Routine customer and content reporting.

  The working norms are checked during these tasks. A passing sample fixture
  does not close duties it never exercised.
- **Voice test.** In a blind review, five agent drafts are mixed with five
  owner-written samples. The owner judges at least four of the agent drafts
  sendable with at most two edits each. The ratings and edits are recorded.
- **Parity.** The parity rule in VISION.md is met with at least 2 real owners.
- **Product materials.** The docs, catalog page and onboarding card are updated
  for the VA product.

**Exit.**
- Every VA bar area meets the parity rule.
- PA is claimed customer ready, with the pass-rate evidence.

### M7: Chief of Staff foundation (target 1.1.0)

**Gate.** M7 may begin as a read-and-prepare pilot once the M1 to M4 exits pass.
In real sessions, two consenting owners must each show the core path:
- onboarding, and recall of a correction;
- an open loop chased or escalated;
- an inbox digest and an approved reply;
- a calendar invite and brief.

The pilot may overlap M5 and M6, but VA parity stays the first product outcome.
M7 claims neither full VA parity nor Chief of Staff parity.

**Scope.** M7 covers levels L0 and L1 only.
- **Chief of Staff interview.** The team roster, roles, who reports to whom, time
  zones, and who owns what.
- **Reading team systems through Hermes.**
  - Team chat on Telegram, Discord or Mattermost.
  - The task board: Hermes Kanban first, then GitHub issues or Linear.
  - Shared documents.

  Every report says what was read and what could not be.
- **Delegation ledger.** Who owes what to whom, and by when. Nudges are drafted
  for the owner.
- **Decision log.** Each entry has six fields:
  - the decision;
  - the rationale;
  - the options rejected;
  - the owner;
  - the date;
  - the revisit trigger.

  The agent recalls an entry when its topic returns.

**Exit.**
- The delegation and decision-log fixtures pass.
- Two consenting owners with teams each receive six scheduled Chief of Staff
  reports within two weeks (#7). Justified silence counts as a report.
- Each owner uses at least one recommendation and explicitly chooses to
  continue. Delivery alone does not pass this exit.

### M8: Chief of Staff operating system (target 1.2.0)

**Scope.**
- **Meetings.** Pre-reads 24 hours ahead. Actions and decisions captured from
  transcripts.
- **Scorecard.** A weekly KPI scorecard with sources. A broken feed shows
  "unknown", never zero.
- **Projects.** A register of cross-team projects that detects dependencies.
- **Calendar defence.** Protect deep-work blocks, and name a substitute for each
  meeting the owner can skip.
- **Operating cadence.** List every recurring forum with its purpose, owner and
  cost. Run the monthly cadence audit. Retire or combine redundant meetings when
  the owner decides to.
- **Communications.** Run the Chief of Staff voice test on drafts for the team,
  customers, partners and the board, reusing M6's voice learning.
- **L2 envelopes** for internal nudges and task writes. Calendar bookings,
  reservations, holds and cancellations still need an explicit yes for each
  exact action.

**Exit.**
- These Chief of Staff bar tests pass 3 of 3 in the lab:
  - calendar defence;
  - operating cadence;
  - meeting prep and follow-through;
  - KPI scorecard;
  - cross-team projects;
  - communications.

  Each of those areas also has one accepted real-work example. These are
  interim proofs, not the M9 parity sample.
- Over two weeks, a pilot runs one approved internal-nudge envelope and one
  approved task-write envelope, and pauses each one successfully. Nothing
  happens outside the approved envelopes.

### M9: Remote Chief of Staff (target 2.0.0)

**Scope.**
- A quarterly OKR loop.
- A board and investor pack process.
- Hiring and onboarding support.
- Special projects beyond tool choices.

**Exit.**
- Every Chief of Staff bar area meets all four parity conditions in VISION.md,
  with at least two business owners and their teams, including the lab checks
  and each owner's day-30 review.
- The observation window stretches to take in infrequent duties. Until they are
  observed, those areas stay unproven.

## Why this order

- **Onboarding comes before integrations.** Every later workflow uses the owner
  profile. Building the inbox or delegation on a thin profile would mean
  rebuilding them later.
- **The scorecard comes second, not first.**
  - M1 is cheap, and it fixes faults already seen live.
  - The scorecard lands before the expensive integration milestones, so M3 onward
    is measured.
- **The Chief of Staff gate is the VA core, not full parity.** Transactions and
  phone calls depend on outside accounts. Team work does not depend on them.
- **L2 is the last expansion of autonomy.** It arrives in M8, after L0 and L1
  are proven, and covers only internal nudges and task writes. L3 always needs
  an exact-action yes.
- **Lowest-value areas go last in their milestones.** Content admin and board
  packs matter least to an owner-operator.
- **Not on a milestone yet:** live flight status with a user's AeroAPI key (#3).

## Decisions the owner holds

- A second pilot user, for the VA scorecard and the Chief of Staff pilot (#7).
- A phone number and accounts for real calls (#4).
- For M7: two business owners with teams who will grant read access to their
  team systems.

## Keeping this file current

The product and release manager updates this file in the same pull request as
the evidence in either of two cases:
- a milestone's exit test passes;
- the order changes.

Each milestone (M0 to M9) has a GitHub milestone of the same name, and its work
is tracked in issues.
