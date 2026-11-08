# M3 exit: 10-working-day Personal Assistant canary

Observe one consented profile for ten working days (Monday–Friday; holidays are
not inferred). The M3 exit requires every row below to pass. Missing evidence is
**unproven**, never a pass. This exporter is an observer; it never changes jobs,
claims, ledgers or provider state. It establishes no rollout or customer approval.

```sh
python scripts/export_canary.py PROFILE_ROOT --start 2026-11-09 --days 10
```

JSON goes only to stdout. There is no `--out` or write mode. Use a private,
consented profile copy for review; never commit profile data or provider receipts.

| Row | Pass condition | Evidence |
| --- | --- | --- |
| Every due routine on time | All expected occurrences claimed within 5 minutes and verified delivered within 60 minutes | Notification claims and provider receipts; unknown cron hand-offs stay unproven |
| EOD note | All ten dates have Done / In progress / Blocked with questions; every blocked item ends in a question | `pa:eod:<date>` note linked to a claimed occurrence and evidence references |
| Broken routine noticed | A deliberately broken working-hours routine is flagged by the other accepted routine within one 5-minute cycle | `pa:routine-health:<kind>` failure and detection timestamps |
| SOP improvement | At least two distinct version bumps, excluding version 1 | Existing SOP changelog entries in the window |
| Owner rescues | Zero rescues, explicitly observed on every date | Daily canary observation; missing is unproven |

## Small evidence contract

R5 records `pa:eod:<owner-local date>` as a note with `occurrence_id`,
`evidence_refs` and `sections`: exact keys `Done`, `In progress`,
`Blocked with questions`, each a nonempty list of short evidence-backed strings.
Use `None evidenced` for an empty section. A cron receipt is `unknown` until
verified provider evidence resolves it; this does not establish delivery.

At each day's close, the consented canary observer records a normal note
`pa:canary:<date>` with `routine_inventory_complete: true`, `owner_rescues`
(non-negative integer, explicitly zero if none), and `due_occurrences`: a list of
`{occurrence_id, due_at}` for **every** expected dynamic due/source/chase occurrence.
An empty list is valid only after checking there were none. Include references
for the inventory and rescues in the note; do not guess missing source history.
Calendar slots from accepted rules (brief, EOD, CoS) are added by the exporter.
Keep acceptance timestamps and profile preferences stable during the observation,
or retain the historical calendar slots in the daily inventory; current rules
alone cannot reconstruct old preferences or source checkpoints.
After a recorded schedule change, reconstructed earlier slots stay unproven
unless the daily inventory retains their historical due times. The exporter
builds calendar slots from current preferences only, so list any occurrence the
owner intentionally held that day (a snooze or pause) in `excused_occurrences`
(occurrence ids); otherwise it scores as missed. Live routine health, unlike the
exporter, delays its grace until a snooze, pause or quiet hours end.

Break a test routine only with the owner's separate authority and an existing
recovery path, during working hours outside quiet hours and snoozes. This
exporter does not inject failures. Failure notes keep `failed_at`, `reason`,
`kind`, and `detected_at` when the other routine claims its exception wake.
No injection/detection observation leaves that row unproven. A late detection
fails. Quiet-hour exception permission defaults off; do not bypass it for a score.

Inspect failing or unproven rows and their daily occurrence identities. Repair
only the proven cause under the owning lane's authority, then repeat the bounded
canary window. Do not expand the cohort on a partial pass. Synthetic exporter
unit tests prove scoring behavior only; the ten-day real canary remains separate.
