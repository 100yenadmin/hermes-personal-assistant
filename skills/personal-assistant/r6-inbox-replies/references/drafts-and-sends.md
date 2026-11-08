# Drafts in the owner's voice, and sends after a yes

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
  then read it back with `gog gmail drafts get <draftId>` and record the draft
  ID with `pa.action_upsert` on the thread row.
- **Otherwise** keep the text in the digest or the chat and call it a local
  draft. A scheduled run never saves provider drafts.

When the owner edits a draft before sending, record the differences as `voice`
preferences (see the base skill's Owner memory).

## Send

Only after the owner's explicit yes to that exact text and recipient list:
`pa.action_prepare` with `enforcement_profile: "exact_action"` and the complete
command (`gog -a <account> gmail drafts send <draftId>` or
`gog -a <account> gmail send ...`, or the profile's Hermes mail tool), then
`pa.action_confirm`, then the one exact call. Read the sent message back
(`gog gmail get <messageId>`), call `pa.action_result`, and move the thread
row to `waiting_on_them` or close it with `confirmation`. Changed text,
recipients or attachments need a new yes.
