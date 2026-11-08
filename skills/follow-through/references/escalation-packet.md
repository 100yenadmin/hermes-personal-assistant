# Escalation packet

An escalation hands the owner a decision, not a problem. Use it when a loop's
`chase.step` is `escalate`: the day 2, 5 and 10 chases did not get an answer.

## Fixed fields

| Field | Content |
|---|---|
| `problem` | One or two sentences: what is stuck, with whom, since when (`opened_at`), and what it blocks. |
| `options` | Two or three concrete options, each with its cost or consequence. |
| `recommendation` | The option you recommend and the reason in one sentence. |
| `decision_deadline` | The date and time, with the owner's timezone, after which the choice narrows. |

Use no other headings. Keep the packet under 120 words. State facts from the
ledger and sources only; label estimates.

## Example

- **problem:** The landlord has not confirmed the boiler repair date. You asked
  on 2 Nov; we chased on 4, 7 and 12 Nov with no reply. The plumber holds the
  slot only until Friday.
- **options:** (1) I draft a firmer note to the landlord for your yes. (2) You
  call the landlord yourself. (3) Book the plumber directly and claim the cost.
- **recommendation:** Option 1, because the lease asks for written notice first.
- **decision_deadline:** Thu 14 Nov, 18:00 JST.

## Where it goes

Put the packet in the next daily brief and in the same chat as the original ask.
Record it on the loop's action with a `chase_log` entry
`{"at":"<now with offset>","step":"escalate","how":"packet in brief and original chat"}`.
After that the loop waits for the owner's decision; do not chase again. Act on
the chosen option with its own approval rules; any third-party send still goes
through `action_prepare` with `enforcement_profile="exact_action"` and
`action_confirm`.
