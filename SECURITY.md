# Security and data handling

Please report vulnerabilities privately: [open a security advisory](https://github.com/100yenadmin/hermes-personal-assistant/security/advisories/new).
Do not put security problems or personal data in public issues.

We aim to acknowledge reports within 3 business days and to share a decision or fix plan within 14 days.

## Security report scope

- Anything sent, booked, paid, reserved or cancelled without the owner's explicit yes: a bypass of PA's approval gate.
- The owner's data leaving the machine other than as the [README discloses](README.md#what-it-touches).
- One Hermes profile reading another profile's PA ledger.
- An exposed credential.
- A web page, email or message that made PA take an action the owner did not ask for.

For Hermes core vulnerabilities, use [Hermes Agent upstream](https://github.com/NousResearch/hermes-agent/security).
How a model provider handles conversation content is outside this plugin's control.
Ordinary bugs belong in the [bug form](https://github.com/100yenadmin/hermes-personal-assistant/issues/new?template=bug_report.yml).

## What stays out of public reports

Never include the owner's or other people's names, contact details (emails,
phone numbers, addresses), booking references or confirmation numbers,
itineraries or travel dates, calendar or inbox content, message text, payment
details, or the ledger file itself (`state/travel-ledger/travel.sqlite`).
Describe the shape of the problem instead: "a hotel step stopped at the login
page" or "a chase came due a day early". The [report-problem skill](skills/report-problem/SKILL.md)
drafts a report for review and files it only after an explicit yes to that draft.

## Boundaries and disclosure

The [README's disclosure](README.md#what-it-touches) is the detailed account of
storage, hooks, reads, provider calls and optional background work.

**Storage.** PA's main store is one SQLite ledger in your Hermes profile,
`state/travel-ledger/travel.sqlite`. Optional features keep their own stores;
setup can also write approved plain-text files. Nothing is deleted automatically:
"forget" retires a record, and disabling the plugin erases nothing.
The [ledger path guard](personal_assistant/state.py) requires the ledger to remain
within the active profile. Pattern-based data filters are not a guarantee.

**Model and network.** As with any Hermes tool, what the agent reads and writes
during PA work (pages, mail, calendar items, ledger records, the notes the hooks
add) goes to your configured model provider as part of the conversation.
`pre_llm_call` adds short notes to your own turns; these can include owner memory.
Opt-in Daily Ops sends selected mail and calendar items to your configured model
provider. Opt-in conversation delivery sends packet content to the model and
the verified Telegram chat. Other provider requests are described in the README;
PA sends no telemetry.

**Approval.** PA's skills tell the agent to stop every booking, payment,
reservation, order and cancellation at the provider's final page and ask for
your explicit yes for that exact action. The `pre_tool_call` gate enforces
exact-action approval only for actions a PA workflow has scoped; other tool
calls stay under Hermes's own approval policy, and the gate cannot prove that
a person typed the yes. See the [operation contracts](skills/personal-assistant/SKILL.md).

**Installation.** Installation alone starts no jobs, grants no credentials or
provider authority, and enables neither Daily Ops nor conversation delivery.
See [Safe defaults](README.md#safe-defaults). Provider authentication, runtime
qualification, fleet approval and customer readiness remain separate gates.
