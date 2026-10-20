# Chief of Staff lab (L34 / PA 0.8 issue #7)

`run --scenario cos --dry-run` validates the full catalog and plans s13–s16.
Use the existing `home` command with immutable PA/HB2 refs and installed dependencies,
then `run --scenario cos --runs 1 --workers 1 --judge codex` with the usual explicit
`--hermes`, `--python`, `--home-template` and fresh `--out` arguments. No installation,
gateway startup, job creation or provider actions happen during a dry-run.
The template must contain the CoS-enabled PA source (PR #18 or its successor).

CoS YAMLs set `modes: {chief_of_staff: true}`, an IANA `timezone`, and synthetic
`user_md`. The runner writes plugin **settings** before plugin discovery and
puts the user section in `memories/USER.md`. It injects that section into the
agent's system context because the existing lab disables automatic memory/context
loading. `seed` entries are real installed-PA `action_upsert` calls for notes and
commitments. No SQL fixture insertion or provider receipt is used. Commitment
status without native Kanban readback remains unknown; the supplied owner notes
are evidence of the stuck brief and meeting, not a calendar scan.

Dates expand at run time in the scenario's timezone: `@today@`, `@tomorrow@`,
`@yesterday@`, `@now@`, `@week@`, `@weekday@`, `@last_week@`, `@last_week_date@`,
`@last_week_at@`, `@review_at@`. The synthetic clock is today's local noon.
Preferences and accepted, verified **lab** destination rules are seeded through PA.
`seed.json` records the resolved clock and pre-run ledger. No live owner data is used.

## Scheduled-child approximation

Reference: Hermes v0.22.2, commit `d923a5eb487a17c0a68801bba9ef0f56c81040a8`,
`cron/scheduler_prompt.py::_build_job_prompt` / `_load_cron_skill_parts` and
`cron/scheduler.py::_CronRunScope`.

`type: scheduled` plus `job: cos_daily|cos_weekly` calls the installed PA's real
`cron_precheck`. Failure to claim is an error, never an ordinary chat fallback.
The runner loads the installed skills named by `prepare_suggestions`' real job
spec, adds the fenced `## Script Output` JSON and scheduled-job hint, and starts
with fresh history. The cron ContextVar is set for that turn and restored before
the scripted human reply. s16's second step supplies a fixed benchmark yes and
slot; no model-generated user can authorize a provider effect. CoS steps use one
assistant turn each; `max_user_turns` bounds the number of scripted steps.

Differences: no scheduler process, script subprocess, gateway, native prompt scanner,
notepad, bundled-skill/config injection, cron session store or real chat adapter.
Hermes's generic hint says the final response auto-delivers, while PA's job sets
`deliver=local` and requires explicit message/receipt calls. This harness replaces
only that hint's delivery instructions with the local-job contract. It exposes
`lab_send_message` instead of the real `send_message`, without overriding native
tools. The tool captures to `messages.jsonl`, returns `provider: lab` and a unique
capture reference, and rejects wrong/unclaimed destinations or duplicate sends.
The agent must record its own PA receipt using that reference. A local capture
proves no real-provider delivery. Final cron responses are local logs; silence is
zero captures plus the agent's `suppressed` receipt and empty/`[SILENT]` log.

## Evidence and limits

`run.json.scheduled_turns` records the claim, send count and actual PA receipt.
Per-step ledger snapshots and `notes_at_delivery` prove note timing; profile
content/mtime manifests detect protected-file changes. Skill writes and install-like
execution attempts are blocked and fail checks. The existing final-submit tripwire
is retained. Terminal/file/cron/delegation/real-message tools stay outside the surface.
Checks count daily notes/words, check seeded citations, receipt/provider-reference
agreement, required note fields, weekly outcome sections/proposal labels and radar
identities. Label-based single-offer/proposal checks are heuristics; they do not prove
semantic cardinality, usefulness or source support. The existing judge checks those
with priorities, seed outcomes, captured notifications, notes and retrieved web text.
No new judge model/schema is introduced; usefulness is scored under correctness.
Live scout/radar research uses real web tools; offline tests use synthetic results.
Report local results as exploratory until the orchestrator creates/publishes the
required result card. Source tests prove no skill-quality, booking or customer result.
