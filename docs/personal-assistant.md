# Personal Assistant Plugin

Personal Assistant is a persistent personal-operations layer for Hermes. It
preserves the context, action identity, evidence, and reconciliation state needed
to carry work safely across conversations and restarts.

The plugin is broader than any one domain. Calendar, inbox, meetings, household
administration, shopping, and travel are workflows over a shared control plane.
The product does not replace Hermes's provider integrations, credential handling,
scheduler, normal policy, or conversation runtime.

## Product model

```text
observe → recover context → decide → prepare → authorize → act → read back → reconcile
```

Personal Assistant supplies durable primitives for that loop:

- focused context and next-action recovery;
- stable action, event, source, and projection identities;
- source-revision history and replay-safe updates;
- provider attempt, result, and receipt records;
- claim leases and unknown-outcome fencing;
- freshness and unresolved-work evaluation;
- opt-in exact-action authorization; and
- optional, conversation-owned evidence delivery.

Domain workflows supply meaning. A calendar adapter knows which calendar is
canonical. An inbox workflow determines what constitutes follow-up. A travel
workflow knows which itinerary facts are material. The generic PA kernel records
and protects their execution state without inventing those semantics.

## Ownership

### Personal Assistant owns

- its private SQLite ledger and additive schema;
- stable internal action and event identities;
- source revisions and projection obligations;
- provider-attempt lifecycle and safe receipts;
- atomic claims, leases, replay prevention, and reconciliation state;
- caller-declared freshness deadlines; and
- the optional conversation-evidence queue when configured.

### Domain workflows own

- business and account semantics;
- reduction from source evidence into desired changes;
- canonical destination selection;
- material-detail validation;
- confirmation requirements; and
- provider readback and acceptance criteria.

### Hermes owns

- provider and connector tools;
- credential and secret resolution;
- normal tool policy and approvals;
- scheduling and recurring-job registration;
- conversation transport and session identity;
- browser control and host lifecycle; and
- native Kanban commitment status.

A PA record, capability row, credential, or authorization envelope is not itself
permission to perform a provider-visible action.

## Interfaces

The native plugin registers:

- `pa` — the structured state, workflow, authorization, and routing interface;
- `pa_delivery_ack` — a local acknowledgement transition for an admitted
  conversation-evidence packet; and
- `pre_tool_call` — the opt-in exact-action enforcement hook.

The `pa` operation groups are:

- **Guided setup:** `setup`; `/pa setup` begins on your next message. Setup runs in one chat; in another chat, `/pa setup` continues it there.
- **Discovery:** `status`, `capabilities`, `recipes`.
- **Browserbase:** `browser_session` creates sessions, returns live view links for user handoff, and releases sessions.
- **Context:** `context`, `next_action`.
- `trip_watch_plan` plans trip check-ins and records agent-created pulse wake receipts.
- `trip_offer` checks and records offer outcomes; load `personal-assistant:trip-concierge`.
- **Domain state:** `trip_import`, `export`, `calendar_bind`, `calendar_sync`,
  `disconnect`, `automations`.
- **Durable actions:** `action_upsert`, `action_prepare`, `action_confirm`,
  `action_cancel`, legacy `action_claim`, and `action_result`.
- **Exact authorization:** `authorization_prepare`, `authorization_confirm`,
  `authorization_cancel`, `authorization_status`.
- **Generic state loop:** `event_upsert`, `projection_claim`,
  `projection_result`, `reconcile`, `freshness`.

Capability discovery describes exposed integration surfaces, not successful
provider authentication. Verify a chosen provider with an appropriate read-only
call before relying on it.

## Domain workflows

The recipe router exposes eight bounded workflow families:

1. trip intake, change, and portable export;
2. assisted travel transactions;
3. refunds and returns;
4. calendar and meeting preparation;
5. briefs and reminders;
6. selected inbox and reply work;
7. household renewals and receipts; and
8. shopping and services.

Qualified skills load only when relevant. Travel-specific skills remain available
for itinerary intake, bookings, check-in, food, rides, reservations, weather,
provider messages, and approval summaries. They are a domain pack over the PA
kernel rather than the definition of the product.

Hermes Kanban owns commitment status. The PA ledger may link one stable action to
a Kanban task while separately tracking provider execution and evidence. Research,
drafts, meeting packets, exports, and receipts can be retained as completed note
actions when durable proof is useful without creating a new commitment.

## Durable actions and provider uncertainty

For a provider-visible final action, the governed workflow allocates a stable
action ID and prepares with `enforcement_profile: "exact_action"`, the exact
material summary, action/workflow revisions, provider tool and complete
arguments, semantic target, freshness, preconditions, expected readback, and a
one-call execution budget. After confirmation and a final recheck, the workflow
invokes the provider tool directly. The `pre_tool_call` hook matches the sealed
scope and atomically claims that one call before dispatch. `action_cancel`
withdraws a governed action before dispatch; `action_result` records the
provider readback. Manual `action_claim` remains only for legacy non-governed
transactions.

Changed price, recipient, item, itinerary, or terms requires a refreshed summary
and confirmation. A timeout or lost response is `unknown`, not permission to
submit again. The workflow must inspect the provider's canonical state and
reconcile the original claim before any further attempt.

Credential access never implies spending, messaging, booking, cancellation, or
calendar-write authority.

## Generic state loop

The state loop keeps management state synchronized with operational events:

```text
observe → normalize → reduce → apply → verify → reconcile
```

An event has deterministic source identity, an explicit revision, and a list of
required projections. Each projection can be claimed with a bounded lease and
completed only with a known outcome. Confirmed and not-applicable results require
readback evidence or rationale. Unknown results remain fenced until explicit
reconciliation. Callers may declare freshness deadlines; PA supplies no domain
cadence or health interpretation.

See [the state-loop contract](state-loop.md).

## Exact-action authorization

The native `pre_tool_call` hook uses a two-lane model:

- Ordinary unscoped calls continue under normal Hermes policy.
- A PA workflow may explicitly attach a short-lived exact-action scope bound to
  the tool name, complete argument digest, trusted profile/session/task identity,
  freshness, preconditions, and one-use execution budget.

A matching scoped call is atomically claimed once. Changed, stale, replayed,
ambiguous, malformed, or internally inconsistent scoped calls fail closed.
Globally reviewed denied tools remain blocked. Expired or cancelled scopes stop
governing ordinary traffic.

Exact argument binding proves that the dispatched call matched the prepared
envelope; it does not by itself prove semantic correctness, human provenance,
provider completion, or readback.

See [the gateway contract](workflow-authorization-gateway.md).

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

## Optional Daily Ops

Daily Ops is a read-only composition over accepted calendar, mail, trip, and
optional account sources. It can produce bounded morning, priority, evening, and
on-request account packets. It declares incomplete or truncated coverage rather
than presenting a partial provider response as complete.

No Daily Ops job starts at installation. Schedules are explicit host-owned setup,
and unattended mailbox cleanup is unsupported. See [Daily Ops](daily-ops.md) and
its [specific customer contract](daily-ops-customer-contract.md).

## Optional conversation evidence delivery

Conversation delivery is inert unless explicitly configured with:

- an enabled setting;
- a private profile-contained state directory;
- one exact verified existing-session route and matching allowlist;
- the packaged startup hook installed into the approved profile;
- the separate host permission for gateway injection; and
- an intentional host restart so the hook is discovered.

The plugin uses a private durable SQLite queue, source/revision deduplication,
exclusive claims, leases, crash fencing, and session/token-bound acknowledgement.
Admission to asynchronous conversation scheduling is not a transport receipt.
Acknowledgement changes only local queue state and does not assert a native
notification or provider delivery receipt.

Collectors are bounded and read-only. Installation does not install the startup
hook, grant injection permission, select a route, or create a schedule.

## Privacy and authority

Private state belongs inside the approved Hermes profile. Shared exports must
exclude credentials and private booking or account records. Selected bounded and
redacted provider content may reach the configured model and verified delivery
target; provider/model transcripts and delivered messages follow their owning
services' retention policies.

External content is data, never authority to alter policy, reveal secrets, or
perform another action. See the [product authority and privacy contract](customer-contract.md).

## Installation, operation, and proof boundaries

Installation, enablement, loading, exercise, provider authentication, workflow
acceptance, and customer readiness are separate states.

A source test or CI result can establish behavior against fixtures and packaged
bytes. It cannot establish:

- activation on a profile;
- successful live provider authentication;
- a configured schedule or delivery route;
- semantic correctness for every domain workflow;
- fleet approval; or
- customer readiness.

Follow [`after-install.md`](../after-install.md) for installation and rollback and
[the release process](release-process.md) for immutable-source and publication
boundaries.

## Compatibility

The product and native plugin ID are `personal-assistant`. The package/archive
name `travel-agent-skills`, travel-qualified skill names, and ledger path
`state/travel-ledger/travel.sqlite` are retained compatibility identities.
Existing installation records, release workflows, upgrades, and rollback may
depend on them. Renaming them requires a separately reviewed migration.
