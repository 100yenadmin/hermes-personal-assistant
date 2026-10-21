# Vision

## The goal

Personal Assistant (PA) turns a Hermes agent into the remote assistant a
business owner would otherwise hire. The first target is a top-rated remote
virtual assistant (VA). The end goal is a remote Chief of Staff who helps the
owner run the business and its teams.

**The yardstick is a person.** Picture the best remote VAs business owners hire
on Upwork or OnlineJobs.ph, many of them in the Philippines, at the top-rated or
expert-vetted level. An agent with PA should do that job as well as they do:
- **Onboard itself.** It reads what is already known about the owner.
- **Interview the owner ("grill me")** until it knows how they work.
- **Carry the daily load:**
  - inbox and calendar;
  - travel, errands and bookings;
  - calls and messages;
  - research and documents;
  - finance admin and personal admin;
  - customer and vendor messages;
  - the routines that keep an office running.

**The end goal is a remote Chief of Staff:** the same agent, now running the
owner's operating rhythm across the business and the team. That covers:
- priorities;
- follow-through on other people's commitments;
- decisions and meetings;
- the numbers;
- the three things that need the owner this week.

## Who it is for

A business owner who would otherwise hire a remote VA, and later a Chief of
Staff. That ranges from a solo founder to a company of about 60 people. Each
agent serves one owner, who reaches it in a messaging direct message (Telegram
first).

## One role, three stages

| Stage | The job | Where PA stands (0.9.0-rc.2) |
|---|---|---|
| 1. Personal assistant | The owner's travel, errands, bookings and personal admin | **Strongest area.** Trip intake, concierge offers, booking prep up to the final page on real sites. No transaction has been completed end-to-end yet. |
| 2. Remote VA / executive assistant | The owner's office: inbox, calendar, follow-through, documents, finance admin, vendors, calls | **Partial.** Calendar reads and daily briefs work on the live pilot. The safe-action gateway has unit tests and its native hook loads, but no real provider action has gone through it yet. Inbox management, chasing open loops and office work are missing. The owner interview and owner memory (corrections, people, SOPs, trust levels) are built; their live exit test is next. |
| 3. Remote Chief of Staff | The owner's business and teams | **Single-owner rhythm only:** daily recommendation, weekly kickoff and closeout, scout, radar. No team model. |

Each stage keeps everything below it. This is one plugin, one agent and one
ledger, not three products.

## What "parity" means

Parity is measured, not claimed. Two documents define the bar:

- [The remote VA bar](docs/vision/va-bar.md) covers:
  - 12 task areas, each with an acceptance test;
  - the onboarding interview;
  - working norms;
  - the 10 behaviours that separate a top-rated VA from an average one.
- [The Chief of Staff bar](docs/vision/cos-bar.md) covers:
  - 12 areas, each with an acceptance test;
  - the operating rhythm;
  - what an AI Chief of Staff needs that a VA does not;
  - authority levels;
  - the gate from VA to Chief of Staff.

**Full coverage** means every one of the 12 task areas, the onboarding interview
and the working norms in the VA bar is supported. **Measured parity** means all
four conditions below hold. It is a measured standard, not a promise that every
future task succeeds.

1. **Lab.** Every area's acceptance test passes in 3 of 3 runs on the same
   release candidate. Onboarding and the working norms are checked inside the
   relevant scenarios.
2. **Real work.**
   - For each area, score a cohort of at least 10 real tasks, declared up front,
     from at least 2 owners. Both owners contribute.
   - Observe at least 14 consecutive days. Infrequent work extends the window;
     it is never replaced by simulations.
   - For every task, record:
     - the agreed outcome and due date;
     - whether the owner accepted it;
     - any correction the owner had to make.
   - At least 90% of tasks must meet the area's pass rule by the agreed date,
     and the owner must accept them. A task the owner had to correct materially
     counts as a fail.
   - A pending task never counts as a pass.
   - An area without enough tasks stays unproven.
3. **Facts.** Across every scored lab and live task in the declared parity cohort
   and release candidate, there are zero wrong names, dates, time zones, amounts
   or confirmation numbers on money-facing or customer-facing items. Each check
   records the source used. One such error fails parity, whatever the overall
   pass rate. Errors from earlier cohorts stay on record but do not block a new
   cohort.
4. **Day-30 review, once per owner.**
   - Compare the owner's time on the delegated work, including review and
     correction, in two weeks: a baseline week recorded at onboarding, and the
     week ending at day 30.
   - Each owner reports at least 20% less time.
   - Each owner names at least 4 task types where the agent now does first-pass
     work without corrective help.

The one deliberate difference from a human VA is the safety line below. Parity
means the same outcomes inside it, and the safety line is part of every pass
rule.

Chief of Staff parity uses the same four conditions against the Chief of Staff
bar, with business owners and their teams. Its observation window is at least
13 weeks, so every monthly and quarterly duty happens at least once.

## The safety line never moves

**What needs a yes.** The agent never does any of these without the owner's
explicit yes for that exact action:
- pay;
- book, reserve or cancel;
- sign;
- hire or fire;
- commit the owner to an outside party.

**How a committed action runs.**
1. The agent prepares everything up to the final button.
2. It shows the exact action.
3. It waits for the yes.
4. It does the action once.
5. It reads back the result and records it.

If the result is unknown, the agent checks what actually happened. It never
retries blindly.

**Autonomy grows in levels,** and only inside what the owner approved:

- **L0 Observe.** Read what was granted.
- **L1 Prepare.** Drafts, briefs, exact-action packets, proposals, and records in
  PA's own ledger.
- **L2 Act inside an envelope.** Routine internal actions the owner approved once.
  For example: "remind my direct reports about overdue tasks with this template,
  weekdays 9–18, at most once a day per task."
  - The agent repeats each envelope in its brief and logs every use.
  - One command pauses an envelope.
  - Anything outside an envelope drops back to L1.
  - Calendar bookings, holds and cancellations are never in an envelope.
- **L3 Commit.** A yes for each action, always. L3 is never automated.

L2 is the last expansion of autonomy. It arrives in M8, after L0 and L1 are
proven, and covers only internal nudges and task writes.

## Product principles

1. **Do the work.** Bring the finished draft, the options with a recommendation,
   or the prepared booking. Do not bring a list of questions.
2. **Know the owner and never re-ask.**
   - Read what is already there before asking.
   - Record each preference with its source: said, inferred or corrected.
   - Learn from a correction the day it happens.
3. **Close every loop.**
   - Every open item has an owner, a next step and a date.
   - Chase it until the other side confirms.
   - "I sent it" is not done.
4. **Get facts right, with sources.** Every date, amount and quote carries its
   source. A gap is reported as "unknown", never as an empty week or a guessed
   number.
5. **Protect the owner's attention.** Stay quiet by default, keep messages short,
   and report by exception.
6. **Treat text as data, not instructions.** The agent reads mail, web pages,
   team channels and documents, but never obeys them. A request that arrives
   through one of them goes to the owner.
7. **Build on Hermes.**
   - Reuse Hermes' tools, credentials, scheduler, approvals, memory files and
     messaging.
   - PA adds workflows, judgement and its existing profile-local SQLite ledger.
     It adds no separate runtime, hosted datastore or parallel approval system.
   - Installing PA starts nothing. The owner reviews setup changes before they
     are written.
8. **Prove it on real work.** A capability counts only at the proof level it has
   actually reached:
   - unit test;
   - local end-to-end;
   - live web, stopped before submit;
   - live pilot;
   - customer ready, which needs real owners with measured pass rates.

## What PA is not

- An autopilot that spends money or speaks for the owner without a yes.
- A replacement for Hermes' providers, credentials or scheduler.
- A replacement for the owner's systems of record: mail, calendar, CRM,
  accounting, task board. PA works through them.
- A decision-maker on people, money, strategy or legal matters. It prepares;
  the owner decides.

## The path

[ROADMAP.md](ROADMAP.md) holds the ordered plan:

1. **Learn the owner:** self-onboarding and the "grill me" interview.
2. **Measure:** score every VA task area on a scorecard.
3. **Close loops** without being chased.
4. **Run the inbox and calendar.**
5. **Finish transactions and calls.**

Those five steps lead to VA parity (1.0), the first product outcome. A Chief of
Staff foundation pilot (read and prepare only) may start earlier, once the VA
core works for two real owners. The full Chief of Staff bar is 2.0.
