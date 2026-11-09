# Customer and vendor report

Load for the weekly review when the owner handles customer or vendor mail,
or whenever the owner asks for a customer or vendor report.

Use the period the owner names; otherwise use the 7 days before today, in
the owner's timezone. State the dates and timezone. Read the relevant threads
in full with the profile's mail read tools, including message timestamps.
Read held replies and open escalations with `pa next_action`; page through
the results and recover details with `pa context`.

Keep the report short:
- Volume: customer threads whose first customer message falls in the window.
- Median first-response time in hours: from each thread's first customer
  message to the first reply from the owner's address. State how many answered
  threads the median uses. Count unanswered threads separately, never as zero.
- Recurring complaints: group by topic in the customer's words; list only
  topics seen at least twice, with counts. Never name customers or their emails
  in the report; use the topic and count.
- Tier-1 replies held for the owner's yes and open owner escalations: read
  these from the ledger and show each item's age from its recorded timestamps.
- Open items: one line each, with the next step and who owns it.

Use facts only from the threads and ledger. Never invent numbers; say what
is unknown, including missing timestamps, owner address or coverage gaps.
This report is read-only: send, draft and archive nothing while writing it.
