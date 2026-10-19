---
name: phone-calls
description: Prepare and place an approved business phone call in Japanese, Korean or English, especially when web booking is unavailable.
metadata:
  hermes:
    category: travel
    tags: [calls, confirmation, japanese, korean]
---

# Phone calls

Every `references/...` path is relative to this skill directory.

Use when booking or asking a business by phone, especially where web booking is
not possible, as is common in Japan and Korea. Load `references/phrases.md` for
short polite phrases. This is a text conversation interface. The only connected
transport is the simulator: never describe a simulated conversation as a real call.

1. Recover known trip facts from the ledger; ask only for missing material facts.
2. Use `pa_call` with `action: prepare`, a tight `purpose`, `language: ja|ko|en`,
   `to: {name, number?}`, `may_share: [...]`, `limits: {party_size?, time_window?,
   max_deposit: 0, other?}` and optional `trip_id`. State currency in `other` if any
   fee is permitted. Permission to call is separate from permission to pay.
3. Show the returned `call_card`: destination, purpose, exact facts to share,
   language, time/party constraints, deposit ceiling and AI disclosure. Get a yes.
   Calls are a gated action. Changing material details requires a new card and yes.
   If the user declines or replaces a card, close the old one with
   `end {call_id, outcome: cancelled, summary}`.
4. Only after that yes use `start` with the returned `call_id` and `confirmed: true`.
   Pass `on_behalf_of` at prepare (the name as it should be said, in katakana or
   Hangul) only if sharing the name is allowed; otherwise the disclosure stays generic.
5. For `no_transport`, give the ready script, fill its brief with known facts in the
   target language, and ask the user to call and report the outcome. The generated
   script preserves user-supplied purpose and time text; translate those slots when
   needed before handing it to the user. When the user reports what happened, record
   it with `end {call_id, outcome, summary}` using their words.
   Do not claim to have called, booked or contacted anyone.
6. For an active call use `say {call_id, text}` for each short utterance. Disclose
   first: you are an AI assistant acting for the user. Use polite keigo in Japanese
   and 존댓말 in Korean. Ask one question at a time; never invent facts.
7. Confirm date, time, party size, the allowed name in katakana or Hangul plus
   romanisation, and callback number only if allowed in `may_share`. If a required
   detail is unavailable or private, ask the user or take a message.
8. Accept an alternative only inside the brief's limits. Never agree to a deposit
   or fee above `max_deposit`; say you need to ask the user and use outcome
   `needs_approval`. Do not send payment details or authorize payment through a call.
9. End politely. If the counterpart hangs up, do not continue talking. There is a
   maximum of 40 PA turns and 15 minutes; the ledger retains at most 80 utterances.
10. Use `end {call_id, outcome, summary}`. Outcomes: `booked`, `needs_approval`,
    `no_answer`, `refused`, `answered`, `message_taken`, `handoff`, or `cancelled`
    (a card that was never started). Only record
    `booked` after the business confirms the details. Summarize in the user's language
    and tell the user honestly what happened and what needs their decision.

On `transport_error`, inspect `status {call_id}` before retrying: a send may have
arrived. Never claim success from a failed response. Confirmed uncertain starts
must not be replayed as fresh calls. End with an honest uncertain-outcome summary
when the simulator is reachable again; do not invent provider proof.
