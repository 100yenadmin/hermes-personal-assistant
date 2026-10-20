# Personal Assistant Plugin

Personal Assistant is a persistent personal-operations layer for Hermes. It helps
an agent carry context, commitments, evidence, and follow-through across
conversations and workflows without replacing Hermes's provider tools,
credentials, scheduler, policy, or conversation runtime.

The plugin combines durable context, replay-safe actions, workflow
reconciliation, exact-action authorization, and optional evidence delivery.
Calendar, inbox, meetings, household administration, shopping, and travel are
domain workflows built on that shared foundation. Travel remains a supported
domain pack, not the product identity.

## What it does

- **Focused context:** recover only the relevant trip, action, source, guide, or
  next action instead of replaying the entire ledger.
- **Durable follow-through:** preserve action identity, source revisions,
  provider attempts, receipts, and reconciliation state across restarts.
- **Workflow state:** register material events, claim required projections,
  record verified outcomes, and surface stale or unresolved work.
- **Provider safety:** prepare, confirm, atomically claim, and reconcile a final
  action without treating a timeout as permission to submit again.
- **Exact-action authorization:** an explicitly scoped PA workflow can bind one
  tool call to its complete arguments and trusted runtime identity. Ordinary
  unscoped calls remain under normal Hermes policy.
- **Daily operations:** optional read-only brief, priority, evening, and account
  views over explicitly accepted sources.
- **Conversation evidence delivery:** optional bounded delivery into one exact,
  existing conversation using a private durable queue and explicit host setup.
- **Domain workflows:** calendar and meeting preparation, selected inbox and
  follow-up work, household administration, shopping and services, and travel.

## Ownership model

```text
User or PA workflow
        │
        ▼
Domain guidance
calendar · inbox · meetings · household · shopping · travel
        │
        ▼
Personal Assistant control plane
context · actions · receipts · state loops · freshness
        │
        ├── opt-in exact-action authorization
        └── optional conversation evidence delivery
        │
        ▼
Hermes-owned services
providers · credentials · scheduler · policy · conversations
```

Personal Assistant owns its durable records, source-revision history, claims,
receipts, and reconciliation state. Domain workflows own their business rules
and canonical destinations. Hermes owns provider integrations, authentication,
scheduling, normal tool policy, and conversation transport.

Recording state or possessing a credential never grants authority to send,
purchase, book, update a provider, or mutate another system.

## Safe defaults

Installing the plugin does not:

- enable the plugin;
- create reminders or recurring jobs;
- grant provider or conversation-injection permissions;
- send email, change calendars, make purchases, or perform other provider actions;
- enable Daily Ops or conversation delivery; or
- establish provider authentication, runtime qualification, fleet approval, or
  customer readiness.

Daily Ops and conversation delivery are separately configured. Protected
provider actions retain their workflow-specific confirmation and readback
requirements. Unknown submission outcomes remain blocked until reconciled.

## Chief of Staff

Chief of Staff helps turn your priorities into useful next actions. It is off
by default. Use `/pa mode chief-of-staff on`, then `hermes gateway restart`
and a new session. Run `/pa setup chief-of-staff` for six short questions about
priorities, radar topics, timing and schedules; review changes before saving.
`/pa mode` shows the mode. `/pa mode chief-of-staff off` removes PA CoS jobs,
dismisses pending CoS suggestions and pauses their rules. Assistant and Travel stay on.

Schedules need an explicit yes for each one, a verified current chat and separate
Hermes suggestion acceptance. `cos_daily` defaults to 09:30 local. The weekly
kickoff, `cos_kickoff`, defaults to Monday 11:00 local and reads the last closeout.
The weekly closeout, `cos_weekly`, defaults to Friday 15:00 local and includes radar.
Use `/suggestions` to review, then `/suggestions accept personal-assistant-cos-daily`,
`/suggestions accept personal-assistant-cos-kickoff` and/or
`/suggestions accept personal-assistant-cos-weekly` for your chosen schedules.
Enabling the mode starts no jobs. Five-minute prechecks respect quiet hours,
pause and snooze, with one report per local day or ISO week. A missed kickoff
catches up only until that week's closeout.

- `cos-daily`: one useful action backed by evidence, or silence.
- `cos-kickoff`: start the week with one focus, read from the last closeout, or silence.
- `cos-weekly`: the weekly closeout; compare priorities and outcomes, record carry-over
  and propose one batch of improvements.
- `cos-scout`: research adopt versus build for a current need, on demand.
- `cos-radar`: offer at most one benchmark a week; book a slot only after approval.

These skills never install software, silently edit SOUL.md, USER.md or skills,
or send unapproved messages. Follow-ups use only owner-approved HeartBeat 2.0
`at` wakes in the same chat.

## Quick start

After an approved installation and activation:

1. Call `pa(operation="status")` to confirm the plugin responds and inspect
   durable state without changing it.
2. Call `pa(operation="capabilities")` to discover integrations. Capability
   exposure is not authentication proof; verify a selected provider with one
   appropriate read-only call.
3. Call `pa(operation="recipes")` and load only the qualified domain skill needed
   for the current request.
4. Use `pa(operation="context", data={...})` or
   `pa(operation="next_action", data={...})` to recover focused state.
5. For a provider-visible action, follow the selected workflow's confirmation,
   exact authorization where applicable, provider readback, and reconciliation
   contract.

The `pa` tool exposes `setup` for guided setup progress and generic state-loop operations:
`event_upsert`, `projection_claim`, `projection_result`, `reconcile`, and
`freshness`. See [the state-loop contract](docs/state-loop.md).
`browser_session` creates Browserbase sessions, returns live view links for user handoff, and releases sessions.

`trip_watch_plan` plans trip check-ins and records agent-created pulse wake receipts.
`trip_offer` checks and records offer outcomes; load `personal-assistant:trip-concierge`.

## Domain workflows

The built-in recipe router covers eight bounded areas:

- trip intake, changes, and portable export;
- assisted travel transactions;
- refunds and returns;
- calendar and meeting preparation;
- briefs and reminders;
- selected inbox and reply workflows;
- household renewals and receipts; and
- shopping and services.

Additional qualified skills provide travel execution, Browserbase continuity,
payment-readiness guidance, reservations, rides, food delivery, check-in,
weather, and itinerary support. These are optional domain modules over the same
PA control plane.

## Installation

Install one reviewed full Git commit and leave it disabled while inspecting the
manifest and [`after-install.md`](after-install.md):

```bash
hermes plugins install 100yenadmin/hermes-personal-assistant \
  --ref <40-character-approved-commit> --no-enable
```

Install the declared `python_dependencies` into that Hermes environment, then
enable `personal-assistant` through Hermes's native plugin controls after the
profile owner approves activation. Restart or reload only at an agreed idle
point. Verify `pa` and `personal-assistant:personal-assistant` discovery before
use.

Pinned revisions do not update automatically. The documented preservation
wrapper requires a separately approved replacement SHA. For an isolated loader
check without profile or provider mutation, use `scripts/check_pa_native.py`.

## Verification and rollback

Focused tests live in `tests/`; the full package, archive, release-contract, and
native lifecycle matrices run in GitHub Actions. Source and fixture success do
not establish live-provider or customer acceptance.

See [provider proof levels](docs/provider-proof-levels.md) for demonstrated preparation and honest handoffs.

To roll back, pause any explicitly configured jobs, disable the native plugin,
and preserve the ledger for re-enable, export, or approved restoration. Schema
changes are additive and retain legacy rows. Follow the bounded procedure in
[`after-install.md`](after-install.md) and
[the release process](docs/release-process.md).

## Documentation

Start with the [documentation index](docs/README.md) or the
[canonical product overview](docs/personal-assistant.md).

- [Product authority and privacy contract](docs/customer-contract.md)
- [Daily Ops](docs/daily-ops.md)
- [Generic state loop](docs/state-loop.md)
- [Exact-action authorization gateway](docs/workflow-authorization-gateway.md)
- [Release and installation boundary](docs/release-process.md)

## Compatibility

The product and native plugin ID are `personal-assistant`. The archive/package
name `travel-agent-skills`, existing travel-qualified skill names, and profile
ledger path `state/travel-ledger/travel.sqlite` are retained compatibility
identities. Installation, upgrades, and rollback may depend on them; changing
them requires a separate migration rather than a documentation rename.
