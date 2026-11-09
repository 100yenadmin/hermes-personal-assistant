# Inbox triage, digest and thread tracking

## When

Twice a day, inside the two existing Daily Ops routines: the morning brief and
the evening register both carry `humans_N` (unread human mail), `awaiting_N`
(read human inbox mail from the last 7 days) and `bulk_N`
(bulk counts) for each account. There is no third job. Outside a routine,
triage only a scope the owner names. Read the owner's inbox rules from the
manual (triage times, reply SLA, what counts as urgent, junk handling).

A section with `complete: false` or `truncated: true` was not fully read: say
so in the digest. A failed mail read is a failure to report, never an empty
inbox.

`humans_N` and `awaiting_N` list the first `shown` threads; `omitted` counts
threads that were read but not listed, and such a section is incomplete and
truncated. When `omitted` is above 0, triage the rest before calling the inbox
covered: run a read-only `gog gmail search` for that account with exactly the
section's `query` string and page past the listed threads. Never widen the
query. If you cannot, the digest says how many threads were not triaged.

## Reconcile each pass, before triage

Read every open `pa:inbox:*` commitment row, then re-read its thread through
the mail integration. Record whether the owner replied, a reply was sent or
received, and update the same row using provider evidence and the closure rules
below. This includes tracked threads outside today's section queries.
For every `awaiting_N` thread, inspect the last message and the owner's identity.
If someone else asks or needs something of the owner, treat it as needs you,
set `waiting_for: "owner reply"`, track it (step 3), and hold a draft (step 4).
If the last message is from the owner, do not surface it. Read FYI needs no reply.
Name each read-but-unanswered thread as "read, not answered" in the digest.

## Five buckets

| Bucket | Means | Then |
|---|---|---|
| urgent | Needs the owner today: the manual's urgent rules, a deadline inside the SLA, a VIP | Name it in the digest; track it |
| needs you | A decision, approval or reply only the owner can give | Name the decision; track it; draft when useful |
| handled | Routine work PA can finish or has prepared: a draft reply, a scheduling step, a receipt filed | Count it; track any reply we wait on |
| FYI | Worth knowing, no action | Count it |
| junk | Promotions, newsletters, spam | Count it; report only |

When the Hermes `email-inbox-triage` skill is installed, map its dispositions:
urgent reply → urgent; reply or action → needs you; waiting → handled;
reference → FYI; noise → junk. Read deadlines buried in the body ("by Friday",
"before the 15th") into `due_at`; keep date-only evidence as an ISO date.

## Digest (5 lines or fewer)

```text
Urgent (2): Lease renewal from landlord, sign by today; Client outage report.
Needs you (3): approve Q4 invoice; pick venue for offsite; reply to Dana on hire.
Handled (8): 5 drafts ready for review, 3 receipts filed.
FYI 12 · Junk 9 (report only, nothing archived).
Coverage: work complete; personal truncated at 25 unread.
```

Every urgent item and every decision needed is named, even when lines get
dense. The coverage line is never dropped to save space. No email bodies or
addresses in the digest.

## Tracking rows

Each urgent or needs-you thread gets one commitment row through
`pa.action_upsert`:

- `action_id`: `pa:inbox:<account-alias>:<thread_id>`, where the alias is the
  Daily Ops account key (`work` or `personal`), never an address;
- `action_type`: `commitment`;
- fields: `thread_id`, `bucket`, `waiting_for` (who must act), `due_at` (the
  reply or decision deadline), `decision_needed` (one line, or empty);
- open-loop fields: `loop_kind` `ask_owner` while the owner must decide or
  approve a draft, `waiting_on_them` after our reply when an answer is
  expected; plus `counterparty`, `next_actor` (`owner` | `us` | `them`),
  `opened_at` and `next_step`. Chase dates live in `next_chase_at`, never
  `due_at`.

Update the same row as the thread moves. Close it only when a reply was sent
and read back with nothing expected back, or the owner's decision is recorded:
set `confirmation` (`by`, `at`, `evidence` such as the sent message ID or the
decision) and status completed. A Kanban card marked done is not confirmation.

## Junk

During triage, junk stays report-only. Then offer once per pass, never repeat
the offer in the same pass: "Archive these N junk threads? <subject list>".
Include the exact thread IDs and subjects. This approval covers archive only,
never delete or label. Nothing moves without the owner's yes to that exact list;
a changed list needs a new yes. No yes means leave every thread in place.
After that yes, use `pa.action_prepare` with `enforcement_profile: "exact_action"`,
the exact thread IDs and the provider's archive operation as the final action;
then `pa.action_confirm`; then the archive call once per listed thread; then
provider readback and `pa.action_result`. Bind each call's complete arguments
and one-call budget to its exact-action approval under that single list yes.
If the provider or grant cannot archive, report that limit and leave mail in place.
Daily Ops never mutates mail on its own.
