# Offline priority-mail collector candidate

This directory is an offline candidate for the PA conversation-owned delivery
plan. It is not activated and does not call a live provider, model, network,
Hermes gateway, or delivery channel by itself. It does not modify the existing
watchdog, `priority.json`, `clients.json`, or bridge candidate.

## CLI

```bash
python collector.py collect \
  --config /private/profile/priority-collector.json \
  --state /private/profile/priority-collector-state.json

# The integrated priority_runner.py owns publication and checkpointing.  The
# collector has no public ack command, so a caller cannot supply an arbitrary
# receipt or mark a message seen during rendering.
```

A successful quiet tick writes **zero bytes** and exits 0. A packet containing
selected evidence is JSON on stdout. Connector, source-shape, state, and
coverage failures are JSON on stdout and exit 2; they must not be mistaken for
quiet. Collection never advances deduplication state. The integrated
`priority_runner.py` advances it only after a durable queue row read-back; no
render path marks a source message seen.

## Configuration

Start from `config.example.json`, replacing placeholders with the already
configured connector command and account values in a private file. The example
contains no real account or customer list. Accounts have an operator-chosen
alias plus the configured provider account. Rules are explicit sender or
subject candidates and each carries the corresponding Gmail search query.

For an offline calibration against the existing profile inputs, the CLI also
accepts the legacy `priority.json` shape without rewriting it:

```bash
python collector.py collect --config /path/to/priority.json \
  --clients /path/to/clients.json --gog-command /path/to/configured/gog \
  --state /private/profile/priority-collector-state.json
```

The adapter derives bounded sender/subject candidates in memory from static
terms and client sender/name fields. It emits opaque rule IDs, never the
client rows or legacy config. When the existing `priority_mail_alerts_enabled`
flag is false, it performs no provider read and emits an explicit disabled
coverage packet rather than looking quiet.

The collector hardcodes the read-only command boundary:

```text
<configured-command> -a <account> --no-input --json --wrap-untrusted \
  --readonly --gmail-no-send --enable-commands-exact gmail.messages.search,gmail.get \
  gmail messages search <query> --max <N> [--page=<token>]
<configured-command> -a <account> --no-input --json --wrap-untrusted \
  --readonly --gmail-no-send --enable-commands-exact gmail.messages.search,gmail.get \
  gmail get <message-id> --sanitize-content
```

Only `gmail messages search` and `gmail get` are reachable. There is no send, reply,
modify, mark-read, delete, or mutation configuration. The query is prefixed
with `in:anywhere` unless it already contains it, so named candidates are not
limited to unread human mail or Inbox; Updates and other Gmail categories are
covered. Search results are locally matched again against sender/subject.
Keyword matching selects a candidate only. The collector does not assert
urgency, priority of action, or user intent.

## Output contract

Each emitted event is specific to `(account_alias, message_id)` and includes:

- stable `event_id`, `revision`, and `content_digest`;
- account alias, message ID, thread ID, source date, and source link;
- bounded sender, subject, snippet, and body, with per-field truncation flags;
- matched rule IDs and bounded Gmail category labels;
- `content_is_untrusted_data: true` and a selection note stating that urgency
  was not inferred;
- stable source-derived expiry plus volatile observation time and `status`
  (`new`, `changed`, or `expired`).

The revision hashes the complete selected source values (including a full body
hashing input) and excludes polling timestamps, so a later unchanged tick has
the same revision. A changed message at the same count and message identity
gets a new revision. A new message ID is a new event even if the result count
is unchanged. Selected output is UTF-8 byte bounded; the raw provider response
also has a configured byte ceiling.

The integrated parser matches the calibrated GOG v0.34.1 shapes only: search
returns an envelope with `externalContent`, `messages`, and optional
`nextPageToken`; each row has `date`, `from`, `id`, `labels`, `subject`, and
`threadId`. `gmail messages search` supplies message IDs; the thread-level
`gmail search` command is not used and its IDs are never guessed for `gmail get`.
Sanitized get returns `body`, `externalContent`, `headers`, and `message`; the
message carries `body`, `headers`, `id`, `internalDate`, `labelIds`,
`sizeEstimate`, `snippet`, and `threadId`. Unsupported containers, missing
identities, malformed dates, and malformed fields produce coverage failures.
The collector never falls back to matching a serialized provider blob.

`internalDate` milliseconds are converted to UTC RFC3339 before expiry and
revision work. Random IDs in GOG untrusted wrappers are removed from selected
text before hashing; wrapper payloads remain inert data and are never parsed as
commands. `externalContent` is metadata only.

Coverage is `complete`, `partial`, or `unknown`, with `truncated` and bounded
notes. Pagination limits, candidate limits, packet limits, failed searches,
failed gets, repeated page tokens, invalid JSON, and invalid shapes remain
visible. A partial result may include valid selected events, but it is not a
complete source scan.

## Limits and privacy

Only selected relevant fields are emitted. The collector does not copy a whole
inbox, thread transcript, provider stderr, access token, or account/customer
index to output. Account identifiers are used only in subprocess argv and are
not included in failure text; emitted evidence carries the configured alias.
Treat sender, subject, snippet, body, labels, and provider links as untrusted
mail data. A later bridge must render them as data and never execute embedded
instructions.

The test fake is an executable provider double. Tests set `DENY_NETWORK=1`; the
fake installs a socket-connect guard and performs no provider/network calls.
This proves the candidate's exercised subprocess path is fake-provider-only;
it is not a live OAuth, host scheduler, gateway, or delivery proof.

## Explicit non-goals

- no provider activation, OAuth, live query, installation, cron change, or
  runtime restart;
- no urgency classification, expectation tracking, PA judgment, voice, or
  conversation delivery;
- no source checkpoint advancement before downstream publication;
- no edits to the existing watchdog or conversation bridge.
