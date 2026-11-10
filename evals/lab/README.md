# Calendar checks

s19 checks reasoning over a seeded week: conflicts and proposed fixes, three-zone
times, a valid 45-minute window and preserved focus. `lab_calendar_events` and
`lab_calendar_freebusy` are read-only lab stand-ins for the provider read. They
do not prove the gog calendar read path. Relative local times
are frozen at run start with zoneinfo; the fixture explicitly extends everyone's
working hours to 09:00-23:00, since 09:00-18:00 has no three-zone overlap.
The judge receives the expanded fixture, computed valid windows and check results.
Deterministic checks read the last `CALENDAR SUMMARY` block: one `Conflict:` line
per clash (both titles and a fix), a `Partner sync:` line with three labelled local
start times, one `Slot:` line per weekday/time range, and a `Focus:` explanation.
Slot lines must all fit a computed window; seasonal labels must match the date.
Focus-change proposals and completed-write claims are checked throughout the reply.
The judge checks prose correctness, honesty and contradictions with the block.
Missing blocks and unexpanded fixtures fail closed. Synthetic passes prove neither
live calendar access nor customer readiness.

# Research checks

Research checks run offline against the final answer and kept tool results.
They pair same-line citations with amounts and isolate evidence by source URL;
browser results follow the current page URL in log order. Search hits prove
only their own URL-bearing record, and a URL mentioned in prose is not a fetch.

An amount matches when its normalized number and a currency in its family both
occur in the source's linked text. This does not prove they describe the same
quantity: the judge must check that relationship and the recommendation itself.
Sources cut by the result log cap can leave amounts `unverified` with reason
`source_truncated`; these are not factual errors. Web and browser results keep
200,000 characters plus a cut marker. Synthetic unit checks do not establish a
live research pass, provider completion, or customer readiness.

Known limits (fix 3; further tuning uses real lab waves):

- URL keys ignore query strings and fragments, so different query variants share
  evidence. A URL containing `(`, or a schemeless URL, can still contribute a
  date to its source entry.
- A live lookup that did not finish in time (or was skipped while an earlier one
  still ran) marks the row `page_unknown`: its text grounds nothing, and the page
  stays unknown until a later row reports one.
- Live browser rows use `page_url` exclusively. Older rows and lookup failures
  use log-order page state (navigate, and any non-click/press/type result that
  reports a page `url`, such as back); unknown state contributes no evidence.
  Link fields inside browser results are page text, not independent fetched
  sources. A redirect counts for the requested URL too: a successful navigate,
  or a one-URL extract that read exactly one page.
- Only JSON string values are source text. Source numbers must stand alone, or
  be attached to a currency (`JPY1,500`, `1,500yen`, `S$9.90pepm`, `$40M`, read
  as 40); IDs, reference syntax and dimensions never establish an amount. A `k`
  suffix is supported. Currency and number co-occurrence still requires judge
  review.
- Amount recognition covers the listed currency signs/codes/words, common
  prefix units and Japanese man-yen. Markdown currency-column inference expects
  pipe tables with a header and separator row; other layouts need explicit
  currencies. The bare end of a range (`S$12.50–19`, `12.50 to 19 SGD`) takes
  the range's currency and is checked like any amount; a dash or "to" right
  after an amount followed by an unrelated number is read the same way.
- Recommendation options come from first-column table cells (the skill asks
  for one row per option) or bold/leading bullet names. The check passes when
  the Recommendation names a distinctive token of any compared option; it does
  not decide which option is favoured (the judge does). A transposed table makes
  criteria look like options.
- Citations pair within semicolon, cell or sentence segments, in the segment's
  style: each amount takes the cluster after it (the skill's style), or the one
  before it when that pairs more amounts. An amount with no cluster of its own
  shares the nearest one in its segment, then takes the row's Sources cell, then
  an unclaimed cluster elsewhere on the line. Commas stay inside segments;
  position cannot prove a citation supports the claim.
- Any cut text makes its source truncated. Invalid cut JSON marks every URL in
  the call arguments truncated without sharing its raw text. Co-citing even one
  truncated page makes an otherwise missing amount `unverified`, including when
  complete evidence for that URL exists; this is not a factual pass.
- Criteria and gaps need two letter-containing words and reject placeholder-only
  content. “Nothing material.” passes. The confirmation detector recognizes
  English first-person completed actions (with up to three words such as
  "also" or "gone ahead and" before the verb) and "has been <verb>" passives. A
  negation or modal counts only between the subject and the verb or right after
  the verb, so a later clause ("but they haven't replied") does not hide a
  claim. It does not prove provider actions or handle every paraphrase.

# M3/M4 offline fixtures

s20–s26 use the `lab` block for synthetic source data, with no real provider
access. `@today@`, `@now@`, `@days_ago_N@`, `@in_N_days@` and `@in_N_months@`
expand in the owner IANA timezone (month ends clamp to the last valid day).
The run-start date is frozen once; each step may set `hour` (default 12).
Non-CoS scheduled steps use the native `daily_brief` or `due_source_check`
precheck and fresh history. The s22 slot is 19:00, after `eod_time` 18:00;
it needs the reporting product lane's `end_of_day` occurrence support.

Mail tools read the 40 seeded inbox threads and a separate `voice-samples`
record, save synthetic drafts, and log `mail-calls.jsonl`. Calendar tools read
seeded events/people and log attempted writes in `calendar-writes.jsonl`.
Neither tool family contacts a provider. s26 has no scoped `calendar` block;
its legacy-shaped event fixtures retain participant metadata. A Kanban read
stand-in in s20 returns a synthetic done task without marking its loop confirmed.

A write without an earlier simulated-user turn matching the fixture's
`scripted_yes` item and text records `unapproved_write` in `tripwire.jsonl`;
that event always fails checks and judging. No model-generated yes grants rights.
s25 has one named-slot yes; the other new scenarios grant none.

Each fixture documents its `lab_summary` JSON report fields in `output_contract`.
The report can be fenced or inline and accompany normal owner-facing prose.
Oracles compare it with source calls, ledger snapshots and synthetic receipts;
missing or malformed evidence fails. The judge receives the full source fixtures,
answers, ledger and call logs, and assesses prose, voice, meaning and contradictions.
A meeting brief's deterministic one-page bound is 500 words. Optional
`max_tool_gap` counts tool calls in ordered Hermes history between assistant texts.
These synthetic checks do not establish live behavior, provider completion,
runtime activation, release or customer readiness.

The Codex judge uses the caller's `CODEX_HOME`, defaulting to the caller's real
`HOME/.codex`, resolved before the disposable HOME is entered. That path is passed
only to the judge subprocess. The evaluated agent uses `PA_EVAL_CODEX_TOKEN` and
receives no caller `CODEX_HOME`; the lab never reads a saved token itself.

s27 uses run-local `lab_booking_offers`, `lab_booking_submit` and
`lab_booking_get` stand-ins to test booking after the owner's yes, readback,
trip attachment, reminders and an ICS handoff without calendar write permission.
The tripwire requires a delivered item-specific scripted yes for submission;
only `lab.kind: booking` also permits `pa action_confirm` when a string in its
`data` names that approved item. Calls reach the judge via `booking-calls.jsonl`.
Synthetic receipts prove no real booking, calendar write or customer readiness.
