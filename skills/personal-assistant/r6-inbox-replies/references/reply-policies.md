# Customer and vendor replies under written policy

## Load policies first

Before drafting to a customer or vendor, call
`pa(operation="profile", data={"action":"list","kind":"sop"})`.
Pick the owned or draft SOP whose `trigger` matches the message.
A reply policy is an SOP whose trigger describes a kind of customer or vendor
message. Read its steps, limits and escalation before preparing a reply.

## In policy

Follow the policy's `steps`, offer only what they allow, and stay grounded in
the thread. On the `pa:inbox:<alias>:<thread_id>` row (create it if the
thread has none) record `policy_ref: "<sop title> v<version>"`.
Keep the voice, person rules, draft rights and read-back requirements in
`drafts-and-sends.md`.

## Out of policy

No matching policy, an unclear policy, a request past its limits, or a trigger
in its `escalation` goes to the owner. Examples include an amount above the
limit, a legal threat, or a change to price or terms.
Write no committing draft. A holding acknowledgement that promises nothing
is allowed only when the policy says so; otherwise save no draft for the thread.
Give the owner the escalation packet from `../../references/reporting.md`:
`problem`, `options` (2–3), `recommendation` and `decision_deadline`.
Track the thread row with `loop_kind: ask_owner`, `decision_needed` and
`policy_ref` naming the nearest policy and version, or `none`.

## Vendor timelines

Chase under the matching policy. Track the promised date on the thread row
with `loop_kind: waiting_on_them`; apply the follow-through chase ladder.
If no firm date is evidenced, mark it unknown and ask for one; invent none.
A missing date is what the chase asks for, not a reason to escalate. While the
chase draft waits for the owner's send approval, the row stays
`waiting_on_them` with `waiting_for: "owner send approval"`, which holds the
chase ladder, and the thread is reported as drafted. Clear `waiting_for` once
the chase is sent.

## Every send needs the owner's yes

Never promise a refund, discount, credit, date, price or term that the matching
policy does not allow, and never admit fault or liability.
Keep the existing exact-action send flow and obtain the owner's yes for each
send. No trust level grants send approval.
