---
name: cos-weekly
description: Close out the week in Chief of Staff mode by comparing priorities with the week's evidence and recommendation outcomes, then propose at most one batched improvement.
metadata:
  openclaw:
    skillKey: cos-weekly
  hermes:
    category: productivity
    tags: ["personal-assistant", "chief-of-staff", "weekly", "closeout", "outcomes"]
    pa_mode: chief_of_staff
---

# Chief of Staff weekly closeout

Run from the accepted `cos_weekly` job, the weekly closeout. Use the user's language. Require Chief
of Staff mode; if off, explain `/pa mode chief-of-staff on` in a human turn.
Read `references/recommendation-state.md` for the shared event, retrieval,
delivery and owner-approved follow-up protocol.
Every `references/...` path is relative to this skill directory.

## Compare intent with evidence

1. Read the user's stated priorities from USER.md and the existing operating
   manual. Name the script's `week` and `timezone`. Missing priorities stay unknown;
   ask in chat rather than infer them from calendar volume.
2. Read `pa(operation="next_action", data={"limit":20})` for open loops.
   Recover selected actions with
   `pa(operation="context", data={"kind":"action","action_id":"<returned action id>"})`.
   Read this week's events through already authorized calendar/inbox read tools.
   Report gaps in coverage; never treat a partial read as a complete week.
3. Retrieve CoS notes through `pa(operation="context", data={"kind":"action","limit":20,"offset":0})`.
   Follow `next_offset` and read each relevant `cos:` action in detail as the
   reference explains. Review what came since the previous closeout: the daily
   recommendations, this week's `cos:kickoff:<week>` focus, the last closeout's
   proposal, and older proposals, research decisions or benchmark offers now due.
   Report `used`, `declined`, `ignored`, and `unknown` separately with evidence.
   A yes or a booked slot is not proof that the change helped.
4. Compare priorities with what happened and what remains stuck. Explain one
   useful discrepancy, not an activity score. Do not claim causation from a
   recommendation followed by an unrelated good result.

## Propose at most one batch

Offer no more than one batched improvement proposal, in this exact format:

- Old: the current wording or process, quoted only as far as necessary.
- New: the smallest proposed replacement; reuse what already works.
- Evidence: the observed failure, affected priority, source and expected benefit.
- Rollback: how to restore the old wording or process if it does not help.

Record it on the `cos:weekly:<week>` note (the script's `week`) with every field the reference
lists, including `benefit` and `review_at` (next week's slot), as `stage: "draft"`,
with `outcome: "unknown"`. It is a proposal, never an edit. Show the exact diff and
wait for explicit apply approval in chat. Keep `draft`, `approved`, `applied`
and `verified` distinct in `stage`. Applied requires actual readback;
verified requires evidence of the promised result. Never silently edit
SOUL.md, USER.md, skills or the manual. Never install software.

On the same note, record `carry_over`: the open loops and decisions still needed,
each with its source, or `"none"`. The next weekly kickoff reads it; never set
next week's focus here.

For a consequential skill or process change, propose one cheap check: freeze
two sanitized tool-output cases (the motivating failure and an ordinary case),
compare old and new text on both with the same model and settings, without live
tools. Keep the change only if the failure is fixed and the ordinary case holds.
A tie means “no regression detected”, not “improved”. Label it unchecked when
the cases cannot be frozen cheaply. Do not run this experiment in the cron turn.

Check the manual's byte size. Above about 8 KB, flag it in this same batch and
propose distilling or replacing text, never appending a second manual. Keep
engineering lessons in their own project context. Do not edit to meet the budget.

## Close the week

Read `pa(operation="profile", data={"action":"pending_files"})`; include these in the normal reviewed USER.md/manual proposal. After explicit apply and saved-file readback, call `profile` with `action=mark_filed, identities=[...]` for only those filed records.
Read `pa(operation="profile", data={"action":"list","kind":"trust"})`. Once the oldest non-retired trust record is 30 days old, include one day-30 review paragraph: task types and levels, proposed level changes with evidence, and "Is this saving you time? Roughly how much?" Do this review once: first read `context kind=action action_id=pa:day30-review`; skip if its `asked_at` exists; an "action not found" result means it was never asked, so continue. Record the first ask using `action_upsert action_id=pa:day30-review action_type=note status=completed fields={asked_at:<ISO>}`. Change levels only after the owner's answer. Record the answer with `profile remember kind=preference source=said category=work` and a safe paraphrase; it feeds the parity rule. Chief of Staff mode must be on here; when off, use the daily-ops morning brief once instead.

Then load `personal-assistant:cos-radar` for this week's single benchmark offer,
if any. Include it in the single final response; Hermes delivers that owner message
to the verified destination. Never use a message tool in a scheduled run.
Record a separate recommendation identity for an actual radar
offer, but use only this job's one delivery receipt. If neither review nor radar
contains useful information, record `suppressed` with a safe note and reply exactly
`[SILENT]` (nothing else). For a report, write and read back the note, then record
`unknown` before the final response as the reference says. `delivered` needs a
provider receipt the run cannot see.
Never replay an already handled occurrence.

Send no proactive message outside this scheduled job or an owner-approved HB2
`at` follow-up in the same chat naming `personal-assistant:cos-weekly`.
