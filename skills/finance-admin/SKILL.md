---
name: finance-admin
description: Record invoices and bills with evidence, draft polite overdue reminders, and track pay-by deadlines without making payments.
metadata:
  openclaw:
    skillKey: finance-admin
  hermes:
    category: productivity
    tags: ["personal-assistant", "invoices", "finance"]
---

# Finance admin

When the owner forwards or mentions an invoice or bill, use `pa` operation
`invoice`, action `record`, with direction `receivable` or `payable`, counterparty,
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

Use action `list` to review invoices. Mark `paid` with invoice_id, paid_on and
evidence only when the owner gives evidence or a remittance is seen in
authorised mail. This records what happened. Use `void` with invoice_id and
reason for an invalid invoice. Never initiate a payment or transfer.

When the owner forwards a receipt, record it with `pa` operation `expense`,
action `record`: amount, currency, category, kind, date, merchant and the
receipt number as evidence_ref, on its trip when there is one. Use `export`
with trip_id for the expense report.

Never store card or account details in any field, not even a card's last four
digits or a masked number; keep only a safe reference to the source.

## Cash position and monthly summary

Use `pa` operation `finance`, action `balance`, with account_label, as_of,
amount, currency and evidence_ref only when the owner states or shows a balance,
with evidence. Never claim a bank balance PA did not get from the owner.
Include action `cash_position` on Fridays inside the owner's existing brief,
or on request. Ask for a fresh balance when one is stale or missing.
A projection is a projection; label it that way. For an account that holds several currencies, put the currency in the label ("Wise USD") so two balances on one date never replace each other.
Send action `monthly` for the previous month on the first working day; pass
month as YYYY-MM and optionally export: true for CSV and Markdown.

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
