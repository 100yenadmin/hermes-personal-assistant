---
name: pa-setup
description: Guide Personal Assistant setup or review through discovery, one-question turns, approved preference writes, and a fresh-session check.
metadata:
  openclaw:
    skillKey: pa-setup
  hermes:
    category: productivity
    tags: ["personal-assistant", "setup", "preferences", "review"]
---

# Personal Assistant Setup

Every `references/...` path is relative to this skill directory.

## When to use

Use when the context note says guided setup is active, or the user asks to set up
or review PA. Resume from saved progress; do not restart a completed interview.

## Rules

- Ask one question per message, with a recommended answer grounded in discovery.
  If nothing supports a recommendation, say so and offer a clearly labelled default.
- “Skip”, “later”, and “you decide” always work. Skip leaves an answer unknown;
  later pauses; you decide accepts the stated recommendation, not extra authority.
- Help with an off-topic request first, then resume at the unanswered question.
- Record every section answer immediately, including corrections and delegated choices. Record skipped IDs too; never pretend an unasked question was asked. After apply, changed answers keep setup applied with `pending_changes: true`; the fresh check is unaffected.
- Never write SOUL.md, USER.md, the manual, context files, or automation preferences
  before explicit apply. Setup progress and proposals are the only interview writes.
- On “pause”, call setup `pause` and stop the interview. On refusal, use `decline`.
  `/pa setup` resumes. Neither action claims existing jobs have been paused.
- Never pay, book, send as the user, contact people, or cancel without confirmation.

## Setup operations

“Setup status” means `pa(operation="setup", data={"action":"status"})`.
Use that same wrapper for every action below; do not invent separate tools.
Progress lives in the `pa:setup` record, never a state-loop event.

```json
{"action":"start"}
{"action":"record","answers":{"call_and_quiet":{"text":"<safe answer>","source":"user"}},"skipped":[],"asked":["call_and_quiet"]}
{"action":"propose","writes":[{"target":"soul_section","summary":"<reviewed change>"}]}
{"action":"propose","writes":[{"target":"manual_skill","summary":"<deeper answer>"}],"draft":true}
{"action":"applied","readbacks":[{"target":"soul_section"}]}
{"action":"fresh_check","status":"passed"}
{"action":"pause"}
{"action":"decline"}
```

Answer sources are `user` or `discovered`. File targets are `user_memory`,
`soul_section`, `manual_skill`, and `context_file`; `pa_preferences` is proposal-only.
Read `status`, `requested_mode`, `next_question`, `answers`, `skipped`, `asked`,
`proposal`, `proposal_draft`, `applied`, and `fresh_check`, plus `requested_section`. Omitting `section` on `start` preserves the requested section; `/pa setup` requests core, or continues an active setup in the current chat. Only IDs in the two question-bank sections may appear in `record` answers, skipped or asked. Use `start` for a requested start, never to reset a fresh-session check.
## Chief of Staff section
`/pa setup chief-of-staff`: first check mode; if off, explain `/pa mode chief-of-staff on`, restart and a new session, then stop.
Use setup `{"action":"start","section":"chief_of_staff"}`; follow the CoS flow in `references/question-bank.md` and the reviewed destinations in `references/where-answers-go.md`.

## Flow

1. Read setup status; `pending_changes` waits for the next `/pa setup review`, then propose and apply to save it in files. For applied setup with a pending or failed check, use the
   Fresh-session check section directly. If `status` is `proposed`, read the current
   targets, rebuild the exact diff, `propose` again and get approval of that diff,
   then step 7; saved summaries never authorize writes. Otherwise introduce briefly:
   “I’m your Personal Assistant: everyday help, travel help, and Chief of Staff.
   We’ll take one question at a time; skip, later, or you decide always work. I’ll
   show changes before saving; `/pa setup` resumes whenever you like. I ask before
   paying, booking, sending as you, contacting people, or cancelling.”
2. In the same message, ask only consent to look around: “May I read your existing
   preferences and routines? I recommend it so I can reuse what already works.”
   Save `consent: "granted"` or `"declined"` with the first `record` call; known facts wait for step 4.
   Never re-ask a known fact. If declined, use what the user shares; do not inspect private sources.
3. With consent, read the active profile’s SOUL.md, USER.md, relevant MEMORY.md,
   and the context file Hermes actually loaded. Check `pa(operation="status")`,
   `pa(operation="capabilities")`, and `pa(operation="automations", data={"action":"status"})`.
   List Hermes cron jobs, installed integrations, and user skills (`skills_list`).
   Recover timezone, upcoming confirmed trips and relevant calendar facts through
   already authorized read paths. Missing access is unknown, not an empty calendar.
   Do not start logins, enable jobs, or perform provider actions during discovery.
   For `requested_mode: "review"` or a null `next_question`, go from discovery to step 6.
   A repeated `/pa setup` keeps prior answers: show them in the review, never re-ask.
4. Send “Here is what I already know” as its own message, with safe source summaries
   and uncertainties, ending with one ask: keep these (recommended if supported) or correct.
   In one `record` call, save each fully known core ID as `discovered` (not in `asked`):
   name+quiet hours+zone → call_and_quiet, ask-before rules → authority, arrival wishes →
   arrival_help, check-in lead → check_in_time. Ask a partly known ID, known parts recommended.
   For each existing brief or alert job, show keep / adapt / replace with a reason.
   Resolve one job per question; one publisher per brief or alert. Review job changes.
5. Read `references/question-bank.md`. For core, follow the eight core IDs in order, skipping
   known answers and respecting skipped IDs. Record `asked` IDs and each core answer
   using setup `record`. Deeper answers go into the review, then manual/USER.md/
   SOUL.md only; never pass deeper section names or IDs to setup `start` or `record`.
   Save deeper answers as you go with `propose` and `draft: true` (safe summaries under
   their targets); a draft keeps the interview going and step 6 uses `proposal_draft`.
6. Read `references/where-answers-go.md` and `references/manual-template.md`.
   Build one fresh review, then call `propose` with changed targets and summaries.
   Use `pa_preferences` for PA preference changes, or `writes: []` for no changes.
   Show saved answers and one review message
   with a diff per target: only missing or corrected facts, current persona kept.
   Include preference changes and job decisions; mark unchanged targets “no change”.
   Example: “USER.md: + preferred name. SOUL.md PA section: + ask before sending.
   Manual: + source hierarchy. Morning brief: keep. Apply all, apply some, or change X?”
   A partial apply must name its subset; revise `propose` to exactly that subset.
   Wait for explicit “apply”; answering the interview is not approval to write.
7. After apply, leave Plan Mode if active and write the approved subset in the
   foreground using the destination reference. Do not claim a protected-write
   prompt will approve the profile SOUL.md: this review is its approval gate.
   Apply `pa_preferences` through `pa automations` action `preferences` (no readback).
   After all proposed writes succeed, call `applied` with exactly the proposed file targets:
   `readbacks: [{"target":"user_memory"},{"target":"soul_section"},{"target":"manual_skill","skill":"<name>"}]`,
   and an absolute `path` for a `context_file`. PA reads the files and computes the
   hashes; never compute or invent them. On a failed readback, fix the write and call
   again; with no file targets use `readbacks: []`. Keep failures and pending writes
   visible. Verify preference/job changes through their own status operations.
8. Core only (a CoS setup skips 8–9 and follows its question-bank flow). Ask for `/new` and then any message
   (never `/pa setup`, which reopens setup), then ask, for example, “When would you check in
   before my next flight?” Do not arm a wake yet: `/new` can orphan existing HB2 wakes.
9. Complete the fresh-session check below, then load
   `personal-assistant:trip-concierge` to arm the first agreed trip/day check-in.
   Reuse the selected publisher; pass the agreed lead as `check_in_lead_minutes`
   (hours × 60; 180-minute default if skipped), plus the manual's confirmed HB2
   window and zone as `hb2_quiet_hours` and `hb2_timezone` to `trip_watch_plan`.
   Resolve unknown HB2 settings via the destination reference. If setup was on Desktop,
   say “Open your Telegram chat with me and say ‘arm my check-in’” and hand off there.

## Fresh-session check

The new-session hook may load this section without the interview. First read `pa(operation="setup", data={"action":"status"})`; do not call `start`.
If `requested_section` is `chief_of_staff`, run the CoS check in `references/question-bank.md` instead: no flight question and no trip or check-in arming.
Later recorded answers leave the fresh check unaffected. If `status` is not `applied`, resume its flow; if `fresh_check.status` is already
`passed`, do not rerun from the hook note. When `pending` or `failed`, run the check
in a session other than the apply session: load the saved manual/USER.md through
normal memory/skill loading and answer
“When would you check in before my next flight?” from “check in N hours before
departure”. If `check_in_time` was skipped, use another saved preference (quiet
hours or preferred name) in the answer; state 180 minutes as the default, not a saved choice.
With a known trip, give a concrete date/time using the effective zone and quiet
rule (move a quiet-hours candidate to the evening before); otherwise give the
relative rule and say trip timing is unknown. Confirm the saved files hold the
approved facts; repeating interview text is not proof. Call `fresh_check` with
`status: "passed"` when the answer correctly uses a saved preference; otherwise
`"failed"`: show the gap, offer a reviewed fix, then repeat `/new` and the check.
Do not arm the first check-in until the check passes.

## Existing users

A user skill covering this user’s briefs, inbox, calendar, or travel is a manual
candidate: patch it, never create a second. If several overlap, recommend one and ask.
Keep the daily manual near 8 KB: distil by domain, do not append every correction.
Engineering or product lessons belong in the repo or an issue, not the manual.
