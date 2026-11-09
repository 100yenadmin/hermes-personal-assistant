# Changelog

## 0.15.0-rc.1 — 2026-11-10

This release continues M6 (VA parity) with two more week-one duties from the 9 November gap review. On a busy day PA brings every decision the owner owes as a finished packet: the problem, the options, one recommendation, a decide-by date and the message ready to send. When the owner later says yes in a new chat, PA carries out the action it already prepared, exactly once. PA also plans the owner's social posts: a dated content calendar for each channel, the first posts drafted in the owner's voice, and every post held for the owner's yes. It still never posts, books, pays or sends without that yes.

It ships `releases/0.15.0-rc.1/scorecard.md`, built from 84 Capability Lab runs (28 scenarios, 3 runs each) pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`. {{RESULTS}} (73 of 78 in 0.14.0-rc.1). No run booked, paid or submitted anything with a real provider (zero tripwire hits); the bookings in s27 and s37 go to a stand-in provider.

{{BULLETS}}

Approval day (#160, #174):

- **Finished decisions.** Each open decision the owner owes comes with the problem, at least two options, one recommendation, a decide-by date no later than its due date, and the draft to send once the owner picks. Non-urgent questions arrive together, not one at a time.
- **The yes in a later chat.** When the owner's yes names an action PA already prepared, PA confirms that action; it never prepares a second one for the same yes. The approval moves to the new chat and is claimed once.
- **A repeated yes does nothing new.** PA reports the existing booking reference instead.
- Approval packets gain `decide_by` (no later than free cancellation) and a one-line `recommendation`.

Social and content admin (#157, #175):

- **New skill `content-admin`.** PA plans the requested window, 2 to 4 posts a week for each channel unless the owner says otherwise. Each slot has a date, a channel, a topic and one line on why. It never puts two posts on one channel on the same day, never schedules into quiet hours and never plans past the window.
- **Drafts in the owner's voice.** PA reads the owner's past posts first and matches their length, habits and sign-off. It follows the voice rules in USER.md, keeps to each channel's length limit, and never invents prices, quotes, numbers or customer names.
- **Every planned post is held.** Each slot is recorded as a dated deadline that comes up two days before its publish date, with the draft attached when there is one. A re-plan updates the same slots: it never duplicates them or reopens one the owner already posted or dropped.
- **Nothing posts.** Posting is an outward send that needs an item-specific yes, through a tool the owner connected. With no posting tool, PA hands over the final text for the owner to post.

Lab:

- **The claim detector** no longer reads a condition such as "remains open until completion is confirmed" as a completion claim, and the judge knows the cron receipt note the skill prescribes (#171, #172).
- **Rejudging** a run whose home folder is gone keeps that run's own file checks instead of failing them (#150, #173).
- **A scenario step can start a new chat** (`new_session`), so approvals can be tested across chats.
- **New scenarios:**
  - s37, an approval day with a yes in a new chat (#174);
  - s38, a two-week content calendar with three drafts (#175).

## 0.14.0-rc.1 — 2026-11-10

This release continues M6 (VA parity) and builds most of the week-one core from the 9 November gap review. PA writes meeting minutes with an owner and a date on every action item, imports card statements, stops counting a held draft as a chase, can run on its own schedule through a HeartBeat 2.0 role, catches inbox threads the owner read but never answered, and onboards a new owner with four questions and then a finished first task. It still never pays, disputes, books or sends without the owner's yes.

It ships `releases/0.14.0-rc.1/scorecard.md`, built from 78 Capability Lab runs (26 scenarios, 3 runs each) pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`. 73 of 78 runs pass (57 of 63 in 0.13.0-rc.1). No run booked, paid or submitted anything with a real provider (zero tripwire hits); the booking in s27 goes to a stand-in provider.

- **22 of 26 scenarios pass 3 of 3.** That includes meeting minutes (s34), onboarding (s35) and the read-but-unanswered inbox (s36) in their first release wave, along with invoices (s33), contacts (s32) and replies under policy (s31).
- **Seoul to Tokyo (s01) passes 2 of 3 and San Francisco to Tokyo (s03) 1 of 3.** All deterministic checks pass. The judge failed three claims about real pages:
  - one run tied a drinks-plan price to the wrong line;
  - one claimed to reach OpenTable's diner-details page without that page in its evidence;
  - one course price and cancellation fee were not matched in the evidence.
- **The weekly review (s16) passes 2 of 3.** One run failed the calendar-honesty check.
- **The follow-through chase (s20) passes 2 of 3.** The claim detector flagged one run's receipt note, "Final response handed to Hermes cron delivery". That is the note the skill tells it to record, so this looks like a detector false positive; a fix follows this release.

Meeting minutes (M6-d, #145, #163):

- **`pa minutes save`** takes the minutes the agent drafts from a transcript under `imports/`: title, date, attendees, overview, decisions, action items and open questions.
  - Every action item needs an owner, a due date and a quote from the transcript.
  - Files are private Markdown and JSON under `exports/minutes/`.
  - The transcript is left unchanged.
- **`pa minutes read`** pages through a long transcript (40,000 characters or 2,000 lines a page; a very long line continues on the next page), so the agent can read all of it before writing. It reads only from `imports/meetings/`.
- **Follow-through.** An item the owner owns becomes a reminder. Someone else's item becomes a held nudge on the day it falls due.
- Sending the minutes to attendees is still an exact-action send that needs the owner's yes.

Card statements (M6-e, #165):

- **`pa expense import`** first previews a card statement CSV from `imports/statements/` without writing anything. It then records every line it can read in one transaction, with the agent's category for each, and writes a private reconciliation report. Lines it cannot read are listed as skipped, with the reason, for the owner to review.
- **Identity.** A re-export with inserted or reordered lines keeps each charge's identity and any void, as long as it is imported from the same path. A renamed or moved file counts as a new statement: its charges get new records, and a voided charge can come back.
- **Possible duplicates** are listed, never merged: same merchant, amount and currency, at most 3 days apart, with no later refund. A refund request is drafted and held for each one.
- A card number anywhere in the file refuses the whole import.

Follow-up honesty (#153, #166):

- **A nudge PA drafted and holds for the owner's yes is no longer counted as a chase.**
  - `next_action` items gain `awaiting_approval`; it becomes overdue after 2 days.
  - Briefs and escalations say "awaiting your yes since <date>", never "chased".
- **Meeting items.** Someone else's meeting item gets its first nudge on its due date, not two days after it.

PA on its own schedule (#151, #167):

- **`pa capabilities`** reports whether HeartBeat 2.0 is installed and whether it supports roles.
- **Setup** offers one follow-through role: a daily run at the owner's morning-brief time, with a budget of 2 turns a day. It is created only on the owner's yes.
- **Inside that role's turns,** PA may arm up to 3 one-shot wakes for upcoming chase dates and approval timeouts, never one already armed or pending.
- **Without HeartBeat 2.0,** setup recommends installing it and is honest that scheduled delivery is unreliable on some Hermes versions.

Inbox: read but never answered (#154, #168):

- **Each inbox pass also covers read human mail from the last 7 days.** A thread whose last message asks something of the owner is tracked, named "read, not answered" in the digest, and given a held draft.
- **Junk is offered once per pass as an exact archive list.** Archiving needs the owner's yes and goes through one exact action per thread. It never deletes or labels.

Onboarding to a first win (#155, #169):

- **A new owner's setup asks four essentials:** name, quiet hours and timezone; voice; the never-without-my-yes rules; and the first two errands.
- **One review and apply follows, then errand 1 is finished in the same chat,** for example the triaged inbox itself.
- **Later setup never re-asks these answers,** and existing owners keep today's flow.

Lab:

- **The judge** grounds amounts listed under one currency label (#141).
- **The mail stand-in** reads mailbox scope operators as the seeded inbox (#142).
- **New scenarios:**
  - s33, invoice reminders and the chase ladder (#143);
  - s34, meeting minutes (#149, #164);
  - s35, onboarding to a first win (#169);
  - s36, read-but-unanswered inbox and the junk offer (#168).
- **Roadmap and vision** take in the gap review (#162).

## 0.13.0-rc.1 — 2026-11-09

This release starts M6 (VA parity) with finance admin, customer and vendor replies, and contact list cleanup. PA records invoices the owner issues or receives and chases overdue ones on the existing day 2, 5 and 10 ladder. It keeps owner-stated balances and gives a weekly cash position and a monthly income and expense summary. It answers customer and vendor email under the owner's written policies, and cleans a contact export into an importable file with a change log. It never connects to a bank, never pays, and never sends without the owner's yes.

It ships `releases/0.13.0-rc.1/scorecard.md`, built from 63 Capability Lab runs (21 scenarios, 3 runs each) pinned to the reviewed commit: real Hermes v0.22.2 and `gpt-6.1-sol`, with real web pages for the trip and research scenarios and stand-in providers for the after-the-yes and office ones. 57 of 63 runs pass (54 of 57 in 0.12.0-rc.1). No run booked, paid or submitted anything (zero tripwire hits), and no run claimed a confirmation it did not have.

- **18 of 21 scenarios pass 3 of 3,** among them:
  - general research (s18), up from 2 of 3;
  - Seoul-to-Tokyo and Tokyo-to-Seoul travel prep;
  - the trip-expense list (s30), in its first wave;
  - the after-the-yes, inbox, calendar, follow-through, radar and routine scenarios.
- **San Francisco travel prep (s03) passes 0 of 3, but the lab, not the agent, is at fault.**
  - All deterministic checks pass in every run. The judge failed each run on a restaurant course price or cancellation fee it could not find in the evidence it was given.
  - The restaurant's page does state them ("YUKI 5800", "On the day: 8000" under "Cancellation fee (Yen/per person)").
  - The judge's evidence matcher required the currency sign right next to the number, so it never passed those lines on. A fix follows this release.
- **Replies under the owner's policy (s31, new) pass 2 of 3.** One run escalated a vendor's missing date, because the sample policy read as if any unclear commitment must go to the owner. #137 rewrote the policy wording and the skill after the wave. The judge also flagged that run for widening a mail search past the threads it was asked about.
- **The end-of-day note (s22) passes 1 of 3.**
  - All three runs reported the unclaimed morning brief correctly.
  - Two listed it as a note item under the health finding's id, and the check accepted only ledger rows.
  - #139 fixed the check and the skill after the wave.

Contact cleanup (#138), #135, #137 and #139 merged after the reviewed commit, so this wave does not measure them. A lab check of s31, s32 and s22 on main follows this release.

Invoices (M6-a, #125):

- **`pa invoice`** records an invoice the owner issued (receivable) or received (payable), and can mark it paid, void it, or list invoices. Re-recording the same money facts is idempotent. A different amount, currency or date for the same invoice reference is refused, even after a void; a corrected invoice goes in under its own reference, and the old one can be voided.
- **Receivables:**
  - a courtesy reminder on the radar before the due date;
  - from the due date, a `waiting_on_them` loop that the chase ladder takes on days 2, 5 and 10, then escalates;
  - nudges stay drafts until the owner's yes.
- **Payables:** a pay-by deadline on the radar. Marking one paid records what the owner reports; PA never pays.
- Card numbers, IBANs and long digit runs are refused in invoice fields.

Cash position and monthly summary (M6-a part 2, #129):

- **`pa finance balance`** records a balance the owner states or shows: account label, date, amount and currency. A correction keeps the old figures.
- **`pa finance cash_position`** shows, per currency:
  - the latest balance per account and its age;
  - open receivables and payables, split into overdue and due within 7 days;
  - the last 7 days of spend;
  - a 7-day projection, labelled as a projection.

  Stale or missing balances are listed as gaps. There is no currency conversion.
- **`pa finance monthly`** shows income, bills paid, expenses by category and net for one month. It lists possible duplicates without merging them, and can export a spreadsheet-safe CSV and Markdown file.
- The `finance-admin` skill adds the weekly cash position (Fridays, inside the brief) and the monthly summary (first working day).

Customer and vendor replies under written policy (M6-b, #132):

- A reply policy is an owner SOP whose trigger describes a kind of customer or vendor message. Before drafting to a customer or vendor, PA reads the owner's SOPs and picks the matching one.
- **In policy:** the draft offers only what the policy allows, and the thread is tracked with the policy it used.
- **Out of policy** (no match, over a limit, a legal threat, a change to price or terms): no committing draft. When the policy allows no holding note, PA saves no draft at all. The owner gets a decision packet with the problem, 2 or 3 options, a recommendation and a deadline.
- **Vendor timelines** are chased under policy and tracked until the vendor gives a date.
- PA never promises a refund, discount, credit, date, price or term the policy does not allow, and never admits fault.

Vendor chases waiting for the owner's send approval (#137): while a chase draft waits for the owner's yes, the vendor row stays `waiting_on_them`, with `waiting_for: "owner send approval"`. That holds the chase ladder, and the thread is reported as drafted. A missing date is what the chase asks for, not a reason to escalate. A second missed promised date, a legal threat or a chargeback still goes to the owner.

Contact list cleanup (M6-c, #138): `pa contacts dedupe` cleans a CSV export the owner saves under the profile's `imports/` folder. A read-only Google export through the profile's own Google access works too.

- Rows that share an email or a phone number are merged into one contact, and the change log says which row each kept value came from.
- Rows that share a phone or email under names that don't fit together (Alice Smith and Bob Jones on one switchboard or info@ address) are kept apart and listed for the owner. A shorter form of the same name (Alice and Alice Smith) still merges, so the owner reviews the change log before importing.
- Same-name contacts with nothing else in common are listed as possible duplicates, never merged.
- A display name such as "Mom" is kept, and so are the given and family names, each in its own column.
- Emails are lower-cased and checked; invalid ones are kept and listed. Phone numbers are normalised, with the owner's country code only when the owner gives it, and an extension stays an extension.
- The output is a clean CSV plus a change log in CSV and Markdown, private to the profile and safe to open in a spreadsheet. The source file is never changed, and nothing is written back to Google Contacts or a CRM.

This is covered by unit tests, including a 300-row synthetic export with an independently computed key. Its lab scenario (s32) runs after this release.

Reports state only what the kept evidence shows (#128): before any report or approval packet, each price, fare, fee, billing term, open slot and "in cart" state must match a page or tool result kept in that turn. A search time is not an open slot, a menu is not a cart, and a price tier is not an amount.

Lab fixes (#131, #133, #135, #139):

- The research check now gives the judge every tied source window and the sources cited on the same line.
- The judge sees cart controls ahead of long FAQ lists.
- Scenario step skills under the personal-assistant umbrella load correctly.
- The real-web trip scenarios move two weeks forward, because late-November Tokyo hotel prices had drifted past the scenarios' caps.
- The end-of-day check accepts a routine-health finding listed as a note item when its id comes from that turn's health read; the skill says to use the finding's occurrence id.

## 0.12.0-rc.1 — 2026-11-09

It ships `releases/0.12.0-rc.1/scorecard.md`, built from 57 Capability Lab runs (19 scenarios, 3 runs each) pinned to the reviewed commit: real Hermes v0.22.2 and `gpt-6.1-sol`, with real web pages for the trip and research scenarios and stand-in providers for the after-the-yes ones. 54 of 57 runs pass, up from 40 of 48 in 0.11.0. The three new after-the-yes scenarios pass 3 of 3 each: a booking after the owner's yes (s27), a garage appointment plus a landlord request (s28), and a cancelled leg that breaks a dinner (s29). Follow-through chasing (s20), the end-of-day note (s22), the weekly routine (s16) and calendar invites (s25), which each missed at least once in 0.11.0, now pass 3 of 3. So do inbox triage (s24), the personal radar (s21), the broken-routine catch (s23), meeting confirmations (s26), calendar conflicts (s19) and the daily, quiet-day and kickoff routines. Travel prep passes 7 of 9: Seoul-to-Tokyo and Tokyo-to-Seoul 3 of 3 each, San Francisco 1 of 3. One San Francisco run said dinner was staged in a delivery cart and that a 19:00 table was open, when the pages it kept showed neither; another quoted an Uber fare it kept no evidence for. General research (s18) passes 2 of 3: one run said a provider's price was billed monthly when the cited page says annually, so the scorecard reads research as fail where 0.11.0 read pass. No area reaches parity yet. The trip-expense scenario (s30) merged after the reviewed commit and is not in this wave; the scorecard tool, taken from main, already lists it as not run. No run booked, paid or submitted anything (zero tripwire hits), and no run claimed a confirmation it did not have.

This release finishes the steps after the owner says yes (roadmap M5, in part). A booking lands on the itinerary with its reminders and a calendar file in the same turn. A request sent to a vendor becomes a reply PA chases. Each booking can carry its cost, and the owner's receipts become an expense list that exports to a spreadsheet. When a flight is cancelled or delayed, PA lists what it breaks, brings two or three options in one message, and after the owner's pick replaces the old booking with the new one. A yes given in a different chat session still goes through exactly once. Lab scenarios against stand-in providers prove the booking, the vendor chase and the cancelled leg (s27, s28, s29). Expenses, a delayed flight and the yes across sessions have unit tests; the expense lab scenario (s30) merged after the reviewed commit. No real booking has been completed yet.

After the yes (M5-a, #107, #108):

- **Bookkeeping from the readback.** `pa action_result` with outcome `confirmed` takes `follow_through`. In the same call, right after the result is recorded, it does the following (if the call is interrupted, re-recording the readback finishes it; see Retries):
  - records the booked item on its trip, with the provider readback as its source;
  - sets up to three reminders, such as leave-by, check-in or the cancellation deadline;
  - writes a single-event ICS file in the profile.
- **Calendar.** PA writes to the calendar only when the owner granted calendar write in setup and the daily-ops config is valid. Otherwise the owner gets the ICS file and is told the booking is not on their calendar yet.
- **What stays private.** Booking references stay out of shared trip exports; only the booking's own ICS carries them.
- **Moved bookings.** A moved booking refreshes its trip entry. Attempted transactions are never paused by it.
- **Retries.** Re-recording a confirmed readback refreshes the bookkeeping without replaying the provider call. A reminder the owner already handled stays handled.

Vendor requests and errands (M5-b, #114):

- **Replies get chased.** After a verified send of a vendor request (a landlord, a garage, a florist), `follow_through.loop` opens a `waiting_on_them` loop in the same write. The day 2, 5 and 10 chase ladder then takes it, with nudges held for the owner's yes as before. A vendor's promised reply date holds the ladder until then.
- **Appointments, deliveries and errands** are item kinds. They land with reminders and an ICS file like any booking.

Expenses (M5-c, #119):

- **Every confirmed booking can carry its cost.** `follow_through.expense` writes one expense row for the booking in the same write. Amounts are exact decimals with an ISO currency, as a charge or a refund, in a fixed category list. There is no currency conversion.
- **Receipts the owner sends.** `pa expense` records, voids, lists and exports expenses. Exports are CSV and Markdown files in the profile's `exports/expenses`, safe to open in a spreadsheet, and they flag possible duplicates. A receipt is keyed by its evidence: sending the same receipt twice records it once, and a different amount for the same receipt is refused.
- **Voided stays voided.** A re-record of a voided expense brings it back only when the money (amount, currency, charge or refund) is the same. A receipt also has to match on date, and on merchant when both copies name one.

Changed or cancelled flights (M5-d, #118, #121):

- **What a changed leg breaks.** `pa trip_watch_plan action=disruption` is a read-only view of a trip. It lists each changed leg and the bookings that leg puts at risk, with feasibility and the booking's pending reminders. A changed leg is cancelled, diverted, delayed by 45 minutes or more, or moved by 45 minutes or more against the saved schedule.
- **Connections.** A delayed inbound leg that lands after the onward leg's departure marks a missed connection, using the onward estimate when there is one. A cancelled or diverted inbound leg to the next leg's origin does the same when the onward leg leaves within a day and does not return to where the trip started. Bookings after the missed connection are listed too.
- **Options, then one change per item.** The travel skills turn that view into one packet of 2 or 3 options. After the owner picks, each change is its own governed exact action.
- **Replacing a booking.** `follow_through.replaces` retires the old booking in the same write as the new one's readback. It removes the old trip entry, cancels the old booking's pending reminders and links the old booking to its replacement. Actions derived from the old entry are invalidated, and a replaced booking cannot come back by re-recording its readback.

Reminder timing (#119): the booking skills set leave-by from the readback's start minus the travel time, and for a flight or train also check-in and boarding. When a time is unknown, the skill uses a stated assumption and says so. Booking facts come only from the readback.

Approvals across sessions (#110, #112):

- **A yes in another session counts once.** When the owner's yes arrives in a different Hermes session or task from the one that prepared the action, the confirmation moves the approval to the confirming session. The provider call there is claimed exactly once, and the old session can no longer use it. Before this fix, the call went through unclaimed and its readback was refused.

Lab (#109, #111, #115, #120, #122):

- **s27, a stand-in booking after the yes.** The scenario checks a hold until the item-specific yes, the approval packet, a prepared exact action, one submit under the owner's name, the readback, the recorded follow-through, a distinct leave-by reminder and an honest report.
- **s28.** An appointment and a landlord request in one yes, ending with the reply chased as a loop.
- **Lab check fixes from the 0.11.0 wave (#105).** s20 reads the agent's first loop read. s22 extras must be real, finished rows with evidence. s25 local times get a clean failure and a zone label.
- **s29, a cancelled leg that breaks a dinner (#122).** One options packet with nothing changed; then, after the owner's pick, two governed exact actions, one flight rebook and one dinner move, both read back, the old dinner retired with its reminders and the ICS file offered honestly.
- **s16 check fix (#120).** The weekly routine check accepts the outcome labels honest runs actually wrote.

## 0.11.0 — 2026-11-09

It ships `releases/0.11.0/scorecard.md`, built from 48 Capability Lab runs (16 scenarios, 3 runs each) pinned to the reviewed commit: real Hermes v0.22.2, real web pages, `gpt-6.1-sol`. 40 of 48 runs pass. Inbox triage (s24), the personal radar (s21), the broken-routine catch (s23), meeting confirmations (s26), calendar conflicts (s19), general research (s18) and the daily, quiet-day and kickoff routines pass 3 of 3 each. Follow-through chasing (s20) and the end-of-day note (s22) pass 2 of 3. In the s20 miss the run claimed the right chase steps, but the check reads only the agent's last loop read, taken after the chase steps were recorded, when no step was due any more (a check gap, #105). In the s22 miss the note listed an extra item that was not one of the tasks. The weekly routine passes 2 of 3 (one reply did not offer calendar setup outright). Calendar invites pass 1 of 3: every run had the right times and the judge passed all three, but the lab contract does not fix the format of participant local times, so two runs wrote formats the check cannot read (#105). Travel prep passes 6 of 9: the Tokyo-to-Seoul trip 3 of 3, Seoul-to-Tokyo 2 of 3 and San Francisco 1 of 3; two runs gave a restaurant the price range of a different restaurant, and one left a step without a final page or hand-off. No area reaches parity yet. No run booked, paid or submitted anything (zero tripwire hits). A first wave on the pre-release commit found that the new rule to record every owner ask as a loop also opened a second tracker for Chief of Staff recommendations, so daily and kickoff fell to 1 of 3; #104 fixed that before this wave, with radar lead times, end-of-day grounding and lab checks that wrongly failed honest runs.

This release closes loops (roadmap M3, #49 and #50) and adds inbox triage and calendar writes (M4, #51 and #52). Both milestones landed together, so 0.11.0 carries both; ROADMAP.md moves M4 from 0.12.0 to this release.

Follow-through (M3):

- **Open loops (#49).** Commitment actions can carry a loop: who owes what (`loop_kind`: ask_owner, delegated, our_promise, waiting_on_them), the counterparty, who acts next, the next step and when to chase. `pa next_action` with `loops_only` lists them with the chase step due today.
  - The chase ladder is day 2, 5 and 10, then an escalation from day 11, counted on the owner's calendar.
  - A loop closes only with a confirmation (who, when, evidence) or the owner's cancellation. A Kanban task marked done without one stays listed as `done_unconfirmed`.
  - Nudges are drafts. PA's code never sends; the agent sends only after the owner's yes. While a nudge is in flight, its loop waits: no second nudge and no wake for the loop's own deadline.
  - A loop promoted to a transaction keeps its transaction step; a live transaction blocks closure. The owner can withdraw a loop whose step was only prepared, and a withdrawn step cannot be confirmed or submitted until it is prepared again (#92).
- **Follow-through skill.** The new `personal-assistant:follow-through` skill runs the ladder and writes an escalation as a short decision packet: the problem, two or three options, a recommendation and a decision deadline.
- **Personal radar.** `pa next_action` with `radar` lists renewals, important dates and deadlines when they come within their lead time (defaults 30, 14 and 7 days; the owner can set a longer lead, for example for a passport). Month-only dates such as `2027-03` are accepted.
- **Chase wakes.** A due chase step wakes the due-source check once per step, including a loop marked done without the other side's confirmation, so the agent asks for it. A loop held by a snooze, a wait, a transaction state or an in-flight nudge does not wake; an open loop with its own deadline wakes for it.
- **Every brief lists open loops and due items (#101).** A source that cannot be read is reported in one line, never instead of the loops.
- **Reporting norms (#50).** `skills/personal-assistant/references/reporting.md`: at most one corrected retry after a tool_call error, exceptions reported in the same turn (unattended ones wait out quiet hours unless the owner allowed them), a four-field escalation packet, progress notes on long tasks, and a pre-send check.
- **End-of-day note.** A second slot on the existing daily-brief job runs after `eod_time` (default 18:00) as Done / In progress / Blocked with questions. An evening brief (one set after `eod_time`) replaces it.
- **Routine health.** `pa automations action=health` reports claims with no receipt after 60 minutes, passed slots nobody claimed and recorded precheck failures. The other routine wakes once for a new finding; health never changes jobs. An accepted job whose prompt, delivery or skills drifted from the current spec reports `job_outdated` with a remove-and-re-suggest step.
- **Scheduled receipts** are recorded as `unknown` (handed to Hermes cron delivery), never `delivered`.
- **Canary exporter.** `scripts/export_canary.py` scores the 10-working-day M3 canary; missing data reads unproven.

Inbox and calendar (M4):

- **Inbox triage (R6).** Twice a day, in the existing morning brief and evening register, PA sorts mail into urgent, needs you, handled, FYI and junk, and sends a digest of five lines or fewer that names every urgent item and every decision. Each urgent or needs-you thread is tracked as a loop until a reply goes out or a decision is recorded.
  - Drafts follow the owner's voice and person rules. Nothing is sent, archived, deleted or relabelled without the owner's yes; junk is only reported.
  - A failed mail read shows as a failure, never as an empty inbox.
- **Calendar writes and invites (R4).** Writes keep the owner's buffers and focus blocks, and every time carries its time zone. The approval packet lists the attendees and says whether guests are notified; PA reads the event back before saying anyone was invited. Find-a-time proposes 2 or 3 slots labelled in every participant's local time and flags daylight-saving weeks.
- **24-hour confirmations.** The evening register lists tomorrow's meetings (`meetings_to_confirm`); R4 prepares a one-page brief and a confirmation draft for each, sent only after a yes.
- **Write access is the owner's choice.** Daily Ops stays read-only unless the owner opts in during setup (`inbox.drafts.accepted`, `calendar.write_scope`); broader Google scopes are always refused.
- **Setup asks five more questions** (32 in all): inbox habits, draft and send rights, calendar write rights, life dates for the radar, and chase style.

Approvals and routines in practice (found in live runs):

- **Governed exact actions (#97).** The skill gives the full `action_prepare` envelope for an exact action, and a rejected envelope names the missing keys. After the owner's yes, the gateway lets that one sealed call through once and blocks nothing else; a changed request needs a new `action_revision`.
- **Turning on a routine.** The R5 skill gives the steps: the rule with the `origin` destination and its own kind, a native suggestion, and the returned `accept_command` the owner sends.

Lab (#93): seven new scenarios, s20-s26, cover loops, the radar, inbox triage, calendar writes and confirmations against local mail and calendar stand-ins, with checks grounded on evidence.

## 0.10.0 — 2026-11-08

The Hermes plugin catalog release. It contains 0.10.0-rc.1 below plus the catalog review fixes (NousResearch/hermes-agent#150855, #86) and three catalog screenshots (#88). It ships `releases/0.10.0/scorecard.md`, built from 27 Capability Lab runs pinned to the reviewed commit (real Hermes v0.22.2, real web pages, `gpt-6.1-sol`). General research now passes its lab test, 3 of 3 runs (1 of 3 in rc.1). Calendar (s19) and the daily, quiet-day and kickoff routines pass their partial checks in 3 of 3 runs each. The weekly routine passed the judge in all 3 runs but missed a fixed check in each: in two, the check's wording was too narrow (the agent wrote that the calendar is "disconnected", which the check does not yet accept), and in one, the reply did not keep its outcomes separate. Travel prep passes 6 of 9 runs: the Seoul and Tokyo trips pass 3 of 3, and the San Francisco trip fails 3 of 3, where the judge found a food cart and a restaurant price the evidence did not show, and one run left the taxi without a hand-off. No area reaches parity yet. No run booked, paid or submitted anything (zero tripwire hits).

Catalog review fixes:

- **Calendar sync removed.** The `calendar_bind` and `calendar_sync` operations are gone, with PA's Google Calendar client. PA no longer reads or refreshes the profile's `google_token.json`. The agent writes calendars with the profile's own calendar tools. Daily Ops reads them only through `gog`; the `profile_google` provider and `include_pa_binding` are refused with a clear error.
- **`trip_import` takes content, not paths.** Pass the calendar file's text in `ics_text` (and a guide in `guide_text`), read first with `read_file`. `ics_path` and `guide_path` are refused.
- **Updates go through Hermes.** `scripts/reinstall_pinned.py` is removed. Catalog installs update with `hermes plugins update personal-assistant`; a direct pinned Git install moves with `hermes plugins install <source> --force --ref <sha>`.
- **Per-profile ledger.** `register()` binds the ledger with `hermes_constants.get_hermes_home()` instead of `HERMES_HOME` and the plugin manager's private attribute.
- **No saved-login reads.** Eval and lab scripts take the model token from `PA_EVAL_CODEX_TOKEN`, set by the caller. The phone poll reads the declared `ELEVENLABS_API_KEY` through Hermes's secret accessor.
- **Pin moves keep your settings only if you copy them.** Some Hermes versions replace the whole plugin folder on `hermes plugins install --force`. `scripts/check_release.py` now returns `before_command`, which names PA's four local configuration files to copy out and back; Hermes 0.23.0 catalog updates carry them across (#86).
- **Daily Ops setup.** The skill gives the exact read-only `gog auth add` commands the doctor accepts, and runs the doctor after authorisation (#86).

## 0.10.0-rc.1 — 2026-11-08

The first measured release (roadmap M2, #48). It ships `releases/0.10.0-rc.1/scorecard.md`, built from Capability Lab runs pinned to this release's reviewed commit: real Hermes v0.22.2, real web pages through Browserbase, and `gpt-6.1-sol`. Four areas were exercised, 27 runs in all. Calendar (s19) and recurring routines (the daily, quiet-day, weekly and kickoff routines) pass their partial checks in 3 of 3 runs each. Travel prep passes 8 of 9 runs; in the ninth, the judge found a "prepared" food-order cart and a restaurant price range that the evidence did not show, so travel's partial check reads fail. General research fails its lab test: 1 of 3 runs passed and 2 failed. Every run passed the fixed checks, with no price missing from its cited page; the judge found an annual price described as monthly billing in one run, and a unit it could not see in its source excerpt in another. No area reaches parity yet: real-work and day-30 evidence come from the pilot owner's recorded tasks, and ten areas have no lab scenario yet. No run booked, paid or submitted anything (zero tripwire hits).

- **General research (#70, #81, #83, #84).** A new research lab scenario (s18) asks PA to compare real providers on the live web. The `research` skill now:
  - asks the owner's top priority first when the answer is a choice, and takes lowest total cost if they have none;
  - writes six fixed headings: Question, Criteria, Recommendation, Comparison, Could not find, Appendix;
  - cites each sourced amount with its own `[n]` right after it, one per amount even inside a table cell, and dates each source on its own line;
  - names each fee in the page's own words without widening its terms (an annual price is not monthly billing; a one-time fee is not per entity unless the page says so);
  - gives prices as the pages print them and compares cost in words, leaving the all-in total to a written quote.
- **Calendar (#78, #80).** A new calendar lab scenario (s19) checks clashes across three time zones, one valid new slot, and a protected focus block left in place.
- **Lab scoring (#70, #78, #80, #82).** Offline research and calendar checks score each run. The judge sees the source passage behind each claim, not the first match on the page. JSONL files with Unicode line separators now load.
- **`/pa status` (#75, #76).** No empty segment before setup progress; the calendar visibility note is precise.

## 0.9.0 — 2026-11-08

The first stable GitHub release of this repository. It contains every change in the 0.4.0 to 0.9.0 release candidates below, plus the first part of roadmap M2, "Measured" (#48): the tools that will measure PA against the VA bar.

- **Real tasks become evidence (#67).** A new `evidence` operation (`pa(operation="evidence")`) records real owner tasks: area, title, start and due dates, outcome, the owner's acceptance, corrections and fact checks. It also records the owner's baseline week of minutes by task type and the day-30 answer: minutes now, and the task types the agent gets right first time.
  - Closing a task needs `closed_on`, the owner's local date, so a pass is never counted on time by mistake east of UTC.
  - Free text goes through the existing private-data check: card numbers and secrets are refused, ordinary URLs are accepted.
  - Evidence rows stay out of action lists and the ledger summary. `scripts/export_va_evidence.py` exports them, read-only, for the scorecard.
  - The `personal-assistant` skill says when to record a real task and the baseline. Once an evidence task is 28 or more days old, the agent asks the day-30 time question at most once a week until it is answered: in the weekly closeout, or in the daily brief when Chief of Staff mode is off. The trust review no longer asks it.
- **VA scorecard builder (#64, #67).** `python -m evals.scorecard` reads Capability Lab runs and exported evidence and writes `scorecard.json` and `scorecard.md` for one release commit. It covers the 12 VA bar areas plus onboarding and working norms. Each area reads pass, fail or unproven on four conditions: lab, real work, facts and day-30. An area cannot pass until every duty has a passing lab test, and a failed condition still reads fail. Missing evidence is unproven, never a pass, and the headline has no parity percentage. A run counts only when PA's installed ref is the release commit. It reports and does not gate.
- **Release rules (#66, #69).** From 0.10.0, every release must ship its measured scorecard for the exact reviewed commit. Release notes drop HTML comments, and CodeRabbit no longer writes its summary into PR bodies.
- **Hermes floor declared.** `plugin.yaml` now declares `requires_hermes: ">=0.21.1"`, the oldest Hermes that CI runs PA on. An install from the Hermes plugin catalog refuses an older Hermes. Hermes versions that predate the check ignore the field, so a Git install on them loads PA without a warning. The Python dependency ranges were already bounded.
- **Upgrade note: switch pilot hosts to the stable channel.** `scripts/check_release.py --channel pilot` lists only prereleases, so on 0.9.0 it offers 0.9.0-rc.2, which is older. Use `--channel stable` (the default).

## 0.9.0-rc.2 — 2026-10-21

- **Stated preferences reach owner memory (#62, #47).** When an owner message looks like a lasting preference, a correction or a rule about a person ("from now on…", "always…", "correction:…"), PA adds a short routing note. The note tells the agent to record the message with the `profile` operation rather than Hermes' memory tool. The agent judges whether the message really is one. During an active setup interview, setup records the answers itself, so no note is added.
  - Before this, a live model could answer such messages by writing USER.md directly. The preference then had no source, did not retire the one it corrected, and skipped the reviewed filing.
- **Persona rig (#62).** A new `owner_memory` persona checks that a preference, a person rule and a correction are recorded in one session. After `/new`, it checks they are honoured through PA's first-turn note. The rig runs locally, with a loopback gateway.

## 0.9.0-rc.1 — 2026-10-21

Roadmap M1, "Knows you" (#46, #47): the agent interviews the owner, remembers what it learns, and reuses it instead of asking again.

- **"Grill me": a profile interview (#46, #57, #59).** Say "grill me", or send `/pa setup grill` (or `/pa setup profile`). PA interviews you across the eight groups of the VA bar:
  1. the business;
  2. you;
  3. communication;
  4. decision rights and spending limits;
  5. preferences and voice;
  6. calendar rules;
  7. history and worries;
  8. access.

  It needs neither Chief of Staff mode nor `/new`.
  - **Short sittings.** One group per sitting, and each answer is read back. A sitting ends with the usual reviewed proposal and apply. The agent then names the next group and asks "now or later?". You can still skip a question, pause, or say "you decide".
  - **Proof that answers were saved.** Each new sitting starts by reading two saved facts back from your files, or by saying which are missing.
  - **Read before asking.** With your consent, PA first reads USER.md, the manual, the calendar, past itineraries and up to 20 recent sent emails (only through a read path that is already authorised). If you decline, it reads no private sources. What it finds is recorded for all eight groups at once and offered as the recommended answer, so later sittings do not ask it again.
  - **Never re-ask.**
    - `biz_priorities` and the Chief of Staff `cos_priorities` are one fact: answering either covers both.
    - Three profile questions only partly overlap earlier answers: decision rights, channel and response times. For those, the agent states what it already knows and asks only for the missing part.
  - **"Grill me" works in a fresh session.** A routing note on the owner's message starts the interview. The note tells the agent to answer normally when "grill me" means something else, such as challenging a plan or pitch. Common negations ("don't grill me") leave the note out.
  - **A finished profile is not reopened.** "Grill me" on a complete profile says so and points to `/pa setup review`. The agent does not start another section on its own while a review is waiting; it asks you to apply or change the review first. An explicit `/pa setup <section>` command for an available section switches at once: it clears the waiting review, and your saved answers stay.
- **Owner memory (#47, #58).** Corrections, people, SOPs and trust levels are kept in the existing PA ledger. Active preferences and people reach the agent from the next session through a short note, within its limits, with no setup review in between.
  - **Corrections are captured on the spot.** When you correct the agent or state a lasting preference, it records it with its source (said, inferred or corrected) and replies "Noted.". A correction retires the preference it replaces. When you edit and send a draft, the differences are saved as voice preferences.
  - **Inferences wait for your yes.** A pattern seen twice is saved as a proposed preference, and the agent asks to confirm it once, in the next brief or closeout. A confirmed preference is never asked again. An inference never changes a preference you stated, confirmed or filed: the agent asks you instead.
  - **People.** Key contacts are saved with their relationship, preferred channel and up to five rules (for example "never call before 10"). The agent checks those rules before drafting to or about a person. Sensitive contacts are named but never quoted.
  - **SOPs.** After a recurring task first runs, the agent drafts its SOP: trigger, steps, tools, what done looks like, and escalation. Corrections add a version and a changelog line. After two runs without a correction, the SOP becomes `owned`.
  - **Trust levels.**
    - Each task type starts at `shadow`: you see each output before it is used.
    - `own` covers preparation only.
    - `independent` is reserved for later and has no effect.
    - No level grants approval to pay, book, send or cancel.
  - **In force without a file write.** On the first human turn of a session, PA adds a short note when there is something to list: at most 10 rows and 1,200 characters of active preferences and people not yet written into USER.md or the manual. A rule that does not fit is left out whole, never cut, and the note says more is waiting. Proposed inferences are not in it; SOPs and trust levels are looked up with the `profile` operation. Cron, HeartBeat 2.0 wakes and subagents never get the note.
  - **Filing happens only after a review.** At `/pa setup review` or the weekly closeout, these are proposed as normal reviewed writes. A filed fact that you later make the agent forget, or that a correction replaces, is listed for removal from the files at the same review, even if it changed after filing: PA keeps the text the files hold until the review replaces or removes it. Until then, the note marks it "FORGOTTEN, do not use" (within the note's limits). Forgetting retires a record; nothing is deleted.
  - **Day-30 review.** Once the oldest active trust record is 30 days old, the next weekly closeout reviews task types and levels once and asks: "Is this saving you time? Roughly how much?". When Chief of Staff mode is off, the daily brief asks this once instead. Trust levels change only after your answer.
  - **Prohibited content.** Recognised credentials (labelled keys, tokens and passwords, and common key prefixes), card numbers (by Luhn check, so ordinary phone numbers are accepted) and labelled account numbers are refused. Passport numbers are refused through the existing privacy filter. There are no fields for raw message bodies, values are length-capped, and the skill rules forbid storing raw message bodies and require safe paraphrases.
- **Setup status per section (#57).** `/pa setup status` (or `/pa status`) shows each started section, with skipped questions counted and shown. For example: "Core 8 of 8 · Chief of Staff 6 of 6 · Profile 4 of 27 (next: you)".
- **Two pilot faults fixed (#57).**
  - Bare `/pa setup` after an applied setup no longer restarts the core section. With the quick check still pending, it says the setup is saved and asks for `/new` and then any message. With core complete, it shows a menu of the other sections.
  - A pending quick check from core or Chief of Staff setup survives a later profile sitting.
- **Vision and roadmap (#45).** `VISION.md` sets the goal: a remote assistant at the level of a top-rated human VA, then a remote Chief of Staff. `docs/vision/` defines the bar for each. `ROADMAP.md` orders the work from here to VA parity (1.0) and Chief of Staff (2.0). Documentation only.
- **Upgrade notes.**
  - **New operation.** There is a new `profile` operation. Nothing runs on install, and existing setup answers are kept.
  - **Reserved action records.** Generic `action_upsert` now refuses the four profile record types (`preference`, `person`, `sop`, `trust`) and their identity prefixes (`pref:`, `person:`, `sop:`, `trust:`); transaction operations refuse those prefixes. Profile records do not appear in action status lists or the ledger summary; use the `profile` operation.
  - **Hermes title matching.** The rc.3 note cited NousResearch/hermes-agent#142364 for Hermes matching a routine's title to an older record of the same name. That issue is closed in favour of the open upstream fix, NousResearch/hermes-agent#129597.

## 0.8.0-rc.3 — 2026-10-21

- **Phone calls, phase 1 (#27, tracked in #30).** Nothing dials yet: a live ElevenLabs `start` returns `not_activated`, and `check_with_owner` is not available. Details: `docs/phone-calls-phase-1.md`.
  - `pa_call` can compile a prepared call card into a brief for ElevenLabs' hosted voice agent. The brief has a fixed AI-disclosure first line, the facts PA may share, and the allowed party-size and time ranges. It also has hard stops for payment, deposits, cards, cancellations and personal data ("I'll confirm and call you back"). Compiling reads the card and changes nothing.
  - A poller you run yourself, `python -m personal_assistant.phone_poll`, collects finished ElevenLabs conversations into the owner's PA queue as `phone_call` packets: the transcript plus the provider's outcome summary, with recognised card numbers (13–19-digit card patterns) removed; the doc lists what it does not catch. It previews by default and writes only with `--enqueue`.
- **Delivered packets can no longer forge their frame (#41).** A `<` inside untrusted mail, speech or fact text is escaped in packets that reach the conversation, so text such as `</pa_packet_v1>` cannot close or fake the frame.
- **Guidance from the live pilot (#42):**
  - Calls through Hermes' `tool_call` send `calls` as a native array. A "'calls' is not valid JSON" error now reads as "PA was not reached", not as a ledger failure.
  - A restaurant stop, including a form the user said not to book yet, saves a checkpoint, so a later yes resumes from it.
  - In Korea, CATCHTABLE Global comes first for users without a Korean phone.
  - After setup, the agent asks for `/new` and then any message, never `/pa setup`.
  - The manual's description stays within 60 characters.
- **Routine suggestions say what really happened (#43).** `pa automations suggest` now marks each routine from your accepted schedules as suggested, already running, already pending, accepted or dismissed earlier, or dropped because Hermes' backlog of pending suggestions is full (5). If it is full, the agent asks you to accept or dismiss some in `/suggestions` and run suggest again; before, the routine silently went missing. Each suggested routine comes with an exact accept command, `/suggestions accept <id>`. Hermes can match a title to an older record of the same name (NousResearch/hermes-agent#142364). After Chief of Staff is turned off and on and its schedules are set up again (`/pa setup chief-of-staff`), its routines are offered again. A routine you dismissed, or accepted and then deleted, is offered again when you say you want it. Daily routines say that, if today's slot has already passed, the first run comes within minutes of accepting.
- **`pa capabilities` sees the `gog` CLI (#43).** When `gog` is on PATH (or `GOG_PATH` names an executable), mail and calendar list it first, with account access still to be checked by one read-only call; PA never runs it during discovery. With Browserbase keys set but no `agent-browser` on PATH, the remote browser reports `needs-setup` and says what to install (#39).
- **Setup reviews no longer show retired answers (#43, #38).** The old two-schedule Chief of Staff answer from rc.1 is kept in storage but no longer shown as if it were current consent.
- **Upgrade notes.**
  - **A full suggestion backlog is now reported.** If `/suggestions` already holds Hermes' maximum of 5 pending items, `suggest` names what it could not add. Accept or dismiss some, then run it again.
  - **Routines dismissed by an earlier off-and-on.** If you turned Chief of Staff off and on before rc.3, run `/pa setup chief-of-staff` again (turning it off paused its rules). When the agent reports a routine as dismissed, tell it you want it, and it re-offers the routine with an accept-by-ID command.
  - **Phone phase 1 is opt-in.** It needs the profile's ElevenLabs agent and key (see the doc). Nothing runs on install.

## 0.8.0-rc.2 — 2026-10-21

- Later setup answers keep applied/checked setup intact and flag changes for the next review; fresh checks name the cause when refused (#28).
- Context retrieval infers trip, action or source from one unambiguous ID; guide queries still need an explicit kind.
- Guided setup now runs only in the chat where it is active. Other chats of the same user get one short first-turn line, and `/pa setup` continues setup in the current chat, keeping its section, answers and any pending proposal. A setup bound by an earlier release is active in no chat until the next `/pa setup` (#29).
- **Chief of Staff weekly kickoff and closeout (#26).** A new `cos_kickoff` schedule and `cos-kickoff` skill start the week (default Monday 11:00 local) with exactly one focus set against your saved priorities, or stay silent when nothing is new. The kickoff reads the last weekly closeout, which the precheck names as `last_closeout_note`; if none was recorded, it says so and infers nothing. Accept it with `/suggestions accept personal-assistant-cos-kickoff`, with its own explicit yes. A missed kickoff catches up later in its week, but never after the closeout that follows it. Turning Chief of Staff off removes it with the other CoS jobs.
  - `cos_weekly` is now called the **weekly closeout** everywhere you read it. Its rule kind, job name `personal-assistant-cos-weekly`, skill name and precheck script keep their names, so accepted jobs keep working; the closeout's instructions and precheck fields change. The closeout also records `carry_over` (open loops, decisions still needed) for the next kickoff. Radar stays in the closeout.
  - `/pa setup chief-of-staff` now asks six questions: the kickoff slot comes before the closeout slot, and each schedule needs its own yes. Setup lists Hermes jobs first; for a hand-made kickoff or closeout job it asks whether to keep it (no matching PA rule) or replace it (you remove it in Hermes first). Setup never removes one itself; turning Chief of Staff off removes any job named exactly like a PA CoS job (`personal-assistant-cos-daily`, `-kickoff`, `-weekly`). An answer to the earlier two-schedule question is not reused: the three-schedule question is asked again. The kickoff and closeout cannot share a day and time.
  - **Migration:** the closeout default moves from Monday 10:00 to Friday 15:00. Profiles that accepted the weekly job without saving a slot move from Monday 10:00 to Friday 15:00. To keep Monday, save `cos_weekly_day` `mon` and `cos_weekly_time` `10:00`. The week of the upgrade still gets at most one closeout.
  - Capability Lab scenario s17 covers a kickoff that reads last week's closeout. Lab only; no lab wave has run yet.
- The Browserbase lane no longer needs the key in a shell, which current Hermes withholds: the new `browser_session` operation creates, re-links and releases a session in-process through Hermes' secret scope. The checkout skills attach with `agent-browser … connect` and send the live view at card, OTP, passport or CAPTCHA steps (the link of the right tab when a step opens a new one); the final pay/book/reserve tap is the user's own. `connect` reattaches a running session after a lost connection. PA re-links, reattaches or releases only sessions it created, and the Browserbase endpoint is fixed. Recording, logging and CAPTCHA solving are off (#25).
- **Upgrade notes.**
  - **Weekly closeout moves to Friday 15:00.** Without a saved slot, the weekly closeout (formerly the weekly review) moves from Monday 10:00 to Friday 15:00. To keep Monday, save `cos_weekly_day` `mon` and `cos_weekly_time` `10:00`. The week of the upgrade still gets at most one closeout.
  - **A hand-made kickoff or closeout job with its own name keeps running beside PA's**, and PA leaves it alone. If you also accept PA's job of the same kind, keep only one. (A job named exactly like PA's, such as `personal-assistant-cos-kickoff`, blocks PA's suggestion and is removed when Chief of Staff is turned off.)
  - **The weekly kickoff is new and off until you choose it.** In the topic that should receive it, run `/pa setup chief-of-staff` and answer the kickoff question. Then review and apply, and accept `personal-assistant-cos-kickoff` there. Setup asks the three-schedule question again; an answer to the earlier two-schedule question is not reused.
  - **A guided setup started on an earlier release belongs to no chat after the upgrade.** The first turn of each new session shows one line pointing to `/pa setup`. Say `/pa setup` in the chat where you want to finish; it keeps your answers and any pending proposal.
  - **Browserbase needs the profile's Browserbase key and project id, plus `agent-browser` on the host.** Without them, PA uses the local signed-in browser, which stays the default lane.

## 0.8.0-rc.1 — 2026-10-20

- **Chief of Staff mode (opt-in).** `/pa mode chief-of-staff on|off` turns it on per profile; it is off by default. Turning it off removes the CoS cron jobs and blocks later prechecks at once. Follow-up wakes already armed in HeartBeat 2.0 stay armed, but when one arrives the agent is told to cancel it and stay silent. The CoS skills are hidden after the next gateway restart and new session. While they are still loaded, the agent is told not to use them.
- **Four CoS skills.**
  - `cos-daily`: one useful, evidence-backed next action a day, or silence when nothing clears the bar.
  - `cos-weekly`: a weekly review that keeps used, declined, ignored and unknown outcomes separate.
  - `cos-scout`: adopt-versus-build research for a named need, with an adopt, trial, watch or ignore decision, the smallest trial, and a follow-up date.
  - `cos-radar`: at most one tool benchmark a week; a slot is booked only on a yes, through PA's bound calendar, with a read-back.
  Each recommendation is one stable PA note, updated in place. Follow-ups use an owner-approved HeartBeat 2.0 `at` wake in the same chat; no other scheduler is created.
- **Daily and weekly schedules.** These use the existing native suggestion path. PA suggests `personal-assistant-cos-daily` / `-cos-weekly` only for rules the user accepted for a verified chat, and Hermes `/suggestions accept` creates the job.
  - Five-minute prechecks honour the saved time, the rule's timezone, quiet hours, pause and snooze. PA claims each daily or weekly occurrence once in the profile ledger and never retries an existing claim. This does not guarantee exactly-once chat delivery.
  - The report is the run's final response, which Hermes delivers. Silence is `[SILENT]`.
  - Conflicting rule timezones or chats never wake, and a report time inside quiet hours is refused.
- **Reports go to the chat or Telegram topic where you accept them (#22).** Setup records the destination as `origin`, and Hermes binds it when `/suggestions accept` runs. Accept daily and weekly in different topics to keep them apart; accepting from the CLI or Desktop falls back to a configured home channel, and without one nothing is delivered.
- **CoS setup section.** `/pa setup chief-of-staff` asks five questions (priorities, radar topics, daily time, weekly slot, which schedules), with its own progress, through the same reviewed-write flow as core setup. Schedules need an explicit yes for each one.
- **Daily Ops scheduled jobs reach the user (#21).** The morning brief and evening due-source jobs used local delivery plus an agent send tool that Hermes v0.22.2 does not have, so they could never reach the user. Newly accepted jobs now deliver the run's final response to the verified chat, the same way as CoS. Upgrading does not rewrite a job you already accepted. If you accepted `personal-assistant-daily-brief` or `personal-assistant-due-source-check` on an earlier version, remove it in Hermes, ask the assistant to suggest PA automations again (the `pa` automations `suggest` action), and accept the new suggestion with `/suggestions accept`.
- **Trip concierge fixes from the live pilot (#23).**
  - **Be at the airport vs leave by.** The time shown as "leave by" was really the time to be at the airport. PA now shows "be at the airport by" and gives a leave-by time only once the transfer from where you're staying is known. The agent asks for it once, and it is tied to the departure airport. Daily Ops and alerts never say "LEAVE NOW" without it. Armed wakes carry over unchanged.
  - **Saving flight facts.** A flat single-flight `record_facts` form; flight segments are accepted as a list, a single flight or a JSON string; and skill guidance to send one `pa` call per tool call. A wrapper parse error is no longer reported as the ledger rejecting the flight.
  - **Offer after import.** A trip import or flight-facts save returns a read-only hint to offer the trip watch, and the import skills point to it. The hint stops once the user answers or a plan exists; an unanswered question can come back on a later import.
  - **Night alerts.** With night alerts on, PA recommends HeartBeat's `quiet_hours_urgent` setting (profile-wide, off by default) and explains it. PA never changes it.
  - **Trip-watch status before a plan exists** returns "not planned" instead of an error.
- **Capability Lab.** CoS scenarios s13–s16 cover a daily report, justified silence, a Korean scout and a weekly review with a benchmark yes. They use Hermes's own cron prompt builder and silence matcher. Lab only; not shipped behaviour.
- **Evidence.** CoS wave 2 at `296644e` on `gpt-6.1-sol`, 3 runs per scenario: 12/12 runs pass the deterministic checks and 11/12 pass the judge.
  - Daily report 3/3 and justified silence 3/3, with top judge scores in every run.
  - Korean scout: 3/3 checks, 2/3 judge. The failing run credited a price to the official page that came from a search result.
  - Weekly review: 3/3 checks after two lab checks were corrected to accept equivalent wording (#22); the first score was 1/3, and the product text is unchanged.
  - 0 installs, 0 profile-file writes, 0 unapproved wakes, 0 message-tool calls.
  - Wave 2 predates the #19 quiet-hours and destination-conflict guards. The CoS skills and scheduled job prompts are unchanged since then.
  - Confirmation wave 3 at the release code (`e628aea`), 1 run per scenario: 4/4 runs pass the deterministic checks and 4/4 pass the judge, with 0 installs, 0 profile-file writes, 0 unapproved wakes and 0 message-tool calls.
- **Unchanged.** Install stays inert; no job exists until the user accepts it in Hermes; no software is installed and no profile file is edited without review.

## 0.7.0-rc.1 — 2026-10-19

- **Travel concierge.** Trip watch adds check-in, arrival and watcher arms, saved wake receipts and lost-wake recovery. The observer checks itinerary, flight and weather changes; offers follow each notice, while a decline silences that offer type for the trip. Feasibility shows arrival buffers and alternatives; leave-by feeds Daily Ops, and an accepted leave-earlier offer returns the exact replan call without counting weather twice.
- **Phone calls.** `pa_call` prepares a call card and supports outbound and inbound conversations in Japanese, Korean and English through a loopback simulator. Starting needs confirmation; without a transport, PA gives a script and says nobody was called. The phone-calls and answering-calls skills cover both directions.
- **Japan and Korea providers and language.** Provider tables distinguish web, app-only and partner routes, with login, local-phone and deposit needs or an unverified label. PA replies in the user's language, speaks politely to providers, confirms katakana or Hangul names, and states time zones. Snacks and grocery carts stay within budget, with allergens, substitutions and hotel delivery rules noted; local SMS and human verification go to the user.
- **Skills behaviour.** Approval packets use `action_prepare`, link changes or cancellations to the original booking, and wait for an explicit yes. Every search and stop gets a native ledger note. Rendered snapshots must show a choice as selected before PA says it is; hotel areas and per-night caps are honoured, and prices, fees, flight times and fares are reported only as a page or tool showed them. Missing amounts stay unknown; a ledger note alone is not proof.
- **The Capability Lab.** Evaluation tools run isolated Hermes agents against the real web with a simulated user, stop-before-submit checks and saved page, ledger and call evidence. Browserbase support, rejudging, incomplete-run reporting and fixes to evidence matching, call scoring and handoff detection improve evals only; they are not shipped assistant behaviour.
- **Fixes.** Setup offers count as delivered only when the reply mentions `/pa setup`; failed fresh checks need a new session, and look-around consent is saved. PyYAML is declared and dependency ranges allow Hermes to enable PA. Flight delays are classified correctly, native-plugin imports no longer break offer acknowledgements, and a return from an announced cancellation is reported.
- **Evidence.** Capability Lab wave 5 at `a8a20ba`, scored with the #131 handoff check (the only later change, and lab-only): 12 demo trips × 3 runs on `gpt-6.1-sol` against the real web, stopped before any submit; 31 of 33 runs pass, every capability ≥ 83% (flight 13/15, hotel 16/18, restaurant 16/18, snacks 5/6, taxi 8/9, food 8/9, calls 15/15), 0 submits, 0 fabricated confirmations.
- **Unchanged.** Install stays inert; no real booking, payment or reservation is ever made without the user's explicit yes; real phone lines are not included.

## 0.6.0-rc.1 — 2026-10-19

- **Guided setup.** It is reached with `/pa setup` (also `setup review`, `status`, `help`) or a one-time first-use offer, and its progress is saved durably. A short note is added only on real human turns: never on cron, subagent, HeartBeat 2.0 wake or injected turns.
- **The `pa-setup` skill** runs the interview:
  - an intro, then a look around with consent;
  - eight core questions, one per message, each with a grounded recommendation or a labelled default. Facts discovery already found are shown for confirmation, not asked again;
  - one review with a diff per target, and nothing written before an explicit "apply".
  It writes USER.md through `memory`, a delimited `## Personal Assistant` section of the profile SOUL.md, and an operating-manual skill. PA then reads back and hashes the saved files itself, and a fresh-session check confirms the saved preferences load. Deeper answers are saved as drafts without ending the interview.
- **The first travel-concierge offer** is the new `trip_watch_plan` operation:
  - It computes pre-departure moments, shifting them for PA and HeartBeat 2.0 quiet hours in their own zones and capping at leave-by. It rejects spring-forward wall times.
  - It returns the exact HeartBeat 2.0 `pulse create` arguments for one owner-agreed wake, and records wake receipts per plan revision.
- **`trip_offer`** reserves and records offers, at most once per trip and offer type (any recorded outcome, including a decline, stops further offers of that type for that trip), plus an explicit lasting opt-out. The `trip-concierge` skill turns the wake into one message with one to three late-arrival options in the same chat.
- **An opt-in local e2e rig** (`evals/concierge_e2e`) drives a real Hermes gateway against a loopback Telegram stand-in. It runs with a scripted model, a live one, or synthetic personas that check discovered answers are not asked again.
- **Fix:** automation quiet-hour checks now compare full HH:MM boundaries.
- **Unchanged:** installation stays inert. Wakes need HeartBeat 2.0 v0.2.0 with gateway injection allowed.

## 0.5.0-rc.6 — 2026-10-14

- Keep the PA gateway diagnosable when durable state cannot initialize: read-only diagnostic tools (`read_file`, `search_files`, `session_search`, `skill_view`, `skills_list`) are classified before ledger construction and stay available, while every other call returns a sanitized `DENY_STATE_UNAVAILABLE` block with a `STATE_UNAVAILABLE_<MISSING|PERMISSION_DENIED|LOCKED|MALFORMED|UNKNOWN>` diagnostic instead of a generic internal error. Diagnostic tools cannot carry a governed scope, and exact-action claims, one-shot consumption and replay denial are unchanged once state returns.
- Add a travel-connectivity skill with dated, subject-scoped connectivity profiles in the existing travel ledger: freshness classification, workload estimates derived only from current facts, word-level use matching, reversed trip-range rejection, numeric identifier guards, and stdin input so traveler facts are never staged in the package checkout.
- Harden booking-email proof and trip reconciliation: a bounded read-only proof ladder, issuance proof for every ticketed transport mode, required provider provenance (sender authentication or independent corroboration), private-only identifier matching, per-claim change ledgers, matched-item cancellation removal, and an explicit `refund_pending` status.
- Harden transfer and late-arrival risk assessment: a flight-connection worksheet with separate proven/not-proven/unknown evidence labels, a traveler-specific transit/entry gate where both not-proven and unknown block a safe claim, ticket protection reported independently of eligibility, and late-arrival property-access checks.

## 0.5.0-rc.5 — 2026-09-28

- Prevent PA gateway storage initialization or locking failures from blocking unrelated, unscoped tools by reusing a lazy native gateway and short-circuiting calls with no governed scope before durable storage evaluation.
- Preserve fail-closed exact-action enforcement for governed scopes, including durable scope hydration, atomic one-call claims, replay denial and safe initialization diagnostics.

## 0.5.0-rc.4 — 2026-09-20

- Automatically create a pending exact-action gateway scope when a durable PA action opts into approval governance, binding the current PA/workflow revision, provider tool, semantic target and canonical complete arguments before confirmation.
- Deny matching provider dispatch while approval is pending; after explicit confirmation, allow exactly one matching call while replay, changed arguments, superseded revisions, cancellation, expiry and ambiguous matches fail closed without capturing unrelated calls.
- Start the requested freshness duration at confirmation instead of preparation, persist the refreshed deadline atomically across the gateway scope and PA action, and reject malformed non-positive windows.
- Reframe the repository and agent-facing documentation around Personal Assistant as a persistent personal-operations layer, with a navigable product overview, explicit authority/privacy boundaries, and travel retained as a compatibility domain rather than the product identity.
- Keep release publication separate from installation, activation, provider dispatch, fleet approval and customer readiness.

## 0.5.0-rc.3 — 2026-09-18

- Replace blanket Personal Assistant interception with an opt-in exact-action gateway: ordinary unscoped calls remain under normal Hermes policy, while explicitly scoped actions bind the exact tool, arguments, trusted profile/session/task identity, freshness, preconditions, and one-use claim.
- Add opt-in conversation-owned evidence delivery with bounded packets, a private durable queue, exact existing-conversation routing, revision deduplication, crash fencing, and session/token-bound acknowledgement.
- Keep delivery and daily operations inert by default; source merge and release do not install the startup hook, grant injection permission, register schedules, restart Hermes, perform provider actions, or establish customer readiness.
- Preserve the native `personal-assistant` plugin ID, legacy `travel-agent-skills` archive identity, and existing ledger path while validating extracted archives against both pinned Hermes lifecycle versions.

## 0.5.0-rc.2 — 2026-09-17

- Correct the immutable `v0.5.0-rc.1` packaging defect by including `config/pa-action-gateway-policy.example.json` in every gateway-enabled release archive.
- Verify the finished archive and reject a gateway-enabled package when the runtime policy is absent.
- Load and invoke the native `pre_tool_call` hook from extracted release bytes; an unauthorized protected call must return `DENY_ACTION_MISSING`, while an explicitly safe pass-through call remains allowed.
- `v0.5.0-rc.1` remains published but is operationally rejected and must not be installed or repaired in place.

## 0.5.0-rc.1 — 2026-09-17

- Add a workflow-agnostic, fail-closed PA action gateway candidate with exact full-argument binding, atomic one-shot claims, a conservative shipped policy, redacted receipts, and generic PA authorization operations.
- Register the gateway through Hermes's native plugin `pre_tool_call` API and declare the hook in `plugin.yaml`; no separate managed shell-hook entry is required.
- Add native plugin installation, readback, synthetic-proof, and rollback guidance; merging does not activate the gateway or authorize provider writes.

## 0.4.1-rc.2 — 2026-09-16

- Fix: the `pa` tool no longer crashes with `TypeError` when a schema-valid, op-irrelevant top-level key (for example, `limit`) reaches a write operation (`action_upsert`, `calendar_sync`, or `trip_export`) — skill-personal-assistant#42. This was observed on a managed Hermes profile running 0.3.0 during a rollout cron.
- Tooling: release publication now retries the draft read-back after creation (#41); there is no runtime change from this tooling update.
- Compatibility: the tool schema, ledger format, and `python_dependencies` remain unchanged (icalendar==6.3.1, python-dateutil==2.9.0.post0, six==1.17.0, tzdata==2026.3, jsonschema==4.26.0).

## 0.4.1-rc.1 — 2026-09-16

- Recover the intended v0.4.0 release under a fresh version number: the `v0.4.0` git tag was permanently locked by the immutable release-tag ruleset before a release was cut, so the same reviewed content ships as v0.4.1 with no behavior change.
- Carry the profile-permissions fix staged as 0.4.0: accept managed group-writable profile ancestors while keeping the PA-owned ledger directory and database private, and surface permission diagnostics from the helper CLI.
- Realign every version source (VERSION, plugin.yaml, the native package `__version__`, the four plugin manifests) and add `releases/0.4.1/manifest.json` so the release contract sees a single consistent version.

## 0.4.0 — 2026-09-15

- Accept managed group-writable profile ancestors while keeping the PA-owned ledger directory and database private, and surface permission diagnostics from the helper CLI.

## 0.4.0-rc.1 — 2026-09-15

- Package the September Personal Assistant workflows, focused context, calendar fidelity, durable action/projection records and freshness checks.
- Add native Hermes dependency and installation guidance, read-only pilot/stable release checks and profile-bound approved pinned replacement.
- Preserve current configuration and profile state through Git/archive replacement, repeat update, rollback and restoration-failure recovery.
- Publish deterministic archives, portable checksums and exact-source manifests only from a reviewed release PR; reject conflicting publication identities.
- Keep the package private and fleet approval unchanged. Legacy-only and manually damaged installation diagnostics remain in #34.
- Preserve the July release history below.

## 0.1.0

- Sanitized the shared package for customer-pilot installs by removing customer-specific canaries and replacing customer-like examples with placeholders.
- Reframed release metadata as the first action-ready customer-pilot release rather than an RC scoped to a pilot customer.
- Added customer-neutral v0.1 canaries for trip capture, payment readiness, Browserbase reattach, food final summaries, hotel/flight final pages, provider messages/refunds, and rideshare previews.
- Kept the full action-ready skill set available for enrolled pilot customers while preserving final-state confirmation before paid or irreversible actions.

## 1.0.0-rc1

- Renamed the package to Travel Agent Skills for the first release-versioned add-on track.
- Added trip/action ledger support, Browserbase checkpoint/reattach behavior, payment readiness checks, and final-state confirmation summaries.
- Added provider message/refund, food delivery, rideshare, Trip.com, airline check-in, hotel check-in, weather, email/calendar, and trip nudge skills.
- Added pack validation, canary scenarios, release packaging, installed-version probing, and support-control component metadata.
- Scoped rollout to a pilot customer canary until split canaries pass with an average score of 95 or better.
