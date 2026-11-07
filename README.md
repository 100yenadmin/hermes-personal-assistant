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

Where it is going: [VISION.md](VISION.md) sets the goal, a remote assistant at
the level of a top-rated human VA and then a remote Chief of Staff, and the bar
that measures it. [ROADMAP.md](ROADMAP.md) sets the order of work.

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

## What it touches

What you would want to know before installing. Nothing on this list runs on install. Anything marked opt-in stays off until you configure it or ask for it.

**Stored data.** PA's main store is one SQLite ledger in your Hermes profile, `state/travel-ledger/travel.sqlite`. Its records cover:
- trips, flight facts and prepared actions;
- setup answers;
- preferences, people, SOPs and trust levels;
- call cards and call transcripts;
- task evidence;
- action receipts.

Optional features keep their own stores:
- conversation delivery keeps a packet queue (`queue.sqlite3`);
- Daily Ops keeps `state/daily-ops/state.json`;
- client sync keeps `clients.json`, with client names, emails and domains.

Owner-memory and evidence records refuse recognised card numbers, credentials and labelled account numbers. Most other ledger records pass a lighter filter that drops private fields and redacts some patterns. Approval records keep their metadata as given, for example an expected read-back reference. Both filters are pattern-based, not a guarantee. After you approve a setup review, the agent also writes your USER.md, a marked PA section of SOUL.md, a manual skill and any context file you named. That file can be outside the profile. A trip export writes `Trip.ics` and `Trip-Reference.md` to the folder you choose. Nothing is deleted automatically: "forget" retires a record, and disabling the plugin erases nothing.

**Hooks.**
- `pre_tool_call` sees every tool call. It blocks only a tool that a PA exact-action approval or the policy deny list covers. If the ledger cannot be opened, it also blocks most tools until storage is readable again.
- `pre_llm_call` adds short notes to your own turns. They cover:
  - the one-time `/pa setup` offer;
  - setup, mode and "grill me" routing;
  - a one-time fresh-session check;
  - active preferences;
  - a note asking the agent to save a stated preference or correction in PA's owner memory instead of Hermes memory.

  On cron, subagent and unattended turns it adds nothing, except a note that cancels a Chief of Staff wake while that mode is off.

**Tools.** `pa` (ledger operations), `pa_call` (call cards, an offline brief compiler and a loopback simulator; nothing dials) and the `/pa` command. `pa_delivery_ack` registers only when conversation delivery is enabled. Some skills also run PA's local ledger helper (`skills/travel-ledger/scripts/travel_ledger.py`) through the shell, for example for connectivity and payment-readiness records. It reads and writes the same profile ledger.

**Reads outside the ledger, when you ask.**
- During `/pa setup`, with your consent, the agent:
  - reads USER.md, SOUL.md, its memory, the calendar, past itineraries and a context file you name;
  - lists your cron jobs and skills;
  - for the "grill me" profile, reads up to 20 recent sent emails through a mail read path you have already authorised, to learn tone and key contacts. It stores no raw mail text.
- Inbox and travel-mail work you ask for reads messages and their attachments through the mail integration your agent already has, and can write drafts in your mail provider. Sending is a separate action that needs your yes.
- Trip import reads the `.ics` or guide file you give it.
- Observer, precheck and mode reads use the profile's `config.yaml`. `/pa mode` also writes the plugin's mode setting there.
- Read-only lookups use Hermes's kanban database and cron job and suggestion stores.

**Network, only when you ask or opt in.**
- **The provider sites you choose.** Errands drive Hermes's browser tools on the provider's own site, for example a restaurant, hotel, airline or delivery site. That can be the local browser, or `agent-browser` attached to a Browserbase session. If you give provider sign-in details in chat, the checkout skill saves them in the agent's credential lane and signed-in browser profile, where available.
- **Browserbase** (`api.browserbase.com`): only if it is configured. It is used when you ask for a cloud browser session, and the agent can also pick it during an errand you asked for, when a sign-in or verification step is likely or the site blocks the local browser. It uses your `BROWSERBASE_API_KEY` and `BROWSERBASE_PROJECT_ID` from the profile's secret scope. Sessions are created with recording and logging off.
- **Google Calendar API:** `calendar_bind` checks the account and the destination calendar, and `calendar_sync` creates and updates PA's trip events in the one calendar you bind. Daily Ops only reads. It uses the profile's existing Google token file, `google_token.json`, from Hermes's Google Workspace sign-in. PA reads that file and refreshes the access token in memory, which contacts Google's token endpoint. It never starts a sign-in and never writes the file. (Moving this onto a plugin-declared OAuth client is tracked in #74.)
- **Open-Meteo** (geocoding and forecasts): only after you accept a trip watch. It receives your departure airport or city, then coordinates. It can be set to `off`.
- **ElevenLabs** (`api.elevenlabs.io`, read-only): only from the manual `python -m personal_assistant.phone_poll` command. That command reads `ELEVENLABS_API_KEY` from the shell you run it in.
- **Daily Ops (opt-in):**
  - mail and calendar reads through the `gog` CLI. Selected mail (subjects, senders, snippets) and calendar items go to your configured model provider to write the brief, with email addresses replaced by aliases. The brief goes to your delivery target;
  - OpenStreetMap Nominatim and OSRM through `curl`, only after you give geo consent;
  - client sync through the Stripe and Supabase CLIs, only after you give consent.

**Background work, only after a yes.**
- **Trip watch.** If you accept one, the agent arms a HeartBeat 2.0 watcher. Once you allowlist its command, the watcher runs `scripts/pa_observe.py` every 15 minutes and stops shortly after the trip, at most 14 days later. If you agree, the trip watch also schedules one-off wakes at the check-in window and on arrival, each of which runs an agent turn.
- **Conversation delivery (opt-in).** It runs one gateway background task that injects packets into one verified session, through a gateway startup hook you install yourself. Its operator-run priority-mail collector reads Gmail through the `gog` CLI.
- **Routine suggestions.** These write small precheck scripts into your profile's `scripts/` folder and add Hermes cron suggestions. Nothing runs until you accept a suggestion. Turning Chief of Staff mode off removes PA's own Chief of Staff jobs.

**Developer scripts.** The `evals/` harness and the `scripts/evaluate_*` tools call the model provider (and, for the voice check, Fish Audio) only when you run them by hand. The plugin never loads them.

**Telemetry and approvals.**
- PA sends no telemetry.
- Bookings, payments, reservations, orders and cancellations stop for your explicit yes for that exact action. A prepared booking stops at the provider's final page.

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
The assistant also gives each routine's exact command, `/suggestions accept <id>`. Use it whenever a routine was offered before, for example after Chief of Staff was turned off and on or after you asked for a removed routine again: the title can match the older record.
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
