# Setup question bank

Ask the core questions in this order, one per message. Reuse known answers and
ask only for corrections. Every recommendation names its basis; a fallback is
a suggestion, never a discovered fact. Record core answers through setup `record`.
The destination rules are in `where-answers-go.md`.

## Core questions

| ID | Friendly question | Form the recommended answer | Save after apply |
|---|---|---|---|
| `call_and_quiet` | “What should I call you, and when should I stay quiet? Should timing follow you when you travel?” | Use USER.md and existing schedules first. If absent, suggest 22:00–07:00 and travel-local timing. Name the effective timezone; do not guess current location. Separately confirm the effective HB2 window and zone using the status readback below. | Compact name/hours/zone in USER.md; quiet hours and timezone in PA preferences; travel-local policy and source in manual, plus “HeartBeat quiet hours HH:MM–HH:MM in <zone>” (or “HeartBeat quiet hours off in <zone>”). |
| `worth_a_message` | “What is worth a message, and what should stay silent?” | Use prior corrections. Recommend decisions, deadlines, preparation, why now and a next action. Show a sample: “Your check-in window opens this afternoon. Shall I prepare it?” Never counters, job IDs, “check your inbox”, or unchanged checks. | Tone in SOUL section; examples and message rules in manual. |
| `authority` | “May I prepare things up to the final button, then ask before paying, booking, sending or contacting anyone?” | Recommend yes for preparation, subject to existing limits. Keep cancellation and cleanup separate; broad help is not final-action approval. | Boundaries in SOUL section; detailed permissions in manual. |
| `first_trip` | “Which trip, or which day, should I help with first?” | Recommend the next confirmed itinerary; otherwise tomorrow with an explicit date and timezone. Unknown or conflicting trip data stays unknown. | First focus and source in manual; keep canonical trip details in PA, not duplicated here. |
| `arrival_help` | “What would help most when you arrive?” | From arrival time, suggest food, a hotel request, or pickup. Consider venue arrival after immigration, bags, transfer and buffer. Do not claim availability without checking. | Travel profile in manual. |
| `protect` | “Which commitment must this trip protect?” | Show a discovered meeting or other commitment and ask only for corrections. If no firm commitment exists, say so; do not force one onto a flexible day. | Commitment priority and source in manual; canonical itinerary stays in PA. |
| `route` | “Which connected account or app should I use for that?” | Recommend an already connected route with the right role and scope. Confirm authoritative calendar/mailbox and primary delivery chat; access does not grant sending authority. | Compact preferred channel in USER.md; source hierarchy and route roles in manual. |
| `check_in_time` | “How many hours before departure should I check in here?” | Suggest 3 hours before departure; move to the evening before if that falls in PA or HB2 quiet hours. With a confirmed trip, state the concrete date, timezone, expected monitoring latency and delivery chat. | Save “check in N hours before departure” and the quiet rule in manual/USER.md. Tell trip-concierge to pass N × 60 as `check_in_lead_minutes` plus the confirmed `hb2_quiet_hours` (ASCII "HH:MM-HH:MM", or "" when off) and `hb2_timezone` (IANA) to `trip_watch_plan`; arm only after the fresh-session check. |

For skipped IDs, record `skipped: ["<qid>"]`; leave facts unknown. For “you
decide”, record the chosen recommendation and the user's delegation as `user`.
Do not turn that delegation into authority for later payments or messages.
If `check_in_time` was skipped, leave its answer unknown and label 180 minutes
as the default. In the fresh session, use another saved preference such as quiet
hours or preferred name; record `passed` when the answer uses what was saved.

## Going deeper

Ask only when relevant or the user picks a section, one question at a time.
The setup op supports only `core` and the eight IDs above. Never pass a deeper
section name or ID to setup `start` or `record`, or reuse a core ID for it.
Keep deeper answers in the review, then save approved facts to the manual,
USER.md or SOUL.md as below; they are not setup progress records.

| Section | Topics and recommended basis | Destination |
|---|---|---|
| You | Working hours, tone, urgent channel, languages. Reuse accepted profile facts before asking. | Compact facts in USER.md; persona/tone in SOUL section; delivery detail in manual. |
| Authority | Never-do list; permitted contacts. Suggest asking before contact; hotels, airlines and restaurants may have different scopes from people the user knows. Promotions are not spam. | SOUL boundaries and manual permissions. |
| Proactivity | Check-in types, daily message cap, night disruptions, brief time. Suggest at most three unprompted messages per day outside trips if no preference exists; propose night disruption alerts per trip, never silently. | Manual timing policy, caps and consent; hand HB2 settings to the user as below. |
| Travel profile | Home airports, airlines/loyalty, seat/cabin, quiet room/pillows/temperature, ground transport. Ask diet/allergies when ordering food. Suggest two hours domestic and three international airport lead time only as defaults; ask minimum connection when relevant. Reuse the travel-connectivity interview for connectivity. | Manual travel profile; compact stable facts only in USER.md. |
| Processes | Up to three recurring jobs: ask trigger, inputs and output to propose a routine. Reuse existing publishers and explain actual coverage before replacing anything. | Manual routines; scheduling needs its own reviewed job decision. |
| Chief of Staff | Role, good week, top three priorities, key people/meetings, work sources, research radar and adopt-vs-build stance. Suggest weekly batched improvements and at most one benchmark slot per week only when wanted. | Manual; project or engineering findings need a separate repo workflow. |

Unsupported settings remain proposals, not claims that code enforces them.
Night interruptions need explicit consent. PA preferences do not set HB2 quiet
hours (default 22:00–08:00). HB2 uses plugin config for its profile default, or the
owner's `/pulse quiet 22:00-07:00` chat override (`/pulse quiet default` restores
the default). Its agent tool cannot change these settings. The inspected
`pulse(action="list")` returns wakes, not quiet hours or timezone, and has no
status action. Ask the user to paste the `Local time: … · quiet: …` line from
`/pulse status` in the intended delivery chat, then confirm the actual recurring
window (or off) and IANA zone, one question per turn. “Off now” is not disabled
quiet hours; a timezone abbreviation alone does not identify the IANA zone.
Use exposed effective fields if the installed tool provides them; otherwise
resolve missing values with the user. Save the confirmed HB2 window/zone and
source in the manual after apply, separately from PA; never infer alignment.
See `where-answers-go.md` for the planner handoff. Changing quiet hours does not
bypass message caps.
