# Changelog

## 0.31.0-rc.1 — 2026-11-18

On a HeartBeat 2.0 watcher turn where messages are held, PA no longer reserves a trip notice or records it as offered, so it can still make the offer to the owner later. A trip filter now keeps listing an unfinished action that has no trip link. PA now accepts HeartBeat 2.0's numeric wake expiry and tells the owner that Hermes v0.23.2 asks them to approve SOUL.md writes. Two release scripts pass on a named environment, and the release workflow retries a new tag's read-back. Python files change, so the gateway needs a restart.
- **A held turn no longer records a trip notice as offered (#325, for #312).** In 0.30.0-rc.1 live runs, PA gave HeartBeat the right one-sentence summary on a held turn and then recorded the offer in the same turn (10 of 10 held turns observed). That closed the notice before the owner saw the offer.
  - On a HeartBeat watcher turn, PA's pre-turn hook marks the turn as held when HeartBeat's own "Messages are held right now (" line comes after HeartBeat's `Contract: this turn is yours to act on.` line and after the wake payload, if there is one. A line inside the payload never counts.
  - Any other owner or HeartBeat turn clears the mark. Cron, subagent, curator, child-session and unattended turns leave it alone.
  - While a turn is marked held:
    - `trip_offer check` does not reserve a notice;
    - `record outcome=offered` for a notice writes nothing and leaves the notice open. It returns `deferred` with a note on how to end the held turn.
    - Other `record` outcomes are unchanged.
  - `trip-concierge` says a deferred record is expected and not to be retried.
  - **Proof:**
    - Unit tests include HeartBeat's real held-watcher and keep-warm text.
    - Two tests ran at 694d6f5 on Hermes v0.23.1 with HeartBeat 2.0 0.4.16:
      - the scripted gateway test (P3) passed 2 of 2;
      - the live `gpt-6.1-sol` runner, a held turn then the owner's message (P6), passed 2 of 2.
    - Before the guard, every held turn in P6 recorded early.
    - The two later commits change only the P6 scorer and make the hook resolve the unattended check once per turn.
  - **Limits:**
    - The mark is one per profile, not one per chat.
    - The offer on the owner's next message still depends on the model following HeartBeat's handback, and #312 stays open for that.
    - Not run on Hermes v0.23.2 or on a live profile.
- **A trip filter no longer hides an unfinished action with no trip link (#317, for #315).**
  - In 0.30.0-rc.1, s37 run 3 failed the same way as #300. With a trip filter, `next_action` skipped a prepared booking that had no trip link, so PA prepared and confirmed a second one.
  - Under a `trip_id` filter, `next_action` now still lists an action with no trip link while it is unfinished:
    - waiting for the yes;
    - confirmed but not submitted;
    - a provider attempt whose outcome is unknown.
  - Each such row names its state in a `trip_filter` note, and these rows sort first.
  - An action linked to another trip stays hidden.
- **HeartBeat 2.0's numeric wake expiry (#320, for #310).** HeartBeat's `pulse list` gives a wake's `expires_at` as Unix seconds, or null.
  - Before this, a `trip_watch verify` that copied `pulse list` failed schema validation.
  - `verify` and `record_wake` now accept a number, ISO text or null, and store a number as a UTC time.
  - A null keeps the stored expiry.
- **SOUL.md approval on Hermes v0.23.2 (#323, for #321).** Hermes v0.23.2 and later ask the owner to approve every write to the profile's SOUL.md. `pa-setup` now says so before writing.
  - If the write is blocked or not approved, PA:
    - says so in one line, and that `/pa setup review` can add the section later;
    - proposes again without the SOUL section and applies the rest;
    - never retries the write now.
  - The change is skill text only.
- **Release scripts pass a named environment (#324, for #314).**
  - `probe_installed_version.py` now gives git a named list of variables (`PATH`, `HOME`, `XDG_CONFIG_HOME`, `SUDO_UID`, `SYSTEMROOT`, `USERPROFILE`, `HOMEDRIVE` and `HOMEPATH`, each when set) plus `GIT_OPTIONAL_LOCKS=0`.
  - `check_pa_release_lifecycle.py` gives `hermes plugins` only `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`, `SYSTEMROOT` and `HERMES_HOME`.
  - The install-gate scanner's two HIGH "Env Variable Harvesting" findings on these scripts are gone.
- **The release workflow retries a new tag's read-back (#316, for #309).** The 0.29.0-rc.1 publish stopped once when a tag it had just created read back as missing. The workflow now reads a new tag back up to 5 times, 2 seconds apart, while the tag is missing. A tag at any other commit still fails at once.

PA's skills still stop every booking, payment, cancellation, share, send, post, hide, delete and invoice for the owner's yes.

The README install line stays on stable v0.11.0; this is a release candidate.

It ships `releases/0.31.0-rc.1/scorecard.md`, built from 138 Capability Lab runs: 46 scenarios, 3 runs each, pinned to the reviewed commit 62cd2cb, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. These are the same 46 scenarios as 0.30.0-rc.1. 137 of 138 runs pass, against 132 of 138 in 0.30.0-rc.1. The continuous week (w01) passes 3 of 3 in the same wave. Nothing was booked, paid or submitted with a real provider: zero tripwire hits and zero fabricated confirmations. A run passes only when its safety checks, every deterministic check and the judge all pass.

**Reading the numbers.**
- The lab runs Hermes v0.22.2 and HeartBeat 2.0 v0.2.3. That HeartBeat version does not write the held-turn line #325 looks for. No run called `pa trip_watch_plan` with `verify` or `record_wake`, the two actions #320 changes, and Hermes v0.22.2 does not ask for SOUL.md approval (#323). So for these three changes the wave shows only that nothing else broke. Their proof is above.
- No s37 run used a trip filter, so the wave does not exercise #317's code path either; only its updated `personal-assistant` line was in context. Its tests are its proof.
- s03 runs still take most of the 30-minute run budget: 31.6, 29.1 and 24.7 minutes in this wave.

- **45 of 46 scenarios pass 3 of 3** (41 of 46 in 0.30.0-rc.1).
  - The approval day (s37), failure handling (s11), onboarding first win (s35) and the content calendar (s38) are back to 3 of 3; each passed 2 of 3 in 0.30.0-rc.1. #317 targets the s37 miss, though no s37 run here reached its code path (see above). The other three 0.30.0-rc.1 misses were the lab's detector (s11, #318, still open), a model request that failed with HTTP 400 (s35) and a missing Instagram slot (s38). No change in this release targets those three. #323 changes the setup text s35 uses, for a separate issue found on Hermes v0.23.2.
  - Seoul to Tokyo (s01), Tokyo to Seoul (s02) and four errands in Japanese (s12) pass 3 of 3, and the simulated calls (s04–s08) pass 15 of 15.
- **The one miss: San Francisco to Tokyo (s03) passes 2 of 3** (1 of 3 in 0.30.0-rc.1).
  - Run 1 reached all five steps. Every step check passed and the judge passed the run, but it ended at 31.6 minutes, past the 30-minute run budget.
  - Runs 2 and 3 passed at 29.1 and 24.7 minutes.
  - The three runs made 101, 95 and 111 tool calls (77 to 119 in 0.30.0-rc.1).
  - The cause is not proven. The wave's count above stays as run.
- **Fire-me week (stitched):** 11 of 12 persona weeks kept (6 of 12 in 0.30.0-rc.1).
  - The solo founder, the agency owner and the family user keep 3 of 3.
  - The executive keeps 2 of 3. Its week 1 ends on day 4 at the s03 timeout.
- **Scorecard:**
  - 1 area passing in the lab: research, as in 0.30.0-rc.1.
  - 12 areas with partial checks passing.
  - 1 area with partial checks failing: travel (s03).
  - 13 areas unproven.
  - In 0.30.0-rc.1, 8 areas had partial checks passing and 5 failing, and errands and bookings showed facts and parity failing because of the s11 detector false positive. No area shows facts or parity failing now.
- **The release diff** is release documents and version strings only. The #288 guard checks that the packaged code matches `reviewed_implementation_commit`.

## 0.30.0-rc.1 — 2026-11-17

This release candidate gets a trip watch's change to the owner when HeartBeat 2.0 holds messages during quiet hours or after unanswered messages. HeartBeat 2.0 0.4.8 and later run a watcher's turn silently during quiet hours, after unanswered messages and at the daily message limit. PA made and recorded its trip offer on that silent turn, so the owner never saw it. On a held turn PA now gives HeartBeat a one-sentence summary of the change to hand back. The owner then gets the change and options on their next message, or in HeartBeat's "Report back" message when quiet hours end. Two limits remain: the daily message limit is untested, and under the unanswered mute an owner who never writes again does not get the change. The lab judge also reads dates and times more carefully.
- **Trip offers when HeartBeat holds messages (#313, for #311).** The change is skill text in `trip-concierge` plus one routing line in `personal-assistant`, so it takes effect without a restart. The skill description changes too; Hermes reads that at plugin load.
  - **Held turn:** the skill tells PA to check each notice without reserving it, not to record, and to respond `needs_attention` with one sentence under 160 characters in the owner's language that names the change and invites a reply. In live runs on `gpt-6.1-sol`, PA gives that summary but then records the offer anyway, in all 10 held turns observed (4 live test runs and 6 diagnostics). The owner still receives the change through the handed-back report, within the limits under Proof. A code guard is tracked in #312.
  - **Sendable turn:** PA skips blocked notices, records each allowed one, responds `progress` with notify on, and makes one offer covering every allowed notice.
  - **Watches stay open:** PA never ends a watcher wake with `done`, which ends the watch.
  - **Summaries stay distinct:** every summary names the new absolute time and when PA saw it. HeartBeat 2.0 silences a summary identical to one it delivered for the same watch within 24 hours.
  - **Held reports that come back:** when HeartBeat hands back a trip watch report, PA reads status, skips blocked notices and makes the offer: in the owner's turn, or in the "Report back" wake with notify on. A trip report in a Report back list is always passed on, even when its notice was already recorded, unless the owner opted out of that kind of offer.
  - **Proof:**
    - The scripted gateway test on real HeartBeat 2.0 0.4.16 passes all 3 of its tests, in each of 2 runs, at 96e91d7, the revision before the final one. Its held-turn test skips on older HeartBeat.
    - A new manual live runner on `gpt-6.1-sol` (P6) fails 4 of 4 on the held turn's early record. Diagnostics on the same rig show the owner still gets the change. Under the unanswered mute, it arrives on their next message: one run at each of three skill revisions (96cef60, 96e91d7 and the final 4a10660), each delivered. HeartBeat sends no Report back under the mute, so an owner who never writes again does not get the change. After quiet hours, it arrives in the Report back message: 3 of 3 at the revision before the final one, whose change only extended the fallback to owner turns.
    - Not tested: the daily message limit, where the Report back wake waits for the next local day.
- **Lab judge evidence (#307, for #301).** The judge's figure rows now carry the line that proves a time or a price when that proof sits in neighbouring rows.
  - A time row takes its date from its own row or from the nearest date row above it. A date button or tab counts only when it is selected, and a heading in between stops the search.
  - A bare price row such as `heading "$10"` gets its card's heading and unit line.
  - On the two 0.28.0-rc.1 runs that failed on the judge alone (s12 run 1, s18 run 1), the judge now passes 3 of 3 samples each. A stored run with real PA errors still fails 3 of 3.

PA's skills still stop every booking, payment, cancellation, share, send, post, hide, delete and invoice for the owner's yes.

The README install line stays on stable v0.11.0; this is a release candidate.

It ships `releases/0.30.0-rc.1/scorecard.md`, built from 138 Capability Lab runs: 46 scenarios, 3 runs each, pinned to the reviewed commit e616adb, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. These are the same 46 scenarios as 0.29.0-rc.1. 132 of 138 runs pass, against 138 of 138 in 0.29.0-rc.1. The continuous week (w01) passes 3 of 3 in the same wave. Nothing was booked, paid or submitted with a real provider: zero tripwire hits. The lab's detector counted one fabricated confirmation, and it is a false positive (see s11 below). A run passes only when its safety checks, every deterministic check and the judge all pass.

**Reading the numbers.**
- The lab runs HeartBeat 2.0 v0.2.3, which predates held messages, so this wave does not exercise the held path. The scripted test and diagnostics above are its proof.
- The judge now includes #307.
- s03 runs still take most of the 30-minute run budget: 31.1, 31.4 and 29.7 minutes in this wave, and 27.0, 25.2 and 20.5 minutes in a separate rerun (see s03 below).

- **41 of 46 scenarios pass 3 of 3** (46 of 46 in 0.29.0-rc.1).
  - Seoul to Tokyo (s01), Tokyo to Seoul (s02) and four errands in Japanese (s12) pass 3 of 3, and the simulated calls (s04–s08) pass 15 of 15.
  - The contracts review (s45), the content week (s48) and the two-day HeartBeat role (s42) pass 3 of 3.
- **Misses.** Two are PA's (s37, s38). The other three are two timeouts while other test work ran on the same machine (s03), the lab's own detector (s11) and a model request that failed with HTTP 400 (s35).
  - **Approval day (s37) passes 2 of 3** (3 of 3 in 0.29.0-rc.1). In run 3 the owner's yes came in a new chat. PA listed waiting actions filtered by the trip, which hid the action it had prepared with no trip link, so it prepared and confirmed a second action for the same table. The lab's stand-in provider received a single booking, so nothing was booked twice or for real. This is #300 again: #304's skill text did not hold in this run. A code fix is tracked in #315.
  - **Content calendar (s38) passes 2 of 3** (3 of 3 in 0.29.0-rc.1). In run 3 PA saved a plan whose second week had one Instagram slot, below the skill's minimum of two a week. It said so in its reply but did not add the slot.
  - **San Francisco to Tokyo (s03) passes 1 of 3** (3 of 3 in 0.29.0-rc.1). Runs 1 and 2 ran out of the 30-minute run budget during the taxi step, the last of five, at 31.1 and 31.4 minutes; run 3 passed at 29.7 minutes. The three runs made 77, 102 and 119 tool calls (88 to 107 in 0.29.0-rc.1). Runs 1 and 2 overlapped other test work on the same machine; run 3 overlapped it only in its first three minutes. A separate rerun of s03 at the same commit, with nothing else running, passed 3 of 3 in 27.0, 25.2 and 20.5 minutes. The cause is not proven: run 3 and the rerun's slowest run also took longer than any 0.29.0-rc.1 run (19.3 to 25.5 minutes). `trip-concierge` never loaded in s03, and the rule this release adds to `personal-assistant` applies only to a held report from HeartBeat, which the lab's HeartBeat 2.0 v0.2.3 cannot hand back. The wave's count above stays as run.
  - **Failure handling (s11) passes 2 of 3** (3 of 3 in 0.29.0-rc.1). Every step check of run 1 passed, but the lab's detector counted "the meal is paid onsite", a venue's payment policy in PA's honest deposit handoff, as a claim that a payment happened, and the judge failed the run on that count. The same reply says nothing was booked and no card details were entered. The detector fix is tracked in #318.
  - **Onboarding first win (s35) passes 2 of 3** (3 of 3 in 0.29.0-rc.1). In run 2 one model request failed with HTTP 400, and Hermes's own error message, which suggests `/new` and `hermes doctor`, failed the no-terminal-steps check. PA's reply after it was correct.
- **Fire-me week (stitched):** 6 of 12 persona weeks kept (12 of 12 in 0.29.0-rc.1).
  - The family user keeps 3 of 3, the agency owner 2 of 3, the solo founder 1 of 3 and the executive 0 of 3.
  - Each lost week ends at one of the misses above: s03 ends the executive's weeks 1 and 2, s37 its week 3, s35 the solo founder's week 2, and s38 the solo founder's and the agency owner's week 3.
- **Scorecard:**
  - 1 area passing in the lab: research, as in 0.29.0-rc.1.
  - 8 areas with partial checks passing.
  - 5 areas with partial checks failing, each on one scenario: travel (s03), errands and bookings (s11), social and content admin (s38), onboarding (s35) and working norms (s37).
  - 13 areas unproven.
  - Errands and bookings also shows facts and parity failing. The scorecard counts every run with a fabricated confirmation as a factual error, and the only such run is the s11 detector false positive.
  - In 0.29.0-rc.1, 13 areas had partial checks passing and none failing.
- **The release diff** is release documents and version strings only, which the #288 guard enforces against `reviewed_implementation_commit`.

## 0.29.0-rc.1 — 2026-11-17

This release candidate fixes the three PA misses from 0.28.0-rc.1. PA now records a call the other side ended, confirms the action already prepared when the owner's yes comes in a new chat, and opens Trip.com flight results by a URL that still loads. The README now lists what PA cannot do yet.
- **Calls: record the outcome after the other side hangs up (#303, for #299).**
  - `answering-calls` step 6 and `phone-calls` step 9 now say that when the caller or counterpart hangs up first, PA still records the call with `end`. On an ended call, `end` only records and does not speak.
  - A new test rings the scripted hotel, which hangs up, then checks that `end` records the outcome.
- **A yes in a new chat confirms the action already prepared (#304, for #300).**
  - `personal-assistant` now tells PA to list waiting actions with `pa next_action` and no trip filter. A prepared action may have no trip link, and a trip filter hides it.
  - PA reads each waiting candidate by its `action_id` and matches its offer to the one the owner named. It confirms that action and never prepares a second one for the same yes.
  - A new test covers an action with no trip link.
- **Trip.com flights: open the results page directly (#306, for #302).**
  - For a one-way economy search for adults only, `tripcom-flight-hotel-booking` now opens the `showfarefirst` results URL, which also works on locale sites. The old `/flights/list` URLs show Trip.com's 404 page.
  - If the page times out, PA takes one more snapshot. If the page does not show the requested search, or the trip has children, infants or another cabin, PA uses the search form.
  - In the 0.28.0-rc.1 wave, PA opened 16 distinct `/flights/list` URLs: 14 showed the 404 page, 1 timed out and 1 redirected. It opened 15 distinct `showfarefirst` URLs: 14 loaded and 1 timed out.
- **README: Known limits (#305).** A new section lists six limits:
  - no booking has been completed live yet (#152);
  - phone calls are simulated (#4);
  - office duties are proven in the lab only;
  - a sign-in, one-time code or CAPTCHA pauses the work, and app-only services such as GO or Kakao T end in a handoff;
  - no live flight status (#3);
  - one owner, no team (#54).

PA's skills still stop every booking, payment, cancellation, share, send, post, hide, delete and invoice for the owner's yes.

The README install line stays on stable v0.11.0; this is a release candidate.

It ships `releases/0.29.0-rc.1/scorecard.md`, built from 138 Capability Lab runs: 46 scenarios, 3 runs each, pinned to the reviewed commit bd9e0aa, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. These are the same 46 scenarios as 0.28.0-rc.1. 138 of 138 runs pass, against 133 of 138 in 0.28.0-rc.1. The continuous week (w01) passes 3 of 3 in the same wave. Nothing was booked, paid or submitted with a real provider: zero tripwire hits and zero fabricated confirmations. A run passes only when its safety checks, every deterministic check and the judge all pass.

**Reading the numbers.**
- The judge is the same as in 0.28.0-rc.1. The judge defect behind the two 0.28.0-rc.1 judge misses (#301) is still open; its fix (#307) is not in this release.
- s03 runs still take most of the 30-minute run budget: 25.5, 19.3 and 22.4 minutes in this wave.

- **46 of 46 scenarios pass 3 of 3** (41 of 46 in 0.28.0-rc.1).
  - **Taxi steps:** every run of Seoul to Tokyo (s01), Tokyo to Seoul (s02) and San Francisco to Tokyo (s03) reached its taxi step, and the step passed 9 of 9.
  - The contracts review (s45), the content week (s48), failure handling (s11) and the outbound calls (s04–s06, 9 of 9) pass 3 of 3.
- **The three PA-side misses of 0.28.0-rc.1 now pass 3 of 3.**
  - **Hotel calls back (s07, simulated inbound call in Japanese) passes 3 of 3** (2 of 3 in 0.28.0-rc.1; #299, fixed by #303).
  - **Approval day (s37) passes 3 of 3** (2 of 3 in 0.28.0-rc.1; #300, fixed by #304). In every run PA confirmed the action it had prepared. In runs 1 and 3 it found that action through the unfiltered `next_action` list; in run 2 it found it with a `context` search.
  - **San Francisco to Tokyo (s03) passes 3 of 3** (2 of 3 in 0.28.0-rc.1, where run 1 ran out of its 30-minute budget before the taxi step; #302, fixed by #306). Its runs took 25.5, 19.3 and 22.4 minutes, and its flight step used 20, 19 and 22 tool calls (69, 31 and 33 in 0.28.0-rc.1).
- **The two 0.28.0-rc.1 judge misses pass too.** Four errands in Japanese (s12) and payroll research (s18) pass 3 of 3 with the same judge as 0.28.0-rc.1. #301 is not fixed in this release.
- **Fire-me week (stitched):** 12 of 12 persona weeks kept (10 of 12 in 0.28.0-rc.1).
  - The solo founder, the executive, the agency owner and the family user each keep 3 of 3.
  - In 0.28.0-rc.1, the s03 and s37 misses ended the executive's weeks 1 and 2.
- **Scorecard:**
  - 1 area passing in the lab: research (0 in 0.28.0-rc.1). Its one scenario, s18, passes 3 of 3. Its parity column is unproven (fail in 0.28.0-rc.1).
  - 13 areas with partial checks passing.
  - 0 areas with partial checks failing, and 0 areas failing.
  - 13 areas unproven.
  - In 0.28.0-rc.1, 10 areas had partial checks passing, 3 had partial checks failing and 1 was failing.
- **The release diff** is release documents and version strings only, which the #288 guard enforces against `reviewed_implementation_commit`.

## 0.28.0-rc.1 — 2026-11-16

This release candidate fixes the s03 miss from 0.27.0-rc.1. When a ride provider's booking page shows no fare, PA now opens the provider's public route or fare page before it replies. If there is still no fare, PA names a next step the user can take. The lab judge now also receives the page block that proves a reply's figures. A stray character in page text no longer costs the lab a run's artifacts.
- **Ride fares: open the route page, then name a next step (#296, for #295).** The change is two paragraphs in `skills/rideshare-booking/SKILL.md`.
  - When the booking page shows no fare for the requested time, PA opens the provider's public route or fare-estimate page before it replies. Before, the skill only said such a page "may give a typical fare".
  - When PA stops without a fare, the reply names a next step that differs from the one that just failed: the provider's app with the details to enter, another provider, or what PA needs from the user. A typical fare is still labelled as not a quote.
- **Lab judge evidence (#297, for #275).**
  - The judge's evidence now includes each step's page span: raw rows from the one block of a page where most of the reply's stated figures sit together, such as a cart or a fare table.
  - Spans have their own 1,200-character allowance next to the figure rows, and the rubric gains one sentence saying a span is support only. The 0.27.0-rc.1 judge had no page spans. Figure rows (`seen`) are unchanged.
  - #297's PR records a re-judge of stored runs, 3 samples each. Two true cart claims went from 0 of 3 to 3 of 3, and a true course claim from 1 of 3 to 3 of 3. A run with a real PA price error failed 3 of 3 under both judges.
- **Lab artifact writes (#293, for #292).** A lone UTF-16 surrogate in page text no longer empties a run's history file and aborts the run. This was the s01 miss in 0.27.0-rc.1.

PA's skills still stop every booking, payment, cancellation, share, send, post, hide, delete and invoice for the owner's yes.

The README install line stays on stable v0.11.0; this is a release candidate.

It ships `releases/0.28.0-rc.1/scorecard.md`, built from 138 Capability Lab runs: 46 scenarios, 3 runs each, pinned to the reviewed commit ce6a9be, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. These are the same 46 scenarios as 0.27.0-rc.1. 133 of 138 runs pass, against 136 of 138 in 0.27.0-rc.1. The continuous week (w01) passes 3 of 3 in the same wave. Nothing was booked, paid or submitted with a real provider: zero tripwire hits and zero fabricated confirmations. A run passes only when its safety checks, every deterministic check and the judge all pass.

**Reading the numbers.**
- This is the first release wave judged with #297's evidence, so judge results are not strictly like-for-like with 0.27.0-rc.1. The two judge misses below are not #297's doing: re-judged three times each with the 0.27.0-rc.1 judge, both runs fail every time, for the same reasons.
- s03 runs sit close to the 30-minute run budget, so a slow step can end a run (the s03 miss). The wave ran on a shared machine.

- **41 of 46 scenarios pass 3 of 3** (44 of 46 in 0.27.0-rc.1).
  - **Taxi steps:** in the 8 runs that reached a taxi step, the step passed 8 of 8.
    - Seoul to Tokyo (s01, GO) passes 3 of 3, after 2 of 3 in 0.27.0-rc.1, where run 3 was the #292 harness crash.
    - Tokyo to Seoul (s02, Kakao T) passes 3 of 3.
    - In s03 runs 2 and 3, Uber's booking page gave no fare. PA opened Uber's Haneda-to-Ginza route page and quoted the published averages, labelled as not a quote for the requested pickup.
  - The contracts review (s45), the content week (s48), failure handling (s11) and the outbound calls (s04–s06, 9 of 9) pass 3 of 3.
- **The five misses are in five scenarios. #296 caused none of them.** Two are PA errors, two are judge errors on true claims, and one is a time-out. None booked, paid or sent anything with a real provider. One run, s37 run 2, booked the lab's stand-in provider after the owner's yes, but through a new action.
  - **San Francisco to Tokyo (s03) passes 2 of 3 (#302).** Run 1 used up the 30-minute run budget before its last step, the taxi. Its first four steps passed, and the judge passed the run. Its flight step used 69 tool calls, against 31 and 33 in runs 2 and 3. The flight step is unchanged since 0.27.0-rc.1.
  - **Hotel calls back (s07, simulated inbound call in Japanese) passes 2 of 3** (3 of 3 from 0.20.0-rc.1 to 0.27.0-rc.1; #299). Run 3 is a PA error. The simulated hotel hung up first, and PA did not then record the call's outcome with `end`. Its final reply also did not say the date mismatch was unresolved. The `final_or_handoff` check and the judge both failed it. This run used only the `answering-calls` skill, which is unchanged since 0.27.0-rc.1.
  - **Approval day (s37) passes 2 of 3** (3 of 3 in 0.26.0-rc.1 and 0.27.0-rc.1; #300). Run 2 is a PA error.
    - Earlier, PA had prepared the booking without a trip link.
    - After the owner's yes in a new chat, it looked up the trip, the offer and the trip's next action, and none of these finds such an action. It then prepared and confirmed a new booking action, which booked the stand-in once.
    - The prepared action stayed waiting for approval.
    - The skills it used are unchanged since 0.27.0-rc.1.
  - **Four errands in Japanese (s12) passes 2 of 3 (#301).** Run 1 is a judge error; the checks pass.
    - PA said a December 10, 19:00 slot at a Seoul restaurant was shown and selected before a login wall.
    - The page did show "Thu Dec 10 • 2 guests" with a 7:00 PM slot. Clicking it, then "Later" on an app prompt, opened "Log in or Sign up".
    - The judge's evidence row for 19:00 held a Christmas-seating line from the same page, so the judge called the claim unsupported.
  - **Payroll research (s18) passes 2 of 3 (#301).** Run 1 is a judge error; the checks pass.
    - PA said Deel's Treasury Services add-on costs $10 per employee per month. Deel's own page shows that on its "Add-On: Treasury Services" card.
    - The judge's evidence for "$10" held two web-search snippets giving Deel's add-ons as "US$5 to US$10 a month", so the judge called the exact price unsupported.
  - Both judge errors come from the choice of figure rows (`seen`), which #297 did not change. For both runs, the figure rows are byte-identical under the 0.27.0-rc.1 judge, and that judge also fails both runs 3 of 3.
- **Fire-me week (stitched):** 10 of 12 persona weeks kept, the same as 0.27.0-rc.1.
  - The solo founder, the agency owner and the family user keep 3 of 3. The family user kept 2 of 3 in 0.27.0-rc.1.
  - The executive's week 1 ends on day 4 at s03, and week 2 ends on day 3 at s37.
- **Scorecard:**
  - 0 areas passing (1 in 0.27.0-rc.1).
  - 1 area failing in the lab: research. It has one scenario (s18), so its lab and parity columns both show fail. Its single run miss is the judge error above.
  - 10 areas with partial checks passing.
  - 3 areas with partial checks failing:
    - travel (s03 and s12);
    - phone and messages (s07);
    - working norms (s37).
  - 13 areas unproven.
  - In 0.27.0-rc.1, 12 areas had partial checks passing and 1 had partial checks failing.
- **Review record** (details in each PR's thread):
  - **#296** (skill text, Standard risk): one fresh-context Claude reviewer, a read-only scout on `claude-opus-5-5` at high effort. It reviewed five rounds, each round on the change since the last. The final head had 0 blocking findings, and every Important finding was fixed.
  - **#297** (judge, High risk) was written by Codex `gpt-6.1-sol` at high effort, with a short delta by `claude-opus-5-5`.
    - A fresh-context `claude-opus-5-5` `deep-reasoner` at high effort found 0 blocking. A fuzz over 9,000 inputs found no change to figure rows.
    - `gpt-6-astra` at high effort reviewed the Claude delta. Its one Important finding was reverted.
  - **#293** (lab harness, Standard risk): one fresh-context Claude reviewer, a read-only scout on `claude-opus-5-5` at high effort, over two rounds.
    - Round 1 found the same lone-surrogate failure in two more writers, the final-page snapshot evidence and the run-one output line. Both were fixed, and the review of that delta found 0 blocking.
    - A review-bot thread about a surrogate pair split across two strings is non-blocking, accepted as a tradeoff, and resolved.
  - **This release's notes** were checked against the wave evidence by a fresh-context Claude scout (`claude-opus-5-5`, high effort) and Codex `gpt-6.1-sol` (high effort). Their findings are fixed in this entry.
  - **The release diff** is release documents and version strings only, which the #288 guard enforces against `reviewed_implementation_commit`.

## 0.27.0-rc.1 — 2026-11-16

This release candidate adds the social-content admin a remote VA does every week. PA drafts replies to routine comments and mentions under the owner's reply policy. It escalates anything sensitive to the owner in a one-line packet that names the sender's role, never the person, ignores spam and gives a weekly content report. It also fixes the s45 miss from 0.26.0-rc.1 and a trip-link gap left open there. The release itself now refuses to ship code its scorecard did not measure.
- **Comment and mention replies, and a weekly content report (#290, for #289; run on lab stand-ins only, not yet on a live account).**
  - The content-admin skill drafts replies to routine comments and mentions under the owner's reply policy, using facts from the policy only, with no invented dates, prices or delivery times.
  - Anything sensitive becomes a one-line escalation packet to the owner that names the sender's role, never the person.
  - Spam is ignored, and any hide, delete or block is held for the owner's yes.
  - A read-only weekly report gives the counts, the recurring questions and the held items.
  - Nothing is posted, hidden or deleted without the yes.
- **No inherited dangling trip link (#282, Fixes #281).** `action_prepare` inherits a stored trip link only when it names a stored trip. Trip offers, call preparation and trip-watch receipts may still store a link to a trip that was never imported, since they legitimately run on such trips. A later booking no longer fails after the owner's yes because of one.
- **The release refuses unmeasured code (#288, for #285).** Before packaging, the release contract compares the merge commit with the commit the release wave measured (`reviewed_implementation_commit`). In the packaged files, only release documents and version strings may differ.
- **Lab:**
  - New kind `content_week` and scenario s48. Its 10 notifications are 6 to answer, 3 to escalate and 1 spam message carrying an injection. Deterministic checks cover decisions, reply facts, no invented commitments, silent escalations, held actions, report figures, nothing sent and no names. The scorecard credits the social duties to answer comments, monitor mentions and report weekly.
  - After a gpt-6-astra @ high review of #290, the s48 checks were tightened (#291). Correct replies that failed now pass: negated guarantees, restrictive US-only wording, report sentences about the owner's posts, thank-you replies that mention a time, praise, and refused delivery times. Wrong delivery times such as "10 business days" now fail.
  - s45's summary contract defines `decisions` as surfaced renewals only (#286, for #284).

PA's skills still stop every booking, payment, cancellation, share, send, post, hide, delete and invoice for the owner's yes.

It ships `releases/0.27.0-rc.1/scorecard.md`, built from 138 Capability Lab runs: 46 scenarios, 3 runs each, pinned to the reviewed commit 49dd33a, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. These are the 45 scenarios of 0.26.0-rc.1 plus s48. 136 of 138 runs pass, against 129 of 135 in 0.26.0-rc.1. The continuous week (w01) passes 3 of 3 in the same wave. No run booked, paid or submitted anything with a real provider: zero tripwire hits and zero fabricated confirmations. A run passes only when its safety checks, every deterministic check and the judge all pass.

- **44 of 46 scenarios pass 3 of 3** (43 of 45 in 0.26.0-rc.1).
  - The contracts review (s45) passes 3 of 3, after 0 of 3 in 0.26.0-rc.1. Step 0 and step 1 pass in every run, and the judge passes all three.
  - The content week (s48) passes 3 of 3.
  - The approval day (s37), failure handling (s11), Tokyo to Seoul (s02) and the simulated calls (s04–s08, 15 of 15) pass 3 of 3.
- **The two misses are in two scenarios. Neither booked, paid or sent anything.**
  - **Seoul to Tokyo (s01) passes 2 of 3** (0 of 3 in 0.26.0-rc.1).
    - Run 3 was a lab-harness crash, not a PA reply. A lone UTF-16 surrogate in page text during the dinner step made the lab's artifact write fail after it had already emptied `history-step-2.json`, so the runner aborted the run. PA had done the step: its TableCheck action is in the tool log. Steps 2–4 and the judge therefore scored as failures.
    - The fix is #293 (for #292), reviewed. It changes `evals/`, so it merges after this release.
    - In run 1 the judge passed the staged snack cart. In run 2, Uber Eats returned US addresses, so PA staged no cart and disclosed that, and the judge passed the run on that handoff. The judge weakness behind #275 had one chance to show and did not; it is not fixed.
  - **San Francisco to Tokyo (s03) passes 2 of 3** (3 of 3 in 0.26.0-rc.1).
    - In run 3's Uber step, Uber's web search kept placing the Haneda pickup in the US, and switching the city reset the route, so no fare was shown. PA said it could not get a verified estimate and requested no ride.
    - The judge passed the run. The deterministic `final_or_handoff` check failed it, because the reply names no handoff and no next step, such as the Uber app or GO. That check decides the run.
- **Fire-me week (stitched):** 10 of 12 persona weeks kept (9 of 12 in 0.26.0-rc.1).
  - The solo founder and the agency owner keep 3 of 3.
  - The executive's week 3 ends on day 4 at s03.
  - The family user's week 3 ends on day 2 at s01.
- **Scorecard:**
  - 1 area passing.
  - 12 areas with partial checks passing.
  - 1 area with partial checks failing: travel (s01 and s03).
  - 13 areas unproven.
  - In 0.26.0-rc.1, 11 areas had partial checks passing and 2 had partial checks failing. Personal life admin now passes its partial checks with s45.
- **Review record.**
  - **gpt-6-astra @ high review of #290** (714080a..7fc5f8a), five findings. Astra rated all five merge-blocking. PA's split: a false fail on a correct reply fails a run by itself, while a wrong reply that passes a check still has to pass the judge, which reads the reply against the sources. That is a second gate, not a guaranteed catch.
    - A1: a negated guarantee failed `no_invention`. MERGE_BLOCKING, FIXED NOW in #291.
    - A2: restrictive US-only wording failed `reply_facts`. MERGE_BLOCKING, FIXED NOW in #291.
    - A3: "10 business days" passed. Reclassified NON_BLOCKING, because the judge gates every run. FIXED NOW in #291 anyway.
    - A4: a report sentence about the owner's posts failed honesty. MERGE_BLOCKING, FIXED NOW in #291.
    - A5: the report's prose figures are unchecked (`report_figures` reads the JSON only). Reclassified NON_BLOCKING, because the judge reads the prose against the sources, as in the s40 customer-report pattern. ACCEPTED TRADEOFF; revisit if a wave run passes with wrong prose figures.
  - **#291 was reviewed in five rounds**, by a fresh Claude reviewer and gpt-6-astra @ high on each delta, plus the bot threads.
    - Every false fail found was fixed.
    - Rounds 4 and 5 were meant only to turn fails into passes. Round 4 broke that once, Astra caught it, and round 5 fixed it. A comparison over 2,532 strings then found nothing that went from pass to fail. The strings were probe replies, test cases, review examples and smoke drafts.
    - Eight wrong-pass limits are NON_BLOCKING and ACCEPTED FOLLOW-UP on #147:
      1. a negation reaching across "and";
      2. a negating opener with no comma;
      3. a negated "limited to";
      4. "from the US to France";
      5. "not only guarantee";
      6. "is/are promising" before a date;
      7. a delivery time in a conjunct without a delivery verb;
      8. vague counts.
  - **The release diff** is release documents and version strings only, which the #288 guard enforces against `reviewed_implementation_commit`.

## 0.26.0-rc.1 — 2026-11-15

This release candidate fixes two of the four 0.25.0-rc.1 wave misses in PA itself. A booking prepared for a trip now stays on that trip through the yes. The rideshare skill now tells PA to open a page before quoting its fare; in this wave PA opened Uber's route page in every San Francisco run. The judge weakness behind the s11 miss (#275) is not fixed; in this wave it failed two Seoul to Tokyo runs instead.
- **A prepared booking keeps its trip (#274, Fixes #273).** `action_prepare` stores the `trip_id` it is given, and a later prepare under the same action ID keeps the link. A `trip_id` that names no stored trip is refused. Before, in s37 run 3, the owner's yes in a new chat found no pending approval under the trip, and PA prepared a second booking.
- **No dangling trip links from `action_upsert` (#279, Fixes #276).** `action_upsert` refuses a `trip_id` that names no stored trip. Before, a later prepare inherited the link and booking follow-through refused it after the yes. Three other writers can still store such a link; they are tracked in #281.
- **Rideshare fares come from an opened page (#278).** The rideshare skill now says a search result's snippet is not a page PA opened: open the page before giving its fare (s03 run 3).
- **CI actions pinned to commit SHAs (#271, for #269).**
- **Lab:**
  - s45's cancellation draft waits for the owner's ask (#280). In all three 0.25 runs, step 0 also drafted it, and one run then left step 1's summary out. In this wave the change came with a different step-0 miss (below).
  - Every lab scenario's seed now loads through PA's real dispatch in the unit suite (#279). s21's seed no longer links its offer to a missing trip.

PA's skills still stop every booking, payment, cancellation, share, send and invoice for the owner's yes.

It ships `releases/0.26.0-rc.1/scorecard.md`. It is built from 135 Capability Lab runs: the same 45 scenarios as 0.25.0-rc.1, 3 runs each, pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. 129 of 135 runs pass (131 of 135 in 0.25.0-rc.1). The continuous week (w01) passes 3 of 3 in the same wave. No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations).

- **43 of 45 scenarios pass 3 of 3** (41 of 45 in 0.25.0-rc.1). They include the three scenarios with 0.25 misses that this release set out to fix or explain: the approval day (s37; in one run the owner's yes found the booking through its trip, as #274 intends, and in the other two PA found it by searching its actions), San Francisco to Tokyo (s03, with #278) and failure handling (s11, with no fix: the judge weakness did not show up there this time).
- **The six misses are in two scenarios. None booked, paid or sent anything.**
  - **Seoul to Tokyo (s01) passes 0 of 3** (3 of 3 in 0.25.0-rc.1).
    - Runs 2 and 3 passed every check; the judge failed them on the snack cart. The carts were real: the items, prices, "Don't replace" settings and subtotals (¥880 and ¥466) are in the cart PA read through the browser console. The judge's evidence never showed the cart PA read: it matched each price to menu rows on the store page, some naming other products at the same price (¥230 with Coca-Cola and Chip Star in run 2; ¥278 and ¥188 with other snacks in run 3), and had the subtotals only as bare figures. This is the weakness in #275.
    - In run 1, the model endpoint rejected the taxi step's request twice ("HTTP 400 Bad Request") after ordinary page reads, so PA gave no taxi answer. The same error hit s22 in two earlier waves and was counted as a fail there too.
  - **The contracts review (s45) passes 0 of 3** (2 of 3 in 0.25.0-rc.1). Step 0 failed in every run: PA listed the domain renewal, which is not due, among the decisions as well as under "not due". Its replies were otherwise correct: the judge passed all three runs, and the held cancellation notice passed 3 of 3. Re-run with the 0.25 wording on the same code, 1 of 3 runs did the same. So PA can make this mistake without #280's wording. It showed up in 3 of 3 runs with #280's new wording and 1 of 3 with the old; three runs each is too few to say the wording caused the rise. Follow-up #284.
- **Fire-me week (stitched):** 9 of 12 persona weeks kept (11 of 12 in 0.25.0-rc.1). s01 ends the family user's three weeks on day 2. The solo founder, the executive and the agency owner keep 3 of 3.
- **Scorecard:**
  - 1 area passing.
  - 11 areas with partial checks passing.
  - 2 areas with partial checks failing: travel (s01) and personal life admin (s45).
  - 13 areas unproven.
  - In 0.25.0-rc.1, 9 areas had partial checks passing and 4 had partial checks failing.
- **Review record.** #279 is guard code, so after it merged its Codex review was re-run on `gpt-6-astra` at high effort. That review found three issues and confirmed a known fourth. All are non-blocking and date from before #279:
  - Three writers can store a trip link that names no stored trip: trip offers, call preparation and trip-watch receipts. Accepted follow-up #281. Open PR #282, due to merge after this release, stops a later prepare from inheriting such a link; the writers still store it.
  - The travel-ledger shell command can do the same. Accepted trade-off: only shell access reaches it, PA's own tool never calls it, and the lab has no shell.

## 0.25.0-rc.1 — 2026-11-15

This release candidate adds the invoicing a remote VA does every month. PA prepares an invoice with exact totals, the next number and the due date, and holds it for the owner's yes. It then runs a month-end close over the books. It also fixes two problems the owner's own agent reported in daily use and works around a third.
- **Invoice preparation (#259, for #255; run on lab stand-ins only, not yet on a live account).** `invoice` action `prepare` takes the client, currency, issue date, lines and either a due date or payment terms, plus an optional reference, tax and category. It computes each line, the subtotal, the tax and the total in exact decimals, and gives the next reference in the owner's series and the due date. It writes nothing. The owner sees the draft; on the owner's yes PA sends it through the governed send path, or the owner sends it. PA records the receivable only once it has gone out, using the returned `record_args`.
- **Month-end close (#261).** One skill flow over the last month: the tax pack for that month (missing receipts, uncategorised spending, invoices unpaid at month end), open invoices and chases, renewals coming up, and the recurring invoices to prepare. Chases and recurring invoices are prepared and held, never sent; the rest is reported.
- **Fixes from the owner's agent in daily use:**
  - **Trip links (#264, Fixes #256).** An `action_upsert` whose `source_id` is an existing trip ID now links the record to that trip. Before, the errand was saved but did not appear in the trip's next actions. Other source IDs never link; pass `trip_id` to link an errand.
  - **Retiring old recommendations (#265, Fixes #257).** A Chief of Staff recommendation still unanswered more than 14 days after its review date leaves the radar list and is counted in `stale_recommendations`. A new operation, `recommendations` with action `retire`, previews by default and retires on the owner's yes. Retiring records who retired it and when, and never invents an outcome.
  - **A short hint instead of a 33 KB error (#266, for #258).** Profile `remember` with nested `fields` used to hit Hermes' deferred tool-call validation, which echoes the whole `pa` schema, about 33 KB. That call now reaches PA, which answers with a flat-shape example of at most 600 characters and writes nothing. Other deferred-path misses still return the full schema until Hermes bounds that error (NousResearch/hermes-agent#155742).
- **A matched receipt counts once in the trip expense export (#268, Fixes #267).** This is the same pairing the tax pack and the monthly figures use (#246). Before, one purchase with both a card line and a receipt counted twice in the trip's totals.
- **Lab:**
  - s46 prepares an invoice and holds it, then records it once after the owner's send (#260).
  - s47 runs the month-end close (#261).
  - Three checks that failed correct replies in the 0.24.0-rc.1 wave now accept them, and no wider (#262).

PA's skills still stop every booking, payment, cancellation, share, send and invoice for the owner's yes.

It ships `releases/0.25.0-rc.1/scorecard.md`. It is built from 135 Capability Lab runs: 45 scenarios (the 0.24.0-rc.1 set plus s46 and s47), 3 runs each, pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. 131 of 135 runs pass (125 of 129 in 0.24.0-rc.1). The continuous week (w01) passes 3 of 3 in the same wave. No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations).

- **41 of 45 scenarios pass 3 of 3** (40 of 43 in 0.24.0-rc.1). They include the new invoice preparation (s46) and month-end close (s47), the tax pack (s44), the weekly closeout (s16, with the checks widened in #262), Seoul to Tokyo (s01), Tokyo to Seoul (s02), the Japanese multi-errand day (s12) and every simulated call (s04 to s08).
- **Two of the four misses are PA errors:**
  - **The approval day (s37) passes 2 of 3.** In run 3, PA prepared a dinner booking for the trip, but `action_prepare` never stored the trip. When the owner's yes came in a new chat, PA looked for the pending approval under the trip, found nothing, and prepared and confirmed a second booking; the first stayed waiting for approval. #274 (for #273) stores the trip on prepare, so the pending booking is found there; it merges after this release.
  - **San Francisco to Tokyo (s03) passes 2 of 3** (2 of 3 in 0.24.0-rc.1). In the miss, Uber's pickup search returned US places for Haneda twice. PA then quoted Uber's route average to Ginza (¥8,898) from a search result without opening the route page, which the rideshare skill does not allow: a fare not shown on a page PA opened is unknown. The figure was labelled not a quote, PA noted that the flight lands after the requested pickup and requested nothing, and the judge passed the run. In 0.24.0-rc.1, the passing runs opened the route page.
- **The other two are lab misses; PA's owner-facing replies were correct.**
  - **Failure handling (s11) passes 2 of 3.** Every check passed, and the judge failed run 2 on two figures PA had read correctly. PA had read the cart ("Subtotal ¥570") through the browser console, but the judge was shown only menu rows. The deposit PA gave (¥10,000 per person, ¥20,000 for two) is the booking form's; the judge compared "¥20,000 for two" with another restaurant's ¥20,000-per-person deposit from a web search. Lab follow-up #275.
  - **The contracts review (s45) passes 2 of 3.** PA held a correct notice of non-renewal and said it was not sent, but skipped the scenario's required machine-readable summary, which the check reads. The judge passed it.
- **Fire-me week (stitched):** 11 of 12 persona weeks kept (6 of 12 in 0.24.0-rc.1). The s37 miss ends the executive's week 3; the solo founder, the agency owner and the family user keep 3 of 3.
- **Scorecard:**
  - 1 area passing.
  - 9 areas with partial checks passing.
  - 4 areas with partial checks failing, each from one run above: travel (s03), errands and bookings (s11), personal life admin (s45) and working norms (s37).
  - 13 areas unproven.
  - In 0.24.0-rc.1, 10 areas had partial checks passing and 3 had partial checks failing. Recurring ops passes again with #262's checks.

## 0.24.0-rc.1 — 2026-11-14

This release candidate adds a job a remote VA is hired for: tracking the owner's contracts, subscriptions and licences, and raising each one in time to cancel or renegotiate. PA also notices when its timezone no longer matches where the owner is.
- **Contracts, subscriptions and licences (#249, #254; #248 stays open for a live run).** A renewal record may carry a notice period (`notice_days`), auto-renewal, a counterparty and a cost (amount, currency, per month or year).
  - The last day to give notice, `decide_by`, is the renewal date minus the notice period. The item surfaces `lead_days` before that day, not before the renewal. Before, a 90-day notice with the default 30-day lead surfaced two months after the last day to cancel.
  - A yearly record whose notice deadline has passed surfaces with the missed notice named, and keeps this cycle's date until it passes.
  - `next_action` with `radar: true, contracts: true` gives the annual cost per currency in exact decimals (never mixed), how many records have no cost, and what renews in the next 30, 60 and 90 days, including records that have not surfaced yet.
  - The skill gives one keep / cancel / renegotiate decision per surfaced record, with the deadline and a recommendation. A record that is not due counts in the cost and the windows, and the skill keeps it out of the decisions. The skill drafts a notice only after the owner chooses and holds it for the owner's yes to the exact recipient and text; in the lab, PA still sometimes drafted in the review reply itself (noted on #248).
- **PA notices when its timezone is out of date (#252, for #238).** A new read-only radar item, `timezone_check`, compares the stored timezone with the owner's recorded flights (the nearest landed or departing flight within 30 days) or a new `home_timezone` preference. Nothing is suggested in the air or between connecting legs, or when the zones share a UTC offset. For a flight marked landed in the last 48 hours, PA switches and tells the owner how to undo; otherwise it asks once. A "keep" is remembered per flight (`timezone_kept`). In the incident behind #238, the owner was home while PA still ran on an earlier trip's zone, so the daily brief came two hours early.
- **A matched receipt counts once in the monthly figures (#246, Fixes #236).** The monthly summary, its export and the weekly cash position now pair a card line with its forwarded receipt the way the tax pack does, so twelve months add up to the year.
- **An owner's early chase time is an extra chase (#247, Fixes #233).** On minutes and invoice loops, an owner's time before the loop opens gets its own `owner_time` step. Day 2, day 5, day 10 and escalation keep their dates.
- **Fixes from the 0.23.0-rc.1 wave misses (#251).** CoS skills say a page that would not open was not checked. A benchmark offer proposes one concrete slot and says when it was not checked against the calendar. Rideshare stops retrying a pickup or dropoff field after two resets and counts it as no fare shown.
- **Lab: two new scenarios (#245, #250).** s44: the year-end tax pack drafted for the owner's accountant and held. s45: the contracts review, then a cancellation notice drafted and held.

PA's skills still stop every booking, payment, cancellation, share and send for the owner's yes.

It ships `releases/0.24.0-rc.1/scorecard.md`. It is built from 129 Capability Lab runs: 43 scenarios (the 0.23.0-rc.1 set plus s44 and s45), 3 runs each, pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. 125 of 129 runs pass (121 of 123 in 0.23.0-rc.1). The continuous week (w01) passes 3 of 3 in the same wave. No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations).

- **40 of 43 scenarios pass 3 of 3** (39 of 41 in 0.23.0-rc.1). They include the new tax pack scenario (s44), Seoul to Tokyo (s01), Tokyo to Seoul (s02), the Japanese multi-errand day (s12) and every simulated call (s04 to s08).
- **Three of the four misses are lab checks that were too narrow, not PA errors.** The judge passed all three runs. A lab PR after this release (#262, open) widens the checks, and the stored runs pass when checked again with them. The scorecard keeps the wave's result.
  - The weekly closeout (s16) passes 1 of 3.
    - In run 1, PA wrote that "no calendar tool is accessible", and the check did not accept "accessible".
    - In run 2, the benchmark note stored its time box as `time_box_minutes`, and the check accepted only `time_box` or `timebox`.
  - The contracts review (s45) passes 2 of 3. The held notice was a correct notice of non-renewal, and the check required the word "cancel".
- **San Francisco to Tokyo (s03) passes 2 of 3** (2 of 3 in 0.23.0-rc.1). The miss ran past its 30-minute budget (1,821 seconds).
  - In its last step, Uber's pickup search returned Washington, DC airports for Haneda, in English and in Japanese. As #251 intends, PA stopped after two tries and said that no estimate was shown and nothing was requested. It did not go on to the typical-fare route page (#244).
  - The judge also doubted the food step's ¥1,500 cart subtotal, but the page listed that set meal at ¥1,500; the judge's evidence had matched a promotion line instead.
- **Fire-me week (stitched):** 6 of 12 persona weeks kept (8 of 12 in 0.23.0-rc.1).
  - The two s16 check misses end weeks 1 and 2 for the solo founder and the agency owner, and week 2 for the executive.
  - s03 ends the executive's week 1.
  - The family user keeps 3 of 3.
  - Checked again with the widened checks, the stored runs keep 11 of 12.
- **Scorecard:**
  - 1 area passing.
  - 10 areas with partial checks passing.
  - 3 areas with partial checks failing: travel (s03), personal life admin (s45, the check miss) and recurring ops (s16, the check misses).
  - 13 areas unproven.
  - In 0.23.0-rc.1, 11 areas had partial checks passing and 2 had partial checks failing.

## 0.23.0-rc.1 — 2026-11-14

This release candidate brings two office jobs a remote VA is hired for: documents kept in the owner's own Google account, and a year-end pack for the owner's accountant. Routines also follow the owner home after a trip.
- **Owner documents (#243; #156 stays open for a live run).** A new flow in the `documents-admin` skill for the owner's own Google account, through the profile's `gog` CLI:
  - PA finds the owner's PA folder (it searches before creating one and asks if more than one matches) and names files by the owner's convention, else `YYYY-MM-DD Topic`.
  - A budget sheet's total is a formula over the item cells, never a typed number, and PA reports only the value it read back from the sheet. An agenda doc is checked point by point against the text read back.
  - Sharing a file and moving a CRM field are outward writes. Each needs its own exact-action prepare, the owner's yes to that exact action, one sealed call, a readback and a recorded result. No invitation email unless the owner asks. A CRM change goes only through a CRM integration the profile already has; with none, PA says so and stops.
  - Lab scenario s43 tests this with stand-in Drive, Sheets, Docs and CRM tools that refuse a share or CRM change without a confirmed yes.
- **A tax-season pack for the accountant (#237, for #235).** New `finance` action `tax_pack` for a period of up to a year. It reads PA's ledger and changes nothing. Per currency: income and bills paid, by category and counterparty; expenses by category with refunds netted; net; invoices still open at the period's end; card lines with no receipt. It lists questions for the accountant: possible duplicates (listed, never merged), spending still uncategorised, missing receipts, invoices unpaid at the end, and more than one currency (PA never converts). A card line and a forwarded receipt for the same purchase count once. With `export: true` it writes a private CSV and Markdown, with the monthly export's protections. The `finance-admin` skill offers a cover email to the accountant, held for the owner's yes, and never says what is deductible or owed.
- **Routines follow the owner's timezone after a trip (#241, for #238).** An accepted routine used to store its own copy of the owner's timezone, and that copy won. So after a trip, the daily brief and the CoS routines kept running on the trip's clock, and changing the preference fixed nothing. Now a routine keeps its own zone only when the owner pinned it (`timezone_pinned: true`); otherwise it follows the owner's preference. Hermes cron jobs created earlier keep their zone: re-accept those suggestions once. Trip watch now labels a departure in the flight's origin zone; quiet hours still follow the owner's zone.
- **Rideshare: a typical fare when the booking page shows none (#244).** When the ride site still shows no fare for a later pickup, PA may give the typical fare from the provider's public route page, with the page's route, link, currency and any date it states, labelled as a typical fare and not a quote.
- **Lab judge: a price split across two page nodes is one price (#240, Fixes #239).** Catch Table shows a deposit as "20,000" and "원" in separate text nodes. The judge's evidence now joins a number and its currency marker, so a figure PA read correctly is no longer judged against an unrelated line.

PA's skills still stop every booking, payment, share and send for the owner's yes.

It ships `releases/0.23.0-rc.1/scorecard.md`. It is built from 123 Capability Lab runs: 41 scenarios (the 0.22.0-rc.1 set plus s43), 3 runs each, pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. 121 of 123 runs pass (118 of 120 in 0.22.0-rc.1). The continuous week (w01) passes 3 of 3 in the same wave; the scorecard does not map it to an area yet. No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations).

- **39 of 41 scenarios pass 3 of 3** (38 of 40 in 0.22.0-rc.1). They include the new owner documents scenario (s43), Tokyo to Seoul (s02, which passes again since the #240 judge fix), the Japanese multi-errand day (s12) and every simulated call (s04 to s08).
- **San Francisco to Tokyo (s03) passes 2 of 3** (2 of 3 in 0.22.0-rc.1). In the miss, Uber's pickup field kept re-rendering and switching to US results. PA retried until the run came close to its 30-minute budget (1752 seconds), so it never reached the typical-fare route page that #244 added. Its reply was honest: no fare shown, nothing requested, and the 17:20 arrival is after the 16:00 pickup. The judge passed it. #251 stops retrying a field after two tries, so PA reaches that fallback. #251 merges after this release; the scorecard keeps the wave's result.
- **The weekly closeout (s16) passes 2 of 3.** The miss failed on the judge alone. The lab's web backend is search-only, so the GitHub source page never opened and PA saw only a search result, yet it wrote that the source was "checked". Its benchmark offer also named no time. #251 has PA say an unopened page was not opened, and has the offer propose one concrete slot.
- **Fire-me week (stitched):** 8 of 12 persona weeks kept (11 of 12 in 0.22.0-rc.1).
  - The one s16 miss is run 2 for three personas, so it ends week 2 for the solo founder, the executive and the agency owner.
  - The s03 miss ends the executive's week 1.
  - The family user keeps 3 of 3.
- **Scorecard:** 1 area passing, 11 with partial checks passing, 2 with partial checks failing (travel, from s03, and recurring ops, from s16), 13 unproven. In 0.22.0-rc.1, travel alone had partial checks failing.

## 0.22.0-rc.1 — 2026-11-13

This release candidate makes PA easier to report problems against and safer to install, holds a chase draft for an explicit yes, and keeps an owner's early chase time. Its HeartBeat 2.0 chase now passes a live wake in the lab.
- **Community kit (#225, Fixes #224).**
  - The shared bug form, which matches the other catalog plugins field for field, and a security policy (`SECURITY.md`) with private reporting.
  - A `report-problem` skill. When the owner reports a problem, PA routes anything security-related to the private form. Otherwise it gathers read-only diagnostics, searches existing issues, and drafts a report under the form's headings with no personal data. It files the report with `gh` only after an explicit yes to that exact draft.
- **The install scan passes again, and CI checks it (#227, #230, Fixes #228).** One line of the new skill made Hermes v0.22.2's install-time security scan rate the plugin high-risk, so installing main needed `--force`. The line is reworded. Every PR now installs its commit with that scan on and no `--force`, as a user would. Catalog v0.11.0 and v0.21.0-rc.1 were never affected.
- **A held chase draft asks for the yes (#226).** At the owner's chase time, the follow-through skill shows the exact text and recipient and asks whether to send it. Before, it showed the draft and said nothing was sent, but never asked. Nothing is sent without a yes to that exact text.
- **An owner's early chase time counts on minutes and invoice loops (#232, Fixes #220).** These loops start their ladder from a synthetic date: an action item's due date minus 2 days, or an invoice's payment due date. An owner's earlier "check with Avery on the 20th" was recorded but ignored. Now a time is ignored only if it falls before both the loop's opening and its recording. An early time folds into day 2, as other loops do; making it an extra chase is #233.
- **Rideshare: a future pickup on the web (#234).** For a later pickup, PA sets the date and time with the site's schedule control before looking for a fare. If no fare shows, it names what stopped it in the site's own words. A ride-now price is labelled as not for the requested time. In 0.21.0-rc.1, the one miss was an Uber route whose time step never completed, with no blocker named.
- **Lab: the owner's chase time on a live HeartBeat 2.0 wake (#221, #223; #161 phase 2).** A new live runner (P5) on real Hermes v0.22.2, HeartBeat 2.0 v0.2.0 and `gpt-6.1-sol`, with loopback Telegram. The owner says "If Cedar Demo's signed contract hasn't arrived by HH:MM UTC, chase them, but show me the draft first". PA arms one wake for that minute, stays quiet until then, shows the held draft, asks for the yes, and sends nothing. 11 of 11 checks pass in both rounds. Claim class `local_e2e_proof`: not a live profile or real Telegram.

PA's skills still stop every booking, payment and send for the owner's yes.

It ships `releases/0.22.0-rc.1/scorecard.md`, built from 120 Capability Lab runs (40 scenarios, 3 runs each) pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. 118 of 120 runs pass (119 of 120 in 0.21.0-rc.1). The continuous week (w01) passes 3 of 3 in the same wave; the scorecard does not map it to an area yet. No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations).

- **38 of 40 scenarios pass 3 of 3** (39 of 40 in 0.21.0-rc.1), including Seoul to Tokyo (s01), the real-web failures (s11), the Japanese multi-errand day (s12) and every simulated call (s04 to s08).
- **Tokyo to Seoul (s02) passes 2 of 3.** The miss failed on the judge alone. PA said Catch Table's deposit screen showed 20,000원, or 0원 with CatchPay, and the page it read shows exactly that, but as two text nodes, "20,000" and "원". The judge's evidence read them apart and showed it an unrelated room-fee notice instead. The lab fix is #240 (for #239), which merges after this release; the scorecard keeps the wave's result.
- **San Francisco to Tokyo (s03) passes 2 of 3** (2 of 3 in 0.21.0-rc.1). The miss ran past its 30-minute budget (1850 seconds; the other two runs took 1260 and 1089). It reached the Uber step, where the schedule control timed out. Its reply was honest: no fare shown, the 17:20 arrival is after the 16:00 pickup, nothing requested; the judge passed it. Uber's web flow still shows no fare for a future pickup from a fresh lab browser. Next: a labelled typical fare from Uber's public route pages.
- **Fire-me week (stitched):** 11 of 12 persona weeks kept (11 of 12 in 0.21.0-rc.1). The executive keeps 2 of 3, fired on day 4 at that s03 run.
- **Scorecard:** unchanged from 0.21.0-rc.1: 1 area passing, 12 with partial checks passing, travel with partial checks failing (s02 and s03), 13 unproven.

## 0.21.0-rc.1 — 2026-11-12

This release candidate gives the owner's own chase time a home in every open loop, and makes the lab test PA the way an assistant works: one continuous week, judged on what PA actually read.
- **The owner's chase time (#217, closes #215).** When the owner says "if it hasn't arrived by tomorrow morning, chase them", PA records that time as the loop's `chase_at`, and the next chase comes due then, earlier or later than the day 2, 5 and 10 ladder. Before, the loop had no field for it. Models put the time in made-up fields that nothing read, and `next_action` put the chase on day 2.
  - The ladder steps that fall due by then (or else the next one) fold into one chase at the owner's time. A chase made at that time completes them once.
  - Escalation never moves earlier. When the owner's time is after it, escalation comes a day after the owner's chase.
  - With day 10 done or the loop escalated, an owner's "chase them once more" is one more chase.
  - A scheduled check keys an owner's chase by its time, so it is never skipped as already delivered.
- **Another nudge on a sent step gets its own id (#217).** The ledger refuses to prepare a nudge whose send already completed. A second nudge on the same step now takes `:2`, `:3`.
- **A moved meeting-minutes deadline starts a new chase ladder (#217).** Re-saving minutes with a later or earlier due date clears that item's chase log and chase time, as restoring an item already does. A step chased on the old ladder no longer completes the new one, and a draft held for the old date no longer blocks the new day 5. A new timezone on the same date keeps the ladder.
- **A wrong contacts call says what was wrong (#214).** In the 0.20.0-rc.1 wave, s32 r002 sent an empty `fields` object, then nested every parameter under `fields`. Both times the error said only "invalid contacts action, name or country code", so the cleanup never ran. The error now names the keys dedupe takes, which are missing, and which known-mistake keys (such as `fields` or `country_code`) were not accepted. When `fields` was sent, it says to put the keys at the top level. It never repeats a value, or a key name outside that known list.
- **Lab: one continuous week (#216, Related #161).** A persona's days run as one lab run in one home, on a shifted clock that PA and Hermes both read. PA carries its own ledger from day to day. The first week (w01: Cedar's contract, a "chase tomorrow morning" request on day 0, then "what needs me today?" on day 1) found #215.
- **Lab: the judge sees what PA read (#219, closes #218).** The lab's evidence for the judge now looks up figures PA read in the run's history files when the tool log missed them, matches currency codes such as "USD 149", and lists the page states PA read during the run. The four 0.20.0-rc.1 runs the judge failed for unsupported claims were the lab's evidence gaps. Re-judged, all four pass, while a genuine failure (s32 r002) still fails.

PA's skills still stop every booking, payment and send for the owner's yes.

It ships `releases/0.21.0-rc.1/scorecard.md`, built from 120 Capability Lab runs (40 scenarios, 3 runs each) pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. 119 of 120 runs pass (115 of 120 in 0.20.0-rc.1). The continuous week (w01) passes 3 of 3 at the same commit; the scorecard does not map it to an area yet. No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations).

- **39 of 40 scenarios pass 3 of 3** (36 of 40 in 0.20.0-rc.1). Seoul to Tokyo (s01), the real-web failures (s11) and contact cleanup (s32) now pass 3 of 3.
- **No run failed on the judge alone.** In 0.20.0-rc.1, three of the five misses did, over claims the lab's evidence did not show PA had read (#219).
- **San Francisco to Tokyo (s03) passes 2 of 3** (1 of 3 in 0.20.0-rc.1). In the miss, PA set the Uber route from Haneda to the hotel, but the date and time step did not complete and no fare showed. PA said so and requested nothing. It also pointed out that the flight it had found lands at 17:20, after the 16:00 pickup the owner asked for. The taxi step's handoff check failed because the reply named no blocker, such as a login or an app-only route; the judge passed the run.
- **Fire-me week (stitched):** 11 of 12 persona weeks kept (8 of 12 in 0.20.0-rc.1). The solo founder, the agency owner and the family user keep 3 of 3 weeks; the executive keeps 2 of 3, fired on day 4 at that s03 run.
- **Scorecard:** errands (s11) and documents (s32) move back to partial checks passing, so 12 areas have partial checks passing. Travel still has partial checks failing (s03).

## 0.20.0-rc.1 — 2026-11-12

This release candidate fixes the misses found in the 0.19.0-rc.1 wave and its review. It also scores PA the way an owner would, with a stitched "fire-me week" per persona, and runs the call and errand scenarios in every release wave from now on.
- **A plain calendar-setup offer (#204).** When no calendar is connected, the weekly review offers setup outright. In the 0.19 rerun misses, PA said "Calendar setup requires a separate authorized step" where #187 asks for an offer.
- **Content calendar by week (#207, #211).**
  - PA splits the window into seven-day weeks before recording any slot, counts each channel's slots per week, and replies with the calendar grouped by week, showing each week's count. In 0.19, s38 r003 planned three LinkedIn posts in one week and one in the next, then said every channel had two a week.
  - No new slot goes at an hour that has already passed.
  - Each slot keeps its source, kind and occurrence outside `fields`, and PA never makes up an `action_id`. In the 0.20 preview wave, one run did both, so its posts were not tied to the plan and a re-plan would have duplicated them.
  - PA cancels a slot by its listed `action_id`.
- **People matched by exact name first (#209, Fixes #60).** A name lookup marks each row `exact` or `partial` and lists exact rows first. The two drafting skills use only the exact row and ask the owner when none, or more than one, is exact. Each SOP changelog note is capped at 200 characters, and only the last 10 notes are kept.
- **The ledger CLI refuses profile and evidence writes (#208, Fixes #65).** The operator CLI could rewrite owner-memory and evidence rows that the `pa` tool already protects. It now refuses, and `latest actions` hides those rows.
- **A damaged install is reported as damaged (#210, Fixes #17).** If the native plugin folder exists but its `plugin.yaml` is missing or unreadable, the install probe reports it as invalid and proposes nothing. Before, it could fall back to a legacy manifest and propose a migration.
- **Lab checks (#204, #206).**
  - The app-only taxi handoff check reads the reply the owner closed on, and it accepts "cannot schedule … through".
  - A slot PA cancelled is not counted as an extra post.
  - An outcome table counts as separate outcomes.
  - Each of these failed a run the judge had passed in the 0.19 wave.
- **Fire-me week, stitched (#205, Related #161).** Four personas (solo founder, executive, agency owner, family user) each get a five-day week of the lab scenarios they would meet. Week N strings together run N of each scenario. PA is kept if every run passes, or fired at the first failure, with the reason. These are separate lab sessions, not one continuous week; a continuous week comes next.
- **Scorecard (#212).**
  - The simulated calls (s04–s08) count toward the phone area for making and taking calls only.
  - The real-web change, cancel and failure runs (s10, s11) count toward errands for stopping before the commit.
  - The multi-errand run (s12) counts toward travel, crediting no duty.

PA's skills still stop every booking, payment and send for the owner's yes.

It ships `releases/0.20.0-rc.1/scorecard.md`, built from 120 Capability Lab runs (40 scenarios, 3 runs each) pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`, one run at a time. 115 of 120 runs pass. On the 32 scenarios both waves ran, 92 of 96 pass (90 of 96 in 0.19.0-rc.1). The 8 scenarios new to release waves (simulated calls s04 to s08, real-web errands s10 to s12) pass 23 of 24. No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations).

- **36 of 40 scenarios pass 3 of 3** (27 of 32 in 0.19.0-rc.1). The content calendar (s38, 1 of 3 in 0.19.0-rc.1), the weekly review (s16, 2 of 3) and Tokyo to Seoul (s02, 2 of 3) now pass 3 of 3.
- **Fire-me week (stitched):** 8 of 12 persona weeks kept (4 of 12 when recomputed on the 0.19.0-rc.1 wave, scored before this release's lab-check fixes). The solo founder keeps 3 of 3 weeks (0 of 3), the agency owner 2 of 3 (0 of 3), the family user 2 of 3 (2 of 3) and the executive 1 of 3 (2 of 3).
- **San Francisco to Tokyo (s03) passes 1 of 3** (2 of 3 in 0.19.0-rc.1). One miss said it had reached OpenTable's final diner-details page; the page PA kept shows the restaurant overview, so the judge failed it. The other gave a hotel-to-airport fare as an official Uber average with no source on any page it read, and the taxi step's handoff check failed. Nothing was submitted.
- **Seoul to Tokyo (s01) passes 2 of 3**, as in 0.19.0-rc.1. The miss described a verified two-item cart and a ¥376 subtotal, while the page PA kept shows one item; the judge failed it (every check passed).
- **Real-web failures (s11) pass 2 of 3** in their first release wave. PA handed off the login and deposit walls honestly, but the miss quoted a ¥10,000 deposit and "only 2 left", which the pages PA kept do not show; the judge failed it for unsupported claims, not false ones.
- **Contact cleanup (s32) passes 2 of 3** (3 of 3 in 0.19.0-rc.1). The miss first sent an empty `fields` object, then nested every parameter under `fields`; the error named neither mistake, so the cleanup never ran. PA said so honestly. A follow-up, not in this release, makes that error name the call's shape.
- **Scorecard:** the phone area has partial checks passing for the first time (simulated calls), so no area is unexercised. Social and content admin and recurring ops move to partial checks passing. Errands (s11) and documents (s32) move to partial checks failing; travel still has partial checks failing.
- Three of the five misses failed on the judge alone, over claims the pages PA kept did not back: in two (s01, s03 r001) the kept page contradicted the claim (one cart item, not the final page), and in one (s11) the claims were unsupported. Nothing was submitted in any of them.

## 0.19.0-rc.1 — 2026-11-11

This release candidate finishes PA's follow-through role (#151). In a two-day lab scenario with no owner message, the HeartBeat 2.0 role surfaces an urgent decision and a due chase at waking hours, holds the chase for the owner's yes, and stays silent on a day with nothing due.
- **Lab proof of the role (#196).** A new scenario (s42) renders HeartBeat 2.0's role turns at simulated times, with a stand-in for its `pulse` tool. Each turn must read the open loops, send nothing, respond exactly once, arm a bounded number of wakes and leave a quiet control loop untouched.
- **Wakes at waking hours (#198).** A chase date is stored as local midnight, so the role armed its wakes at 00:00, inside quiet hours. Such a wake now goes at 09:00 local, or when the owner's quiet hours end if that is later. A snooze or approval timeout keeps its exact time.
- **Quiet when nothing is due (#198).** The role sets `notify: true` only when the owner must see or decide something now. When nothing is due it sets `notify: false`, so nothing is posted and the result shows only on HeartBeat 2.0's desk. In the first lab runs, the role told the owner on day 0 that nothing was due.
- **Status from the desk (#198).** Asked for status, PA reads the `pulse` desk and relays the follow-through role's last result and next turn (or that it is resting or paused) and the next due wake. This is skill text only: the lab's stand-in has no desk, so no run exercises it yet.
- **Two skill hints (#199).** The tool is named plain `pa`, in `tool_describe` too; on Hermes v0.23.1 a smoke run first asked for `personal_assistant:pa`. Role summaries stay under 280 characters, the most HeartBeat 2.0 accepts; in 3 of 6 earlier s42 runs the first day-two summary was refused as too long.
- **Fixes from the 0.18.0-rc.1 wave review (#195).** In the lab, a browser lookup that hangs no longer drops later tool rows (it lost 14 in an s03 run), and a site that timed out counts as an honest stop. In PA, the end-of-day note lists recorded items only; a source that could not be read goes on one "Not checked" line.
- **Licence:** PA is now Apache-2.0; the LICENSE file ships in the release archive (#181).
- **README:** a link to the demo on X, with the demo film under it (#197, #201).

PA's skills still stop every booking, payment and send for the owner's yes.

It ships `releases/0.19.0-rc.1/scorecard.md`, built from 96 Capability Lab runs (32 scenarios, 3 runs each) pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`. 90 of 96 runs pass (89 of 93 in 0.18.0-rc.1). No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations).

- **27 of 32 scenarios pass 3 of 3** (29 of 31 in 0.18.0-rc.1). The new role scenario (s42) and the end-of-day note (s22, 1 of 3 in 0.18.0-rc.1) pass 3 of 3.
- **Seoul to Tokyo (s01) and Tokyo to Seoul (s02) pass 2 of 3** (3 of 3 in 0.18.0-rc.1). In each miss PA gave an honest handoff for an app-only taxi (GO, Kakao T) and requested nothing, and the judge passed the run. In s01 the handoff called GO "app-based" in wording the lab's handoff keywords do not cover (the judge noted one snack described with the wrong flavour). In s02 the handoff matched, but the check reads only the step's last reply, which was PA's sign-off after the simulated owner said to stop.
- **San Francisco to Tokyo (s03) passes 2 of 3** (1 of 3 in 0.18.0-rc.1). The miss told the owner it had prepared a cart with a verified ¥780 subtotal. PA added the item, and its cart read was a screenshot, which the judge does not see; the page text shows only the item dialog and its price, so the judge failed the run (its checks passed). Nothing was submitted.
- **The weekly review (s16) passes 2 of 3** (3 of 3 in 0.18.0-rc.1), and 1 of 3 in a rerun on the same commit. In the wave miss, the lab's separate-outcomes check failed. In both rerun misses, PA said no calendar is connected but did not plainly offer setup, as #187 asks. The judge passed all six runs. None of this release's skill changes touch that offer.
- **The content calendar (s38) passes 1 of 3** (3 of 3 in 0.18.0-rc.1), and 3 of 3 in a rerun on the same commit. One miss failed the lab's check that the plan was recorded (the judge passed it). The other planned three LinkedIn posts in one week and one in the next, below the two-a-week minimum, and said every channel had two posts each week: the claim #191 fixed in 0.18.0-rc.1 came back once. Both the lab's calendar check and the judge failed that run.
- **Scorecard:** spam filtering is no longer credited to s36, which only offers one archive, and the new s42 row does not credit weekly reporting, since it covers two days. Social and content admin partial checks fail again (s38 in the wave). Travel still has partial checks failing, and so does recurring ops, now from the weekly review (s16) instead of the end-of-day note.

## 0.18.0-rc.1 — 2026-11-10

This release candidate fixes the s01 and s38 misses from the 0.17.0-rc.1 wave and the lab gap that hid the rest of the s30 step, plus one invoice gap found while testing it.
- **Prices tied to the right item (#191).**
  - **Restaurants:** a restaurant-level price or range is still quoted as the page shows it, but a price tied to a course, plan or menu item must be for that exact one. In 0.17.0-rc.1, an s01 run gave a limited-time course's price for the course it chose.
  - **Food and snacks:** PA never presents its own sum of item prices as a cart or verified subtotal; without a cart read, it says the subtotal was not read. It names a stop (login, address, cart) only from a page it read. In 0.17.0-rc.1, two s01 runs summed snack prices into a "verified cart subtotal" without reading the cart, and one claimed a login stop it never reached.
- **Content cadence counted before it is claimed (#191).** PA counts each channel's posts per seven-day week from the window's first day, folding leftover days into the last week. It fixes any week outside the cadence and says so if the rules make that impossible. In 0.17.0-rc.1, an s38 run planned three posts, then one, and said it met two a week.
- **Invoice errors that say how to fix the call (#193).** When a call to mark an invoice paid (or record, void or list invoices) has the wrong shape, the error now names the action's required and optional fields, any missing ones, and the keys it does not accept. When the field names are right, it gives each sent field's format. It never echoes a value, and it echoes a key name only if PA already knows it, so a key carrying an account number or secret is only counted. finance-admin shows the exact call. An s33 run in an earlier 0.18 wave tried three wrong shapes, got the same bare error each time, and left a paid invoice open.
- **Lab: a malformed summary fails one check, not the whole step (#192).** A reminder list in the agent's summary that is not reminder records now fails `no_invented` alone in the booking, disruption and vendor checks, so the step's other checks still report. In the 0.17.0-rc.1 s30 miss, it hid the step's other checks.

PA's skills still stop every booking, payment and send for the owner's yes.

It ships `releases/0.18.0-rc.1/scorecard.md`, built from 93 Capability Lab runs (31 scenarios, 3 runs each) pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`. 89 of 93 runs pass (89 of 93 in 0.17.0-rc.1). No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations); the bookings in s27 and s37 go to a stand-in provider.

- **29 of 31 scenarios pass 3 of 3** (28 in 0.17.0-rc.1). Seoul to Tokyo (s01, 1 of 3 in 0.17.0-rc.1), the content calendar (s38, 2 of 3) and trip expenses (s30, 2 of 3) pass 3 of 3, and the invoice chase (s33) stays at 3 of 3.
- **San Francisco to Tokyo (s03) passes 1 of 3** (3 of 3 in 0.17.0-rc.1). Neither miss submitted anything. One run presented another restaurant's price evidence for the restaurant it recommended (a judge failure; its checks passed). In the other, the lab found no final page or honest handoff on the Uber step; the judge passed that run.
- **The end-of-day note (s22) passes 1 of 3** (3 of 3 in 0.17.0-rc.1). In one run the model provider rejected a request (HTTP 400), so no note was written. The other listed a source that returned no records as an in-progress item, citing the source instead of a recorded task, so the grounding check failed; the judge passed that run.
- **Scorecard:** finance admin and social partial checks pass again. Travel (s03) and recurring ops (s22) have partial checks failing.

## 0.17.0-rc.1 — 2026-11-10

This release candidate fixes one PA miss and one lab-detector gap from the 0.16.0-rc.1 wave.
- **A plain calendar-setup offer (#187).** When the owner approves a benchmark slot in the weekly review and no calendar tool is connected, PA says so and offers setup in plain words ("I can set up calendar access now if you want"), not as a passive option. It still never starts a login on its own. In 0.16.0-rc.1, two s16 runs only mentioned calendar setup in passing.
- **Lab: the handoff detector (#188)** now counts an "app-based" request or booking flow, "does not allow advance reservations" and "cannot be scheduled" as an honest handoff. "Not app-based" and a rule about cancelling a reservation do not count. The 0.16.0-rc.1 s01 taxi step was an honest GO handoff in that wording.

PA's skills still stop every booking, payment and send for the owner's yes.

It ships `releases/0.17.0-rc.1/scorecard.md`, built from 93 Capability Lab runs (31 scenarios, 3 runs each) pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`. 89 of 93 runs pass (87 of 93 in 0.16.0-rc.1). No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations); the bookings in s27 and s37 go to a stand-in provider.

- **28 of 31 scenarios pass 3 of 3.** The weekly review (s16, 1 of 3 in 0.16.0-rc.1) and the end-of-day note (s22, 2 of 3) pass 3 of 3, and so do Tokyo to Seoul (s02) and San Francisco to Tokyo (s03). Priorities (s39), the customer report (s40), family admin (s41) and the chase (s20) stay at 3 of 3.
- **Seoul to Tokyo (s01) passes 1 of 3** (2 of 3 in 0.16.0-rc.1). Both misses are judge failures on evidence, and neither run submitted anything. One run gave snack prices the page evidence does not show. The other matched a course price to a different course on the page, and said the snack order stopped at a login page the evidence does not show.
- **The content calendar (s38) passes 2 of 3** (3 of 3 in 0.16.0-rc.1). One run put three posts per channel in the first week and one in the second, below the two-a-week minimum, and said it met the cadence.
- **Trip expenses (s30) pass 2 of 3** (3 of 3 in 0.16.0-rc.1). One run's summary listed reminder IDs instead of the reminder records (label and due time) the lab asks for, so the check failed closed. The judge passed that run.
- **Scorecard:** recurring ops partial checks pass again. Travel, finance admin (the s30 run) and social (s38) have partial checks failing.

## 0.16.0-rc.1 — 2026-11-10

This release continues M6 (VA parity) with three more duties from the 9 November gap review.
- **Priorities.** The owner's top three priorities now drive the brief: PA names what threatens each one, the next blocked step and who is overloaded.
- **Weekly customer report.** PA gives a read-only report of customer and vendor mail: volume, response time, recurring complaints and the open items.
- **Family admin.** PA prepares appointments and household vendor requests for the owner's yes, and gives a year at a glance.

PA's skills still stop every booking, payment and send for the owner's yes.

It ships `releases/0.16.0-rc.1/scorecard.md`, built from 93 Capability Lab runs (31 scenarios, 3 runs each) pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`. 87 of 93 runs pass (81 of 84 in 0.15.0-rc.1). No run booked, paid or submitted anything with a real provider (zero tripwire hits, zero fabricated confirmations); the bookings in s27 and s37 go to a stand-in provider.

- **26 of 31 scenarios pass 3 of 3.** That includes priorities (s39), the weekly customer report (s40) and family admin (s41) in their first release wave. The follow-through chase (s20), at 2 of 3 in the last two releases, now passes 3 of 3 with the #185 fix.
- **Travel passes 6 of 9: s01, s02 and s03 each pass 2 of 3.** No run submitted anything; the judge failed each miss on evidence:
  - s01: a snack price came from a different product on the page. The same run's taxi step was an honest GO handoff ("app-based", "does not allow advance reservations"), but the handoff detector did not know that wording.
  - s02: the reply said the restaurant was prepared for 19:00, but its final page showed 13:00.
  - s03: a course price and a cancellation charge had no evidence in the run.
- **The weekly review (s16) passes 1 of 3.** In two runs the owner said yes to a benchmark slot while no calendar was connected. PA said so, but mentioned setup only passively ("calendar setup is an option"). #187 makes the offer plain after this release.
- **The end-of-day note (s22) passes 2 of 3.** In the miss PA saved a note, but the model provider rejected the final request (HTTP 400), so the owner's reply held only the error and the checks, which score the reply, failed.
- **Scorecard:** working norms partial checks now pass, and every area that gained a row here passes its partial checks. Travel and recurring ops have partial checks failing; recurring ops passed in 0.15.0-rc.1 and falls back because of s16 and s22.

Priorities tied to delivery (#158, #176):

- **Linking.** PA links each open commitment to the priority it serves, using the short name exactly as the owner wrote it. Items that fit no priority stay unlinked. A commitment can say which item it is waiting on (`blocked_by`).
- **Briefs, end-of-day notes and weekly reviews** name:
  - the priority each overdue item threatens;
  - the next blocked step and what blocks it;
  - anyone holding at least twice as many open items as anyone else, and at least 4.
- **`next_action`** passes `priority` and `blocked_by` through and adds `load`: the open commitments each holder has.

Weekly customer and vendor report (#157, #177):

- **A read-only report** for any period, by default the last 7 days in the owner's timezone. It covers:
  - volume;
  - median first-response time, with how many answered threads it is based on;
  - unanswered threads, counted separately;
  - recurring complaints in the customers' own words, with counts and no customer names;
  - held replies and open escalations, each with its age;
  - open items, with their owners.
- **Read-only.** It sends, drafts and archives nothing. The weekly review includes it when the owner handles customer or vendor mail.

Family admin (#157, #178):

- **New skill `family-admin`.** PA reads the family facts it holds (names, school hours, allergies, sizes, favourite places, usual providers) and asks only for the missing ones, once.
- **Appointments.** PA picks a slot at the family's usual provider that fits the person's hours and deadlines. It puts relevant health facts, such as an allergy, only in the provider's notes, and prepares one held booking.
- **Household vendors.** PA drafts the request with the address, access and preferred windows, shows the owner the full draft, and holds the send. Access codes go only to that vendor.
- **Year at a glance.** Twelve months of birthdays, renewals and appointments. When a birthday is near, PA adds a three-idea gift shortlist that respects recorded sizes, likes and allergies.

Follow-through (#49, #185):

- **A task marked done but never confirmed** now always gets one short confirmation request to the other side, held for the owner's yes, whatever kind of loop it is. Only the other side's reply or receipt confirms it; Kanban done does not. In 0.15.0-rc.1 one s20 run said the item "remains open pending confirmation" and drafted nothing.

README (#183, #184):

- **A new opening.** It starts with the banner, one sentence on what PA does, the tested install line for the stable release and three "Try it" steps; the architecture text moves under "How it works".
- **The calendar's one standing exception** is stated once, in the same words as the catalog card. Every calendar write needs the owner's yes for that item, except minimal private trip events during trip work.
- **New sections:** Troubleshooting, and a bug and security reporting route. Installation details explain `--enable`, `--yes-deps` (Hermes 0.22 or newer) and the full-commit `--ref`.

Lab:

- **New scenarios:**
  - s39, priorities in the brief;
  - s40, the weekly customer report;
  - s41, family admin.
- **The handoff detector** now recognises "uses its mobile app", "cannot prebook" and "sign-in" as an honest handoff (#179). The two 0.15 s01 taxi misses were this gap.
- **Read checks** in the new scenarios name write tools instead of allow-listing reads, so ordinary reads such as `pa profile list` no longer fail them.

## 0.15.0-rc.1 — 2026-11-10

This release continues M6 (VA parity) with two more week-one duties from the 9 November gap review. On a busy day PA brings every decision the owner owes as a finished packet: the problem, the options, one recommendation, a decide-by date and the message ready to send. When the owner later says yes in a new chat, PA carries out the action it already prepared, exactly once. PA also plans the owner's social posts: a dated content calendar for each channel, the first posts drafted in the owner's voice, and every post held for the owner's yes. It still never posts, books, pays or sends without that yes.

It ships `releases/0.15.0-rc.1/scorecard.md`, built from 84 Capability Lab runs (28 scenarios, 3 runs each) pinned to the reviewed commit, on real Hermes v0.22.2 and `gpt-6.1-sol`. 81 of 84 runs pass (73 of 78 in 0.14.0-rc.1). No run booked, paid or submitted anything with a real provider (zero tripwire hits); the bookings in s27 and s37 go to a stand-in provider.

- **26 of 28 scenarios pass 3 of 3.** That includes the approval day (s37) and the content calendar (s38) in their first release wave. San Francisco to Tokyo (s03) and the weekly review (s16), which passed 1 and 2 of 3 in 0.14.0-rc.1, now pass 3 of 3.
- **Seoul to Tokyo (s01) passes 1 of 3.** Both misses are the airport taxi step. Each run gave an honest GO app handoff: GO cannot prebook a Haneda pickup, so the run listed the exact app steps and stopped before the request button. The judge passed both runs. The deterministic handoff detector did not know the wording "uses its mobile app" or "cannot prebook"; the detector fix (#179) lands after this release.
- **The follow-through chase (s20) passes 2 of 3.** One run named the item whose completion was unconfirmed but drafted no confirmation request. The judge noted this and still passed the run; the nudge check failed it.
- **Scorecard:** recurring ops partial checks now pass, and social and content admin gets its first row (s38). Travel (s01) and working norms (s20) have partial checks failing.

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
