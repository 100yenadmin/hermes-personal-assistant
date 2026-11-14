---
name: finance-admin
description: Prepare and record invoices and bills with evidence, draft polite overdue reminders, and track pay-by deadlines without making payments.
metadata:
  openclaw:
    skillKey: finance-admin
  hermes:
    category: productivity
    tags: ["personal-assistant", "invoices", "finance"]
---

# Finance admin

To bill a client, see "Preparing an invoice" below. When the owner forwards or mentions
an invoice or bill they already have, use `pa` operation `invoice`, action `record`, with direction `receivable` or `payable`, counterparty,
reference, amount, currency, issue_date, due_date, category and evidence_ref.
Ask for missing facts; never invent money facts or evidence. Describe the evidence by sender, date and
subject, not a raw message id. Add description,
trip_id or remind_days_before (0–60, default 3) when useful.

Receivables follow `personal-assistant:follow-through`: read `next_action`
with `loops_only`, draft polite reminders, and send only after the owner's yes
to the exact recipient and text through that skill's governed send path.
Payables appear as pay-by deadlines in `next_action` with `radar: true`.
Read radar too for receivables: an invoice not yet due surfaces there
`remind_days_before` days ahead, with a courtesy reminder to draft and hold.

Use action `list` to review invoices. Mark `paid` only when the owner gives
evidence or a remittance is seen in authorised mail, with every field at the top
level of `data`: `{"action":"paid", "invoice_id":"<id from list>",
"paid_on":"YYYY-MM-DD", "evidence":"<who sent the remittance, its date and reference, under 200 characters>"}`.
This records what happened. Use `void` with invoice_id and reason for an invalid
invoice. Never initiate a payment or transfer.

For subscriptions and other recurring contracts, read "Contracts and subscriptions" in
`../personal-assistant/references/radar.md` (relative to this skill directory):
notice deadlines, annual costs and a keep-or-cancel decision held for the owner.

When the owner forwards a receipt, record it with `pa` operation `expense`,
action `record`: amount, currency, category, kind, date, merchant and the
receipt number as evidence_ref, on its trip when there is one. Use `export`
with trip_id for the expense report.

Never store card or account details in any field, not even a card's last four
digits or a masked number; keep only a safe reference to the source.

## Preparing an invoice

When the owner asks PA to invoice a client:
1. Gather the billable lines from the owner's words, minutes or time notes: description,
   quantity (hours or units) and unit price. Ask for a missing rate or quantity; never guess one.
2. Use `pa` operation `invoice`, action `prepare`, with counterparty, currency, issue_date and
   lines (quantity and unit_price as strings), plus the owner's terms as `terms_days`, or a `due_date`.
   Add `tax` (`label`, `rate_percent`) only with the rate the owner gives. Without a `reference`, PA takes
   the next number in the owner's series. If `reference_source` is `none`, ask for the owner's numbering,
   then run `prepare` again with that `reference`. If the number carries a year and the year has changed,
   confirm the number with the owner. When several drafts wait for the yes together, give each later
   draft its `reference` explicitly, continuing from the one before. `prepare` writes nothing.
3. Show the draft exactly as returned: number, client, each line with its amount, subtotal, tax,
   total and due date, and any warning (a number already used, a possible duplicate, a draft
   `record` would reject). Payment details come from the owner's own template; never type bank or account numbers.
4. Hold it for the owner's yes. To send it, use the governed send path in
   `personal-assistant:follow-through` with the exact recipient and text.
5. Record it only once it has gone out: after PA sends it on the owner's yes, or when the owner says they
   sent it. Use `record_args` from `prepare`, with `evidence_ref` saying where and when it was sent.
   The chase ladder then follows it. An approved draft that has not been sent is not recorded.
   Never change an amount by hand; run `prepare` again instead.

## Cash position and monthly summary

Use `pa` operation `finance`, action `balance`, with account_label, as_of,
amount, currency and evidence_ref only when the owner states or shows a balance,
with evidence. Never claim a bank balance PA did not get from the owner.
Include action `cash_position` on Fridays inside the owner's existing brief,
or on request. Ask for a fresh balance when one is stale or missing.
A projection is a projection; label it that way. For an account that holds several currencies, put the currency in the label ("Wise USD") so two balances on one date never replace each other.
When the owner asks to close a month, run the month-end close below. Action `monthly`
(month as YYYY-MM, optional export: true) gives a month's CSV and Markdown.

## Month-end close

When asked to close a month, or asked about the previous month on the first working day of a new one:
1. Read the month just ended with `pa` operation `finance`, action `tax_pack`, with `period_start` and
   `period_end` its first and last days (`export: true` only if the owner wants files). Report per currency
   the income, bills paid, expenses and net exactly as read. Never convert currencies.
2. Name what needs the owner from the pack's `questions`: receipts missing, spending to categorise,
   possible duplicates and invoices unpaid at the month's end, each with its one next step
   (forward the receipt, pick a category, check the dates).
3. Use `invoice` action `list` with direction `receivable` and status `open`: name each overdue invoice with
   its chase step, and draft the chases due today, held as in `personal-assistant:follow-through`.
4. Read `next_action` with `radar: true, contracts: true`: name each surfaced contract renewal with its last day
   to give notice and the keep / cancel / renegotiate decision.
5. If the owner's notes list recurring invoices (client, lines, terms), prepare each one for the new month
   as in "Preparing an invoice", numbered in sequence, and hold them for the yes.
6. Give one month-end note: the numbers, the decisions with deadlines, and the drafts awaiting a yes.
   Never send, record, pay or categorise anything on PA's own.

## Card statements

Use `pa` operation `expense`, action `import`, with path under `imports/statements/`.
Preview first with `preview: true`; give every parsed line one category:
`lodging`, `transport`, `food`, `activity`, `shopping`, `services`, `fees`, or `other`.
Check signs and `kind` in the preview, since issuers mark refunds differently.
Import once with all `categories` entries (`line`, `category`); supply currency if the CSV has none.
Report counts by category, skipped lines, and possible duplicates from the reconciliation report.
Overlapping statement files may show possible duplicates; check dates before drafting a refund request.
For each duplicate, draft a refund request naming the merchant, amount and both dates.
Hold it for the owner's yes to the exact recipient and text.
Never dispute, pay or contact anyone on PA's own; never store card numbers.

## Tax-season pack

When the owner asks for the accountant's pack, or their tax year has ended:
1. Use the tax year from the owner's profile; if unknown, ask once for the start and end dates.
2. Use `pa` operation `finance`, action `tax_pack`, with `period_start`, `period_end` and `export: true`.
3. Report per currency the income, bills paid, expenses and net exactly as read, the export file paths,
   and every gap and question: possible duplicates, `other` spending to categorise, receipts missing,
   invoices unpaid at the end, and several currencies (never convert).
4. Offer a cover email to the accountant: the period, the two files, the questions.
   Hold it for the owner's yes to the exact recipient and text through the governed send path.
   Never send on PA's own.
5. No tax advice: never say what is deductible or what is owed; that is the accountant's call.
   Never initiate a payment.
