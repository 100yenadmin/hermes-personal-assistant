# Where setup answers go

No destination write happens before the user reviews the diff and explicitly
says apply. This includes memory calls and preference/job changes. Setup `record`
and `propose` save interview progress only; they do not apply it.

| Kind | Destination | Setup target |
|---|---|---|
| Compact facts: name, timezone, hours, channel | USER.md through native memory | `user_memory` |
| Persona, tone, boundaries | Only the delimited Personal Assistant section of profile SOUL.md | `soul_section` |
| Travel profile, processes, Chief of Staff context, provenance and precedence | Existing PA user skill, or a new pinned operating manual | `manual_skill` |
| Quiet hours, timezone, brief time needed by code | PA automations preferences | `pa_preferences` (no file readback) |
| A real project rule | Only the context file Hermes actually loaded | `context_file` |

Deeper answers are not setup `record` IDs: persist safe summaries in a `propose`
draft before pause or session end, include them in the review, then save
approved facts only in the manual/USER.md/SOUL.md. Save `check_in_time` as “check
in N hours before departure” (suggest 3 hours), with the rule to move a candidate
in quiet hours to the evening before. Tell trip-concierge to use N × 60 as
`check_in_lead_minutes`; keep the relative rule available for a fresh session.
When `check_in_time` was skipped, keep it unknown and state 180 minutes as the
default, not an accepted preference. The fresh-session answer can demonstrate
another saved preference (quiet hours or preferred name); record `passed` when
it uses what was saved and the saved files still hold the approved facts.

## USER.md

Use `memory(action="add", target="user", ...)` for missing compact facts or
`memory(action="patch", target="user", ...)` for corrections on Hermes ≥0.22;
older pins use `memory(action="replace", target="user", ...)` instead.
Use the installed tool's actual arguments. Read existing content before corrections. Do not write
USER.md directly or duplicate long profiles there. On an over-budget error,
move detail into the manual, review the changed split, and keep the compact fact;
never silently truncate facts to fit. Read back the active profile's saved USER.md.

## Profile SOUL.md

Read `$HERMES_HOME/SOUL.md`. Insert or replace only this block:

```markdown
<!-- personal-assistant:start -->
## Personal Assistant
<approved persona, tone and boundaries>
<!-- personal-assistant:end -->
```

Keep all existing persona text outside the markers untouched. If no block exists,
append one; do not absorb an unrelated existing heading. If markers are ambiguous
or incomplete, show the conflict and ask before repair. Use a normal foreground
file write after explicit apply, then read back. The profile's own SOUL.md is
exempt from Hermes' protected-write gate: no extra host prompt approves it.
Project-local instruction files still follow Hermes' protected-write approval.

## Operating manual

Discover user skills by description, not a fixed name. If one covers this user's
briefs, inbox, calendar or travel, patch it through `skill_manage`. Do not create
a second PA manual. Resolve overlapping candidates with the user before writing.
Otherwise use `skill_manage` to create `operating-manual` from `manual-template.md`.
Keep it near 8 KB; replace stale guidance and distil by domain instead of appending.
Read back the skill's saved file. Pin the selected skill in the active profile:

```sh
hermes curator pin <name>
```

Run that through the terminal tool when available. Otherwise give the user that
exact command with `<name>` replaced by the selected skill name. State that pinning
is pending; do not claim archive protection until the command succeeds.

## Preferences code needs

Read `pa(operation="automations", data={"action":"status"})` first. After apply,
use `pa(operation="automations", data={"action":"preferences","changes":{...}})`.
Preserve existing preferences when forming `changes`; use supported keys only:
`timezone`, `brief_time`, `quiet_hours`, `paused`, `snooze_until`,
`cos_daily_time`, `cos_weekly_day`, `cos_weekly_time`.
Quiet hours use `{"start":"22:00","end":"07:00"}`; use an IANA timezone.
Read status again to verify saved values. A travel-local policy in prose does not
prove a scheduler follows it; verify its effective zone before promising a time.
HB2 quiet hours are separate (default 22:00–08:00). Its `pulse` agent tool cannot
change them. Show how they differ from PA and hand the change to the user:
edit the HB2 plugin's `quiet_hours` config for the profile default, or send
`/pulse quiet 22:00-07:00` in the delivery chat for a chat override.
`/pulse quiet default` restores the configured default; `/pulse status` shows
the current chat's status. The inspected `pulse(action="list")` exposes wakes
only, with no quiet-window/timezone fields or status action. Ask the user to
paste only the `Local time: … · quiet: …` line from `/pulse status` in the
intended delivery chat. If the installed tool exposes effective settings, use
those instead. Confirm the recurring window or explicit off and its IANA zone:
“off now” only means not quiet at that moment, and an abbreviation is not an
IANA zone. Ask for any missing window/zone; never substitute PA settings or an
assumed HB2 default. Keep a temporary “quiet until” override distinct and
reconfirm its effect before arming.

After apply, save “HeartBeat quiet hours HH:MM–HH:MM in <zone>” or “HeartBeat
quiet hours off in <zone>” in the manual with the source and confirmation date.
Trip-concierge passes this confirmed window as `hb2_quiet_hours` in ASCII
"HH:MM-HH:MM" form (a hyphen, not the manual's dash), or "" when HB2 quiet hours
are off, and the IANA zone as `hb2_timezone`, to `trip_watch_plan`, alongside `check_in_lead_minutes`
(N × 60, or the labelled 180-minute default if skipped). Unknown is not off;
resolve missing settings before planning. Recheck in the delivery chat if setup
was elsewhere. Never claim PA and HB2 are aligned until the user confirms.
Do not register, replace or enable jobs without the reviewed job decision and
explicit approval. Keep one publisher per brief or alert; never a second morning brief.

## Chief of Staff schedules

Read `pa(operation="status")`; stop if `modes.chief_of_staff` is not true.
Explain `/pa mode chief-of-staff on`, then `hermes gateway restart` and a new
session. Never create rules while off. Save `cos_priorities` and
`cos_radar_topics` through the reviewed USER.md/manual path above. Apply
`cos_daily_time`, `cos_weekly_day` and `cos_weekly_time` through preferences
(defaults 09:30, mon, 10:00 in the confirmed IANA timezone). PA refuses a time
inside quiet hours, because that report would never be sent; offer one outside them.

Only an explicit yes in a human turn to daily, weekly, or both permits those
schedules. “You decide”, skipped timing or a general apply is not a schedule yes.
Read automation status and Hermes jobs first; reuse an existing selected rule
and publisher instead of making duplicates. Show the proposed rules in review.
Set up schedules from the chat that should receive the reports. If this surface
cannot receive pushed messages, ask the user to continue there; never guess a chat ID.
The destination is `"origin"`: Hermes binds it to the chat, including the Telegram
topic or thread, where `/suggestions accept` runs. To send daily and weekly to
different topics, accept each one in its own topic. Accept in a chat, not the CLI or
Desktop: there Hermes uses a configured home channel or delivers nothing. `destination_verified: true`
records the owner's explicit yes in this chat; PA runs no other verification, and
Hermes shows each suggested job before `/suggestions accept`, which is the final check.
After apply, use the existing
`pa(operation="automations", data={"action":"rule","rule_id":"<stable rule id>","rule":{"kind":"cos_daily","accepted":true,"destination":"origin","destination_verified":true,"timezone":"<IANA zone>","accepted_at":"<aware acceptance timestamp>"}})`.
Use `cos_weekly` with its own stable rule ID for weekly; create only the selected kinds.
Rules store intent and create no jobs. Read automation status back, then call
`pa(operation="automations", data={"action":"suggest","native":true})`.
Check that the chosen suggestions actually exist; do not claim they are enabled.

Tell the user: “Run `/suggestions` in Hermes to review pending automations.
Accept daily with `/suggestions accept personal-assistant-cos-daily` and weekly
with `/suggestions accept personal-assistant-cos-weekly`, only for the schedules
you chose, each in the chat or topic that should receive it.” Hermes v0.22.2 accepts an exact title or ID, or the current pending
number (`/suggestions accept N`); re-list after each numbered acceptance because
numbers shift. This is the CLI and gateway chat command, not a shell
`hermes cron` subcommand. Acceptance creates the native job; verify Hermes's
scheduled response and jobs list. Five-minute prechecks use the saved daily or
weekly slot, quiet hours, pause and snooze, with one report per local day/week.
Follow-ups still require a separate owner-approved HeartBeat 2.0 `at` wake in
the same chat; setup creates none.

## Context file and readbacks

Only propose AGENTS.md or another context file for an actual project rule, and
only the file Hermes actually loaded. Do not guess a workspace path or add
personal routines to project instructions. Respect host approval for protected files.
PA reads each written file back and hashes its saved bytes (only the marked PA
block, including markers, for SOUL.md). Propose only changed targets; use `writes: []` when nothing
changes. Include PA preference changes as `pa_preferences`, apply them through
`pa automations` action `preferences`, and verify its status without a file readback.
After all proposed writes succeed, call `pa setup applied` with readbacks such as:
`[{"target":"user_memory"},{"target":"soul_section"},{"target":"manual_skill","skill":"<name>"}]`.
Include exactly the proposed FILE targets (`user_memory`, `soul_section`,
`manual_skill`, `context_file`). The manual accepts its skill name or a `path`
inside the profile's `skills` directory; `context_file` requires an absolute
`path` to the approved file. Never compute or invent hashes: PA reads and hashes.
If PA reports a failed readback, fix the write and call again.
No unproposed or missing targets; when there are
no file targets, use `readbacks: []`. Keep failures and pending writes visible;
never mark incomplete work applied. For partial approval, first revise `propose`
to the approved subset. Verify job changes separately through their own tools.

## Privacy

No credentials, passport details, payment details, or raw inbox text in any file
or setup answer. Save short safe facts and source roles, not sensitive source
contents. The private manual reaches the configured model when loaded; never
export a user's populated manual as a template.
