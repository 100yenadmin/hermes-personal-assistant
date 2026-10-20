# Phone calls, phase 1: brief → call → transcript

Tracking: [PA #30](https://github.com/100yenadmin/hermes-personal-assistant/issues/30),
with transport acceptance still tracked in [#4](https://github.com/100yenadmin/hermes-personal-assistant/issues/4).

## Decision and boundary

Hermes compiles a brief **before** a call; ElevenLabs' fast hosted front model
handles speech turns inside that brief. Hermes is not the per-turn speaker.
The former `phone_brain`, `phone_bridge` and `phone_bridge_http` draft modules
are removed, rather than retaining an unused, publicly exposed Custom-LLM path.
Their earlier source review and cold-import measurements are historical evidence,
not phase-1 runtime acceptance. There is no HTTP listener, relay, webhook,
subprocess model worker, inference route or automatic scheduler in this design.

This implementation can compile an initiation payload and explicitly collect
finished conversations into the existing PA internal queue. It **cannot** dial,
answer a live line, change an agent or number assignment, authorize a payment,
register `check_with_owner`, or send a Telegram message. Installing/importing the
plugin starts none of these actions. `none` and `sim` keep their existing script
and loopback behavior; `start` with `transport: elevenlabs` returns
`not_activated` without consuming the prepared card. Legacy bridge-owned records
are fenced from `say`/`end`, not silently converted to phase-1 authority.

## Brief compiler

Prepare a normal `pa_call` card, then use `action: compile` with its `call_id`.
Compilation opens the ledger read-only, requires a prepared card and leaves its
state unchanged. `compile_brief(card)` is the equivalent pure Python function.
A compiled payload is **not** evidence that the owner approved or placed a call.
The actual outbound execution/approval binding is a later integration gate.

The schema retains `party_size`, `time_window`, `max_deposit` and `other`, and adds:

- `limits.party_size_range: {min, max}`: inclusive, ordered positive integers;
  a preferred `party_size`, if present, must be inside this range.
- `limits.preferred_time`: the preferred date/time and timezone, as explicit text.
- `limits.time_window`: the owner's exact permitted date/time window and timezone.
- `limits.flexibility`: exact pre-approved flexibility, e.g. `Any table type`.

Time windows remain declarative owner-provided text, not an inferred date or a
machine-validated scheduling interval. Absent choices mean **not approved**.
Use explicit dates and timezones; prepare a new card when material facts change.
`may_share` contains at most 20 exact facts, not permission to retrieve more facts.
`on_behalf_of` is the explicitly allowed name used in an outbound disclosure.
No owner identity, private persona, memory or other profile file is imported.

The return value is the documented `conversation_initiation_client_data` object:

    {
      "type": "conversation_initiation_client_data",
      "conversation_config_override": {
        "agent": {
          "prompt": {"prompt": "mandatory policy + decision table + selected facts"},
          "first_message": "Hello, this is an AI assistant calling on behalf of Example Guest.",
          "language": "en"
        }
      },
      "dynamic_variables": {"pa_allowed_facts": "[\"Name: Example Guest\"]"}
    }

Every generated prompt includes the canonical AI disclosure, decision table,
pre-approved ranges, hard stops for payment, deposit, card, cancellation and
personal data, and the exact default **"I'll confirm and call you back"**.
Japanese/Korean briefs also carry a local fallback phrase. A legacy nonzero
`max_deposit` never grants phase-1 payment or deposit authority. Supplied
`disclosure`, arbitrary prompts, routing/session keys, transcripts, destination
phone numbers and extra ledger fields are not forwarded. Selected public facts
that known privacy filters would rewrite are refused rather than silently
changing the approved brief. Shared phone-sensitive checks reject recognizable
long card-like digit runs (bare, brand-labelled or grouped with repeated
whitespace/hyphens) in all selected public fields, including the verbatim
disclosure name. Inspection-only Unicode/whitespace normalization covers tabs,
NBSP and fullwidth digits; original string leaves are inspected before JSON
escaping. Approved input is rejected, not normalized/repaired. The only
long-number exception is an exact `Callback number: +…` (or `Callback: +…`)
E.164 fact explicitly listed in `may_share`; it cannot appear as a name or be
extended with extra card data. A callback-labelled 13–19 digit value that passes
the payment-card Luhn checksum is still refused: a rare phone/card ambiguity
must go back to the owner, not become permission to disclose card data. Ordinary
shorter callback numbers and non-card-like long callback facts remain supported.
This conservative field-sensitive rule preserves
approved callback facts without treating arbitrary long numbers as public.
These are prompt/schema guarantees, **not** proof
that a live front model always obeys them.

The prompt has an explicitly unavailable future `check_with_owner(question,
options)` slot: no invented owner answer, no tool call in phase 1. A future
approved implementation may hold at most 45 seconds, then fall back. There is
no tool schema, `tool_ids`, server URL or tool registration in the payload.

Applying overrides to an actual conversation is not implemented/activated here.
ElevenLabs requires the corresponding prompt/first-message/language override
permissions in the agent's Security settings; the compiler does not enable them.
For SDK/outbound integrations the approved initiation object is supplied by the
client. Existing inbound Twilio calls need an approved initiation mechanism;
polling cannot inject a brief into a call already in progress. No standing agent
prompt is edited as a shortcut. Check the agent's required dynamic variables
before any later live integration.

## Explicit post-call collection

`ElevenLabsReader` has only fixed-host HTTPS GET operations:

- `GET /v1/convai/conversations?agent_id=…&call_start_after_unix=…&page_size=100`
  plus an encoded pagination cursor;
- `GET /v1/convai/conversations/{conversation_id}`;
- `GET /v1/convai/agents/{agent_id}` for readback.

The key is read from `ELEVENLABS_API_KEY` by the explicit command, never from a
profile file by package code. Use an operator-provisioned read-only key. No
arbitrary origin, redirects or environment proxy forwarding is supported.
Responses have a 1 MiB cap and ten-second timeout; errors expose stable status
text, not provider bodies or credentials.

`PhonePoller(profile_root, config, reader, dry_run=False)` lists only the configured
agent and checks both list/detail identities. Only `done`/`failed` conversations
are terminal; `processing` is retried by a later scan. The caller explicitly
chooses `since` inside provider retention and a page cap (default ten). Every
run rescans that window, rather than advancing a watermark past processing calls.
Pagination loops/invalid cursors fail explicitly; the page cap and per-call
failures report partial coverage. The command exits nonzero for partial coverage.
Provider failure is evidence to review, not permission to retry a call.

A terminal snapshot selects spoken user/agent messages with call-relative times,
start/duration, provider status and a labelled provider-reported summary. It drops
initiation data, caller metadata, tool inputs/results, model reasoning and raw
provider receipts. Known credential/card/passport/link patterns are filtered.
Filtering is deliberately conservative, **not universal PII detection**: selected
call evidence remains private, destination-bound owner data. Do not publish it or
commit real-call fixtures. Limits are 400 raw turn entries, 8,000 characters per
spoken message/summary, and 512 KiB selected evidence; overflow is an error, not
silent truncation. Tool-only/platform-event rows contain no exported speech.

The deterministic owner summary distinguishes outcome, provider report,
unverified agreements and owner approval for any commitment/follow-up. It never
interprets provider `call_successful: success` as a real booking or authorization.
The existing owner session may refine the summary after reading the transcript.
No extra LLM/API generation or provider fallback is used by the poller.

## Queue, deduplication and delivery

Configuration is a non-secret JSON object with `agent_id` and `handoff`. `handoff`
uses the existing [conversation-delivery configuration](../personal_assistant/conversation_delivery/config.py):

- absolute private `state_dir` inside the explicitly supplied owner profile;
- `route.source: existing-host-session`, `verified: true` only after real host
  readback, the exact profile name and namespace;
- the exact existing `session_key`, `platform`, `chat_type`, `chat_id`, `thread_id`
  destination, equal to the sole allowlist entry;
- optional `max_packet_bytes` (4,096–16,384), honored by the producer.

A topic number alone is not a verified owner-session route. Test fixtures use
explicitly labelled fixture routes in isolated directories, never a live queue.

The existing PA queue is the **only** admission/dedup/receipt authority. Each
agent/conversation has a stable hashed event base, numbered `phone_call` packets
and fixed `terminal-v1` revision. The first complete terminal admission freezes
the snapshot; later provider-analysis edits do not create repeat notifications.
Each packet carries a SHA-256 source-content revision. Each full serialized
packet, including escaped JSON, labels and final part counts, fits the configured
byte limit. Parts have explicit index/count facts and are admitted in a single
`QueueStore.publish_many` SQLite transaction; a conflict or failure rolls back
all parts. The existing single-packet `publish` retains its boolean semantics.
Concurrent identical collectors dedup; a conflicting snapshot/route fails closed.
A durable first packet means the whole batch was admitted, so restarts skip it
without a second mutable poller ledger. Publication receipts are read back.

`queued` is **not delivered**. The poller starts no consumer and performs no
Telegram send. An already approved/installed PA conversation-delivery consumer
can later inject the untrusted packets into the exact owner session, with
`pa_delivery_ack` handling/unknown-state reconciliation as before. Multipart
facts are joint evidence; reconstruct by `part_index`, not lexicographic event
ID, and do not treat a partial transcript as final. Do not blindly requeue
handled, silent, unknown or expired packets to force another notification.

Explicit one-shot preview (no local queue writes):

    python -m personal_assistant.phone_poll \
      --profile-root "$APPROVED_OWNER_HOME" --config "$APPROVED_PHONE_JSON" \
      --since "$WITHIN_RETENTION_UNIX_SECONDS"

Only an explicit `--enqueue` admits packets to that configured queue. Preview
prints selected private summaries; keep output private. No job is installed.
Periodic operation needs separate approval for one owner/controller, exact route,
interval, retention, key scope, monitoring and stop/reconciliation behavior.

## Validation and non-goals

Focused tests cover EN/JA/KO disclosure and hard stops, exact fallback, allowed
facts/ranges, the absent tool, pure compilation, simulator compatibility, fixed
GET/cursor behavior, processing/failed statuses, pagination/partial coverage,
privacy/identity failures, quote-heavy multibyte packet bounds, atomic rollback,
concurrent/restarted dedup, route fencing and the default-preview CLI.
Run focused checks only; the full package/archive/release/native-host matrices
belong to GitHub-hosted CI.

A real-call read-only canary may fetch the two pre-existing consenting inbound
tests, preview the owner summaries and rehearse queue admission/repeats in an
isolated fixture route. Retain private proof separately, not in source. Such a
rehearsal proves API parsing and queue admission, **not** live owner-session or
Telegram delivery, memory retention, front-model obedience, inbound brief
attachment, language quality, <1.5-second speech turns or <60-second delivery.
Polling cannot remove ElevenLabs' asynchronous analysis delay or promise an SLA.

Phase 2 (`check_with_owner` and approved outside relay), phase 3 (standing
answering rules), outbound business dialing and persona work remain PA #30
follow-ups. No live agent/number/config change, call, country permission, new
spend, merge, release or runtime activation is authorized by this source change.

## Primary references

- [PA #30 roadmap](https://github.com/100yenadmin/hermes-personal-assistant/issues/30)
- [Per-conversation initiation payload](https://elevenlabs.io/docs/eleven-agents/customization/personalization.md)
- [Override permissions](https://elevenlabs.io/docs/eleven-agents/customization/personalization/overrides)
- [List conversations and pagination](https://elevenlabs.io/docs/api-reference/conversations/list.md)
- [Get conversation details](https://elevenlabs.io/docs/eleven-agents/api-reference/conversations/get.md)
