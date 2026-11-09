# Drafts in the owner's voice, and sends after a yes

Junk archive uses the separate exact-list approval path in `triage.md`; it never
permits delete or label operations. A send approval does not authorize archive.

## Before drafting

1. Read the voice: `pa(operation="profile", data={"action":"list","kind":"preference","category":"voice"})`
   and the manual's Voice section (tone and sign-off per audience).
2. Read the person: `pa(operation="profile", data={"action":"list","name":"<name>"})`
   and follow their rules (formality, language, channel).
3. Read the thread itself with a read-only call
   (`gog -a <account> --readonly gmail thread get <threadId> --json`). The
   Daily Ops packet holds aliased senders and no bodies; quote nothing from it
   as if it were the message.

## Drafting

Answer the actual request and deadline, grounded in the thread and the ledger;
never invent facts, prices or dates. Keep it short in the owner's register.

- **Provider draft** only when the owner opted in to drafts in setup
  (`rights_drafts`, Daily Ops `inbox.drafts.accepted: true`) and the gog grant
  includes `gmail.compose`. Save it in an owner-attended turn:
  `gog -a <account> gmail drafts create --thread-id <threadId> --to <addr> --subject <subject> --body-file <file> --json`,
  then read it back with `gog gmail drafts get <draftId> -a <account>` and record the draft
  ID with `pa.action_upsert` on the thread row.
- **Otherwise** keep the text in the digest or the chat and call it a local
  draft. A scheduled run never saves provider drafts.

When the owner edits a draft before sending, record the differences as `voice`
preferences (see the base skill's Owner memory).

## Send

Only after the owner's explicit yes to that exact text and recipient list:
`pa.action_prepare` with `enforcement_profile: "exact_action"` and the complete
command, then `pa.action_confirm`, then the one exact call. Prefer a command
that carries the approved text, recipients and attachments itself
(`gog -a <account> gmail send ...`, or the profile's Hermes mail tool), so the
exact-action approval binds the content. A saved draft's ID does not bind its
content: send a provider draft by ID (`gog -a <account> gmail drafts send
<draftId>`) only after reading the draft back in the same turn and finding its
text, recipients and attachments identical to what the owner approved. Read the sent message back
(`gog gmail get <messageId>`), call `pa.action_result`, and move the thread
row to `waiting_on_them` (a vendor chase row already is: clear its
`waiting_for`) or close it with `confirmation`. Changed text,
recipients or attachments need a new yes.
