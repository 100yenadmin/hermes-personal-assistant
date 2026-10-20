# ElevenLabs → PA/Hermes inbound bridge (draft, issue #4)

Status: source implementation and synthetic validation only. This is NOT an
installed phone service, a latency pass, a delivered Telegram message, or a
successful live canary. No release/version bump. `none` and `sim` remain defaults.

## Decision

Choose (a), with a deliberately narrow adapter rather than a public general
Hermes API: ElevenLabs Custom LLM → authenticated PA Chat Completions ingress →
call-scoped Hermes `AIAgent`. ElevenLabs retains native Twilio integration,
ASR/TTS, endpointing, interruption handling and call termination. Hermes produces
the actual reply, not just a suggestion to an independent front model.

The initial scope is one owner-approved inbound **message-taking** call. It is
not standing answering authority, caller authentication, arbitrary access to the
owner's assistant, outbound calling, or a booking/payment agent. The worker gets
only the approved brief and this call's transcript. “Eva supplies the decision”
means a bounded Hermes worker commissioned by Eva, not importing Eva's personal
memory or pretending to be the human. Broader capability needs a separate grant.

Alternatives:

- (b) Fast front model plus decision webhook can reduce routine speech latency,
  but the front model still controls what is said. Requiring a Hermes decision
  before every substantive reply retains the Hermes delay; letting it answer
  independently changes the outcome. Do not silently switch to this architecture.
- (c) Speech Engine/WebSocket + owned Twilio Media Stream offers more transport
  control, but needs a new audio relay and Twilio routing. It is unnecessary for
  the existing native integration's first inbound canary. Consider it only after
  measured HTTP/turn-taking bottlenecks justify the added operational surface.

## Authority and lifecycle

1. Configure `calls.transport: elevenlabs`, one exact staging `agent_id`, and
   `calls.handoff` using the existing PA conversation-delivery settings shape.
   This does not start a listener, queue consumer, tunnel or call.
2. `pa_call prepare` accepts `direction: inbound`, an E.164 destination line,
   purpose, language, `may_share: []`, and `limits.max_deposit: 0`. Its card
   includes AI disclosure, staging agent and exact handoff destination. The brief
   and non-secret route are bound at prepare; changing either requires a new card.
3. Show the card and obtain the owner's explicit yes. `start confirmed:true`
   arms one inbound call; it **never dials**. Repeated starts cannot re-arm it.
4. `/initiate`, authenticated independently of the caller, validates agent,
   called line, conversation ID and Twilio CallSid. It atomically consumes the
   armed card. Retry of the exact binding is safe; a second conversation is
   refused. Caller ID is neither stored nor used for authority.
5. Return `conversation_initiation_client_data` containing the public disclosure
   as `first_message`, language, and `custom_llm_extra_body.conversation_id`.
   ElevenLabs forwards that body as `elevenlabs_extra_body`. Enable only these
   initiation overrides in the separate staging agent.
6. `/v1/chat/completions` ignores supplied system prompts, model selection,
   arbitrary tools, prior provider history and URLs. It uses the bound ledger
   history and latest bounded caller message. A durable turn intent prevents
   retries of an uncertain execution; interrupted/stale generations cannot
   overwrite a completed call.
7. Hermes is constructed with an explicit approved model/provider, no toolsets,
   no memory/context files/SOUL/background review, no trajectories, one iteration,
   a short run budget and an empty fallback chain. Refuse an unexpected nonempty
   tool snapshot. This is **not an OS sandbox**: use a separately provisioned,
   minimal call-only Hermes home, without owner plugins or ambient private data.
8. Only a completed final JSON decision (`say`, `end`, `outcome`) can become
   speech. No reasoning, progress or raw errors are forwarded. No tools can
   perform payments, bookings, changes, outbound callbacks or private retrieval.
   Allowed outcomes are answered/message_taken/needs_approval. The adapter
   requests the explicitly configured ElevenLabs `end_call` system tool for
   goodbye/withdrawal or a 40-turn/15-minute ceiling. Configure a stricter
   **180-second** provider hard limit for the canary; stop on unverified hangup.
9. `pa_call status` reads the ledger. A not-yet-consumed armed card can be
   cancelled. Once active, `pa_call say/end` refuse to fabricate speech/hangup or
   a remote outcome; only signed/provider-read terminal evidence closes it.

## Security and exposure

The listener binds **127.0.0.1 only**. A separately approved HTTPS tunnel exposes
only this narrow service, never the full Hermes API, session endpoints or tools.
No tunnel is started by installation or plugin registration. Provision a stable
reserved ngrok domain or equivalent owner-controlled TLS reverse proxy; confirm
its plan costs and authenticate the route before attaching ElevenLabs. This task
has not installed a tunnel client or approved a hosting subscription.

- `/initiate` and `/v1/chat/completions`: separate high-entropy ingress bearer,
  supplied through ElevenLabs secret/header storage, not the prompt, URL,
  custom body, ledger or transcript.
- `/post-call`: distinct HMAC secret, raw-body `ElevenLabs-Signature` validation,
  constant-time comparison and ±5-minute timestamp check. Duplicate signed
  deliveries are idempotent. Reject unrelated agents/conversations and audio
  webhooks. Never use a shared full-Hermes bearer at the public boundary.
- Bounded JSON bodies, finite socket timeouts and four ingress threads; add edge
  rate limits/IP allowlisting. No redirects or environment proxies on provider
  reads. The reader has only a fixed-host GET-conversation capability.
- Discard metadata, dynamic variables, tool details, phone numbers and auth
  headers from exports. Apply existing PA privacy filtering plus conservative
  credential-line filtering to speech/transcripts/summaries. This reduces known
  patterns; it is not a claim to identify every possible secret or PII.
- Secrets come from the dedicated service environment, never committed source.
  The operator must approve and configure that environment. Do not copy a live
  owner's `.env`, memories, plugins, or configuration into a test profile.

## Post-call handoff to the owner (topic 9 for the pilot)

Use both an HMAC transcription webhook and a five-second fixed-conversation
read poll. Polling reconciles missed callbacks/restarts; it does not discover or
export unrelated calls. Only `done`/`failed` provider state is terminal. Provider
analysis “success” is **not** a booking or authorization. Unknown model execution
or provider failure produces `needs_approval`.

Persist one sanitized terminal snapshot before publishing. Webhook/poll retries
cannot replace it. Chunk the full bounded transcript plus summary, outcome and
brain receipts into ≤6,000-byte facts using the existing private PA queue's
`phone_call` kind. Each part has a stable event identity/revision. No raw audio,
provider receipt or initiation metadata is copied. Oversized/non-text transcripts
are rejected explicitly rather than silently claimed complete.

The queue destination is the exact already-existing owner session route,
verified in normal PA conversation-delivery configuration. For the pilot its
`thread_id` must be `9`; a topic number alone is insufficient—profile, namespace,
chat ID and full host session key are required. The consumer must be explicitly
installed/activated by the authorized owner. Merely calling Telegram sendMessage
would not put the transcript into Eva's Hermes context; this implementation uses
the existing internal injection/ack path instead.

`queued` means durable admission, **not delivery**. The existing `pa_delivery_ack`
from that exact host session proves handled/silent; visible topic delivery needs
its own gateway receipt. In-flight unknowns require existing queue reconciliation,
not blind reposting. Multi-part packets are explicitly labeled and remain
untrusted evidence—not instructions or approval to act on a caller's requests.

The desired **<60 seconds from hangup to owner handoff is not yet proven**.
ElevenLabs sends transcription webhooks after analysis completes; the docs give
no hard one-minute analysis SLA. Polling removes a lost-webhook dependency, not
analysis latency. Record hangup, first provider-terminal observation, all queue
admissions, owner acknowledgments and topic delivery. If analysis exceeds the
budget, a separate authenticated Twilio-terminal callback plus cached-transcript
partial handoff is required; do not label a partial transcript final.

## Latency and cost: evidence boundaries

The acceptance metric is last caller speech → first **substantive audible**
assistant speech at the receiver, <1.5 seconds. Neither component marketing nor
filler (“Let me think…”) passes it. This implementation buffers the complete
small JSON decision, validates it and then emits standards-shaped SSE; it does
not pretend that SSE framing alone is token-streaming or a speed improvement.
Cold Hermes construction/provider reasoning may dominate. The three-second
worker budget is a failure bound, **not a 1.5-second latency promise**.

Current proof: real loopback HTTP/SSE and durable-queue fixtures with a synthetic
brain, and constructor-contract tests. These establish protocol/security/state
behavior only. There is no approved, running call-only model endpoint or public
tunnel in this source change; no Hermes/PSTN turn sample has been obtained. Stop
before live activation if the backend cannot meet the budget. A front model or
a relaxed latency goal requires Eva's explicit decision.

For the canary, retain per-turn trace ID, input/response digests and measured
brain elapsed milliseconds. Correlate them with the provider transcript and
receiver timing. Record cold/warm sample counts, median, p95/max and failures,
plus endpointing/network/TTS breakdown where observable. Do not turn local stub
latency or provider-default calls into Hermes performance evidence.

Public prices inspected 2026-10-20: ElevenLabs Creator $22/month includes 275
agent minutes; extra minutes $0.08, burst $0.16. External LLM and carrier charges
are separate. Reuse existing included minutes only; verify **agent-minute**
entitlement/remaining quota (character credits are not proof), burst off and no
overage before any test. Custom Hermes route cost/quota depends on the explicitly
approved provider/subscription; no fallback or additional paid route is assumed.
Twilio US local inbound is $0.0085/min and Media Streams is $0.0044/min where
billed. A conservative three-minute carrier+stream illustration is $0.0387,
plus existing rental, Hermes/hosting/tax. Native-integration billing must be
checked from the actual receipt rather than assuming that extra leg applies.
Do not charge standalone ASR/TTS again on top of bundled ElevenLabs minutes.

## Deployment/canary gate and rollback

No production runtime/config, live agent, number assignment, outbound call,
new number, country permission, merge or release is authorized by this PR.

Before an inbound canary, the owner must provide/approve:

- a minimal isolated call-brain home, explicit model/provider/quota and workspace;
- exact existing topic-9 session route and queue consumer/ack proof;
- public TLS tunnel, ingress secret, signed post-call webhook and staging agent;
- staging Custom LLM URL, initiation webhook, empty non-system tool list,
  `end_call`, disclosure overrides, native privacy readback (`record_voice:false`,
  seven-day retention), 180-second provider cap, included quota and spend limits;
- Eva's **card comment authorizing exact phone-number reassignment** for the test
  window, and Andrew's availability/AI-processing-transcription consent.

Explicit service entrypoint (variables are operator-provisioned, not inferred):

    HERMES_HOME=$APPROVED_CALL_BRAIN_HOME python -m personal_assistant.phone_bridge_http \
      --profile-root "$APPROVED_OWNER_LEDGER_HOME" --call-id "$APPROVED_CALL_ID" \
      --model "$APPROVED_MODEL" --provider "$APPROVED_PROVIDER" \
      --brain-workspace "$APPROVED_CALL_WORKSPACE"

The environment additionally supplies `PA_PHONE_INGRESS_KEY`,
`PA_PHONE_WEBHOOK_SECRET`, and an approved read-only `ELEVENLABS_API_KEY`.
This command starts no tunnel and alters no agent/phone assignment. It must use
an interpreter containing the approved Hermes source and PA package.

Do one inbound message-taking call from the consenting tester. Use a fresh
non-secret challenge phrase, record its Hermes trace/response digest, and verify
it in the audible reply/provider transcript. Verify termination, no booked or
payment claim, full post-call handoff and exact topic route. Stop on withdrawal,
privacy/route drift, missed latency or uncertain provider state. Reverting the
phone assignment requires the same authorized operator; stop the narrow service
and tunnel after the window, preserving private reconciliation evidence. No
automatic rollback of an unknown provider action.

## Primary references

- [PA #4](https://github.com/100yenadmin/hermes-personal-assistant/issues/4)
- [ElevenLabs Custom LLM/SSE](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm.mdx)
- [Native inbound initialization](https://elevenlabs.io/docs/eleven-agents/customization/personalization/twilio-personalization.md)
- [Conversation initiation payload](https://elevenlabs.io/docs/eleven-agents/customization/personalization.md)
- [Post-call HMAC + analysis timing](https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks.mdx)
- [Conversation read API](https://elevenlabs.io/docs/eleven-agents/api-reference/conversations/get.mdx)
- [Alternative Speech Engine/Media Stream](https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio-integration/custom-llm-integration)
- [Hermes API/full-toolset semantics](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server)
- [ElevenLabs pricing](https://elevenlabs.io/pricing/agents)
- [Twilio US pricing](https://www.twilio.com/en-us/voice/pricing/us)
