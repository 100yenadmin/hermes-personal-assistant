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
