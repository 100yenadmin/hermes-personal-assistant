"""VA catalogue from docs/vision/va-bar.md and closure milestones from ROADMAP.md."""

AREAS = [
    {"key": "inbox", "title": "Inbox", "closes_in": "M4",
     "duties": ["Triage at least twice a day: urgent / needs-you / handled / FYI / junk",
                "Draft routine replies in the principal's voice from approved patterns",
                "Track every open thread to a reply or decision", "Daily digest of five lines or fewer",
                "Meet the agreed SLA", "Filter newsletters and spam without being asked"], "tests": []},
    {"key": "calendar", "title": "Calendar", "closes_in": "M4",
     "duties": ["Book with buffers and travel time", "Protect focus blocks", "Resolve conflicts early",
                "Confirm every meeting 24h ahead", "Send an agenda and one-page brief",
                "Capture action items within 24h", "Get cross-time-zone arithmetic right",
                "Decline and reschedule politely in the principal's name"],
     "tests": [{"scenario": "s19_calendar_conflicts_en", "kind": "partial",
                "label": "calendar reads and conflicts (lab stand-in for the provider read)", "covers": [1, 2, 6]}]},
    {"key": "travel", "title": "Travel", "closes_in": "M0 (real trip), M5 (completion)",
     "duties": ["Collect constraints once: budget, preferences, loyalty numbers, arrive-by",
                "Return 2-3 good / better / best options with totals and trade-offs",
                "Hold at the final submit", "Deliver one post-yes itinerary with every leg and confirmation",
                "Include check-in times, ground transport, addresses and contingencies",
                "Track changes and expenses afterwards"],
     "tests": [{"scenario": "s01_seoul_tokyo_en", "kind": "partial", "label": "travel prep to the final page", "covers": []},
               {"scenario": "s02_tokyo_seoul_ko", "kind": "partial", "label": "travel prep to the final page", "covers": []},
               {"scenario": "s03_sf_tokyo_en", "kind": "partial", "label": "travel prep to the final page", "covers": []}]},
    {"key": "errands", "title": "Errands and bookings", "closes_in": "M5",
     "duties": ["Find the right vendor", "Check availability and price", "Draft the request",
                "Stop before commit", "Confirm afterwards",
                "Calendar the appointment with a reminder and vendor contact"], "tests": []},
    {"key": "phone", "title": "Phone and messages", "closes_in": "M5",
     "duties": ["Make and take calls to confirm, chase, query and cancel on instruction",
                "Screen unknown callers", "Relay who, outcome, promises, next step and date",
                "Use the preferred channel per contact", "Never disclose private details or commit the principal"],
     # Simulated calls: PA's own turns against a text-mode counterpart, no phone line. The checks need a real exchange
     # ending in an allowed outcome. Duty 4 is not credited: only the "booked" outcome label is checked, and nothing
     # reads the call for private details or a spoken commitment (scorecard PR review).
     "tests": [{"scenario": f"s0{n}_{name}", "kind": "partial", "label": label, "covers": [0]} for n, name, label in [
         (4, "call_ryokan_ja", "simulated outbound call: ryokan late check-in query (Japanese)"),
         (5, "call_restaurant_ko", "simulated outbound call: table and deposit query (Korean)"),
         (6, "call_shop_ja", "simulated outbound call: stock and hours query (Japanese)"),
         (7, "inbound_hotel_ja", "simulated inbound call: hotel confirms arrival time (Japanese)"),
         (8, "inbound_restaurant_ko", "simulated inbound call: restaurant asks to move a booking (Korean)")]]},
    {"key": "research", "title": "Research", "closes_in": "M2",
     "duties": ["Restate the question", "Fix comparison criteria first",
                "Lead with a one-page answer, recommendation and reason, then detail",
                "Source and date every number", "Declare what could not be found", "No padding"],
     "tests": [{"scenario": "s18_research_payroll_en", "kind": "full",
                "label": "payroll providers, two countries", "covers": [0, 1, 2, 3, 4]}]},
    {"key": "documents", "title": "Documents and data", "closes_in": "M6",
     "duties": ["Clean briefs, agendas and minutes with owners and dates on every action",
                "Prepare proposals and slide skeletons", "Use spreadsheet formulas, not pasted numbers",
                "Keep the naming convention and folder tree", "Keep CRM and contacts current and deduplicated with a change log"], "tests": []},
    {"key": "finance", "title": "Finance admin", "closes_in": "M6",
     "duties": ["Send invoices and reminders on schedule", "Chase overdue invoices on a polite escalation ladder",
                "Categorise expenses and reconcile cards monthly", "Weekly cash position",
                "Monthly income/expense summary", "Tax-season pack for the accountant", "Never initiate a payment or transfer"], "tests": []},
    {"key": "personal_admin", "title": "Personal life admin", "closes_in": "M3 (radar), M6 (the rest)",
     "duties": ["Track passport, visa, insurance, subscription, licence and vehicle renewals",
                "Track birthdays and gifts", "Handle family logistics, health appointments and household vendors",
                "Keep a yearly personal calendar", "Remember sizes, allergies, favourite places and important people"], "tests": []},
    {"key": "customer_comms", "title": "Customer and vendor comms", "closes_in": "M6",
     "duties": ["First-line FAQ replies in company voice", "Resolve tier-1 issues under written policy",
                "Escalate tier-2 with context and recommendation", "Chase vendor timelines and deliverables",
                "Report volume, response time and recurring complaints weekly", "Never promise refunds or terms outside policy"], "tests": []},
    {"key": "social", "title": "Social and content admin", "closes_in": "M6",
     "duties": ["Keep a content calendar", "Turn raw notes into posts in voice", "Schedule into the approval flow",
                "Answer routine comments and DMs", "Monitor mentions", "Report weekly",
                "Publish only inside the principal's chosen approval flow"], "tests": []},
    {"key": "recurring_ops", "title": "Recurring ops",
     "closes_in": "M2 (check), M3 (daily and weekly), M6 (monthly, quarterly, licences and contracts)",
     "duties": ["Own daily brief, weekly kickoff, closeout, monthly admin and quarterly review checklists",
                "Run checklists unprompted", "Notice missed recurring items", "Maintain the SOP library",
                "Improve one SOP a week", "Track renewals, licences and contracts"],
     "tests": [{"scenario": "s13_cos_daily_en", "kind": "partial", "label": "routine runs: daily", "covers": []},
               {"scenario": "s14_cos_daily_silence_en", "kind": "partial", "label": "routine runs: quiet day", "covers": []},
               {"scenario": "s16_cos_weekly_en", "kind": "partial", "label": "routine runs: weekly", "covers": []},
               {"scenario": "s17_cos_kickoff_en", "kind": "partial", "label": "routine runs: kickoff", "covers": []}]},
    {"key": "onboarding", "title": "Onboarding", "closes_in": "M1",
     "duties": ["Interview in short bursts across business, principal, communication, rights, preferences, calendar, history and access",
                "Write a living profile, read back for correction and never re-ask recorded answers",
                "Capture, correct and own recurring-task SOPs", "Arrange named least-privilege delegated access before day one",
                "Stage shadowing, process ownership, judgement and independence across the first 30 days",
                "Review quality, time saved, questions and the month-2 task wave at day 30",
                "Read granted material before asking; record preference provenance and learn from edits",
                "Propose repeated patterns, confirm inferences and read style guides on day one"], "tests": []},
    {"key": "working_norms", "title": "Working norms",
     "closes_in": "M1 (preferences); norms checked inside scenarios",
     "duties": ["Anticipate next steps and bring a plan", "Track open-loop owners, next actions and dates; chase to confirmation",
                "Report daily, weekly and immediately on exceptions", "Escalate early with problem, options, recommendation and deadline",
                "Act within decision rights; draft-and-hold outward actions and batch non-urgent questions",
                "Keep confidential details inside the role and agreed systems", "Use explicit correct time zones and plan holidays",
                "Check outbound facts, totals, links, attachments and placeholders; log errors and fixes",
                "Keep agreed hours, response SLA, away hand-off and emergency path"], "tests": []},
]

LAB_RUNS = 3
REAL_MIN_TASKS = 10
REAL_MIN_OWNERS = 2
REAL_MIN_DAYS = 14
REAL_PASS_RATE = 0.9
DAY30_MIN_SAVING = 0.2
DAY30_MIN_TYPES = 4
DAY30_MIN_DAYS = 28  # The day-30 review week ends at least this many days after the owner's first task.
PARITY = {"LAB_RUNS": LAB_RUNS, "REAL_MIN_TASKS": REAL_MIN_TASKS,
          "REAL_MIN_OWNERS": REAL_MIN_OWNERS, "REAL_MIN_DAYS": REAL_MIN_DAYS,
          "REAL_PASS_RATE": REAL_PASS_RATE, "DAY30_MIN_SAVING": DAY30_MIN_SAVING,
          "DAY30_MIN_TYPES": DAY30_MIN_TYPES, "DAY30_MIN_DAYS": DAY30_MIN_DAYS}


# Synthetic lab rows cover only the named duties; live provider/session proof is separate.
for key, scenario, covers, label in (
    ("documents", "s43_owner_documents_en", [0, 2, 3, 4], "owner Sheet formulas and agenda Doc, filed and read back; exact approved share and CRM field"),
    ("documents", "s32_contacts_cleanup_en", [4], "deduplicated contact import with a change log; no provider write"),
    ("working_norms", "s37_approval_day_en", [3, 4], "decisions finished with options, a recommendation and a decide-by date, drafts held; a yes in a new chat confirms the prepared booking once"),
    ("social", "s38_content_calendar_en", [0, 1, 2], "two-week content calendar and three drafts in the owner's voice, each slot a dated item held for the yes; nothing posted"),
    ("documents", "s34_meeting_minutes_en", [0], "minutes from a raw transcript: an owner and a date on every action item, open questions kept, nothing sent"),
    ("onboarding", "s35_onboarding_first_win_en", [], "essentials intake, one review and apply, then the triaged inbox as the first win; no terminal steps"),
    ("inbox", "s36_inbox_awaiting_en", [1], "read-but-unanswered threads surfaced, tracked and drafted; one exact junk archive offer; nothing moved"),  # An offer is not filtering (#202 review).
    ("customer_comms", "s31_customer_policy_en", [1, 2, 3, 5], "policy-bound drafts, owner escalations and vendor chase tracking"),
    ("travel", "s30_trip_expenses_en", [], "stand-in booking charge and forwarded receipt recorded; per-trip expense export"),
    ("finance", "s30_trip_expenses_en", [], "categorised trip expenses from a readback and a receipt; no card reconciliation"),
    ("finance", "s44_tax_pack_en", [5, 6], "prior-year accountant pack with per-currency totals, questions and two exports; cover email held"),
    ("finance", "s33_invoice_chase_en", [0, 1, 6], "receivable reminders and the chase ladder held for the yes; payable deadlines; remittance marks paid"),
    ("travel", "s29_changed_leg_en", [2, 3], "synthetic cancelled leg: held options, then rebook, moved dinner and retired reminders"),
    ("travel", "s27_booking_after_yes_en", [3], "stand-in booking after the yes: readback, itinerary, reminders, ICS"),
    ("errands", "s27_booking_after_yes_en", [3, 4, 5], "stand-in booking after the yes: readback, itinerary, reminders, ICS"),
    ("errands", "s28_vendor_request_en", [2, 3, 4, 5], "stand-in appointment and vendor request after the yes: reminder, readbacks, waiting-on-them loop"),
    # Real-web runs held back by the no-submit tripwire: stopping before the commit is checked, not the rest of the duty.
    ("errands", "s10_change_cancel_en", [3], "change and cancellation of a booked dinner and hotel prepared from the ledger, never executed"),
    ("errands", "s11_failures_en", [3], "sold-out date, deposit over the limit, login or OTP wall and CAPTCHA handed off honestly; nothing submitted"),
    ("travel", "s12_multi_errand_ja", [], "four errands in one Japanese chat (flight, hotel, dinner, snacks), each stopped at its final page or handed off"),
    ("working_norms", "s20_follow_through_chase_en", [1, 3, 4], "confirmation-only loops and draft chase ladder"),
    ("personal_admin", "s21_personal_radar_en", [0, 1], "personal radar and held proposals"),
    ("recurring_ops", "s22_eod_note_en", [0, 1], "evidence-grounded end-of-day note"),
    ("recurring_ops", "s23_broken_routine_en", [2], "same-cycle routine health exception"),
    ("inbox", "s24_inbox_triage_en", [1, 3], "synthetic drafts and five-line digest"),
    ("calendar", "s25_calendar_invite_en", [1, 6], "synthetic approved invite and readback"),  # No travel-time check yet.
    ("calendar", "s26_meeting_confirm_en", [6], "held confirmations and one-page briefs"),  # Held drafts, not completed confirmations or sent briefs.
    ("working_norms", "s39_priorities_brief_en", [0], "open items linked to the owner's priorities; the priority each overdue item threatens, the next blocked step and an overloaded holder named; nothing sent"),
    ("customer_comms", "s40_customer_report_en", [4], "read-only weekly report: volume, unanswered threads, median first response, recurring complaints with counts, held replies, escalations and open items with owners; no customer names; nothing sent"),
    ("personal_admin", "s41_family_admin_en", [1, 2, 3, 4], "held dentist appointment for the right person with the allergy in the packet, held boiler request with the access code only there, a twelve-month year and a three-idea gift shortlist that avoids the allergy; nothing booked or sent"),
    ("working_norms", "s42_role_two_days_en", [1, 4], "two synthetic unattended role turns: urgent decision surfaced, day-2 nudge held for the owner's yes, nothing sent; no scheduler proof"),  # Two days prove no weekly report (#202 review).
):
    next(area for area in AREAS if area["key"] == key)["tests"].append(
        {"scenario": scenario, "kind": "partial", "label": label, "covers": covers})
