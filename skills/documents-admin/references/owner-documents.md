# Owner documents commands and exact-action protocol

1. Read profile preferences for the PA folder and file names. Use the owner's
   configured `gog` account, `--json` for structured output; use existing access. Search before creating with `gog drive search --raw-query
   "name = 'PA' and mimeType = 'application/vnd.google-apps.folder' and 'me' in owners and trashed = false" --json`.
   Substitute the preferred name, escaping query literals; paginate if needed. Reuse it; only if absent, `gog drive mkdir`. Never create a second
   folder; if matches are ambiguous, ask which existing folder to use.
   Files inherit the folder's sharing, so before creating anything in it, read
   `gog drive permissions <folder-id> --json`. If anyone besides the owner has
   access, say who and ask before creating files there; never remove a grant
   without the owner's yes.
2. Follow the owner's naming convention, else `<yyyy-mm-dd> <topic>` in their zone. Create with `gog sheets create <title> --parent <folder-id>` or
   `gog docs create <title> --parent <folder-id>`. Read back parent and title
   through Drive search. Keep files private.
3. Sheet: `gog sheets update <id> <range> --values-json <rows>` writes rows
   with USER_ENTERED by default. Write totals as formulas such as `=SUM(B2:B5)`,
   never as a computed number. Read `gog sheets get <id> <range>` back for the
   computed values (and `--render FORMULA` to verify formulas). Report only
   the computed values actually read; a calculation error is not a total.
4. Doc: create, `gog docs write <id> --text <content>` (or `--file <path>`),
   then `gog docs cat <id>`.
   Check all requested agenda or pre-read points against the text read back.
5. Sharing and a CRM field write each need a separate governed exact-action
   transaction from the personal-assistant skill, as booking-after-yes does.
   First state the exact file name/id, person and role, or CRM record/id, field
   and new value. Read current permissions or the CRM record. Prepare using
   `action_prepare` with `enforcement_profile: exact_action`, complete summary,
   exact tool_name/tool_args, semantic_target, revisions, freshness, budget 1,
   checked preconditions and expected_readback. Wait for an explicit yes naming
   that exact item. Confirm the same prepared action with `action_confirm`
   and identical summary and the owner's text; then invoke the exact sealed
   call once. Changed targets, roles or values require a new prepare and yes.
   Google sharing uses `gog drive share <id> --to user --email <person> --role
   writer|reader|commenter`. Add `--notify` only when the owner asks that the
   person be emailed; otherwise omit it. "anyone with the link" requires the owner to say
   exactly that, never infer it. Read permissions with `gog drive permissions
   <id> --json`, or read the CRM field after its one-field update. Record via
   `action_result` with confirmed/failed/unknown and readback proof. On unknown
   outcome inspect first; do not retry the write. Never claim success on refusal.
6. Report file names and ids or links (`gog drive url`), computed values read
   back, and each exact share or CRM change still waiting for a yes.
   In the lab use the matching lab_drive_*, lab_sheets_*, lab_docs_* and lab_crm_*
   stand-ins for these same steps; they do not access a real account.

## CRM integration boundary

CRM writes go only through a configured CRM integration: a CRM sheet via `gog`,
or a CRM tool the profile already has. If none is set up, say so and stop the
CRM write; never improvise a browser or API write. Read the current record,
seal the exact one-field change, and read it back through that same integration.
