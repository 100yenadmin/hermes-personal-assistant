# Changelog

## Unreleased

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
