# Confirm tomorrow's meetings and brief the owner

The evening register lists `meetings_to_confirm` for tomorrow: event ID,
title, start, end, attendee count and (aliased) attendee emails, read-only.
When `attendees_known` is false, the calendar packet carried no attendee list:
read the event with the calendar tool before drafting, and say so.

## One-page brief per meeting

Keep it to one page (about 300 words):
- **Purpose:** why the meeting exists, from the event, thread or ledger.
- **Attendees:** name, role, and each person's local time and offset for the
  start, from their saved zone; unknown zones are labelled unknown.
- **Agenda:** from the event description or the thread; never invented. If
  none exists, say so and propose three lines for the owner to approve.
- **Open items:** related `pa.next_action` loops, decisions waiting and
  promises made to these people.
- **Prep links:** event link, documents and the last thread, as safe links.

Ground every line in event data, mail or the ledger. Keep attendee details out
of shared summaries.

## Confirmation draft

Draft one short confirmation per external meeting in the owner's voice (read
`profile` category voice and each person's rules first). It names the time in
the recipient's zone. Save it as a provider draft only when the owner opted in
(`inbox.drafts.accepted`) and is in this conversation; otherwise keep it in the
brief. Show it,
and send only after the owner's yes through `pa.action_prepare` with
`enforcement_profile: "exact_action"` and `pa.action_confirm`; then read the
sent message back. No yes means no send; never mark a meeting confirmed
because a draft exists.

## Action items within 24 hours

After the meeting, ask for or read the notes and capture each action item
within 24 hours with `pa.action_upsert` (owner, next step, `due_at`, and
`loop_kind` `our_promise` or `waiting_on_them`), or as linked Kanban tasks.
Promises to others are tracked until the other side confirms.
