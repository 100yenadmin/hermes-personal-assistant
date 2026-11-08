# Calendar writes, invites, declines and reschedules

PA writes nothing itself. The agent writes with the profile's own calendar tool,
Google through `gog` first, in its own tool call and only after the owner's yes.

## Before any write

- **Authority.** Write only to a calendar the owner opted into during setup
  (`cal_write`), recorded in Daily Ops as `calendar.write_scope` with
  `accepted: true` and `calendar_ids`. Guest notifications need
  `invites: true` there. Without the opt-in, prepare the packet and stop; the
  owner grants write access in a terminal (see the Daily Ops skill), never you.
- **Rules.** Read the manual's Calendar rules: meeting lengths, buffers, travel
  time for in-person events, booking horizon and protected focus blocks. Keep
  the buffer before and after neighbouring events, and never book over a
  protected focus block or a sacred recurring meeting. If no buffer rule is
  saved, say so instead of inventing one.
- **Times.** Every time is RFC3339 with an offset (`2026-11-10T10:00:00+09:00`)
  plus an IANA zone (`--timezone Asia/Tokyo`, or `--start-timezone` and
  `--end-timezone` when they differ). Never a bare local time or an
  abbreviation such as PST.
- **Conflicts.** Read the target window back (`gog calendar events` or
  `gog calendar conflicts`) immediately before proposing.

## Dry run, packet, yes

1. Run the exact command with `--dry-run` first. The dry run carries no
   `--send-updates`; it proves the arguments, not the notification.
2. Show one approval packet: title, calendar, start and end in the owner's
   zone and each attendee's zone, buffers kept, location or video link,
   every attendee address, and in plain words whether guests will be notified
   (`--send-updates all`) or not (`none`). For a recurring event, name the
   scope: this instance, this and following, or the whole series.
3. Wait for an explicit yes to that packet. A changed time, attendee or
   notification choice needs a new yes.

## Executing

- **Private event** (no attendees, nobody notified): run the command without
  `--dry-run`, then read it back.
- **Anything that notifies someone** (an invite, a guest-notifying update, a
  decline, a reschedule): call `pa.action_prepare` with
  `enforcement_profile: "exact_action"` and the complete terminal tool
  arguments, including the full `gog` command string. The frozen command may
  name `--send-updates all`; no calendar call carries it until the owner's yes
  and `pa.action_confirm`. Then invoke that exact command once.

Command shapes (check `gog calendar <command> --help` on the installed build):

```text
gog -a <account> calendar create <calendarId> --summary <title> --from <RFC3339> --to <RFC3339> --timezone <IANA> --attendees <a>,<b> --send-updates all --json
gog -a <account> calendar update <calendarId> <eventId> --from <RFC3339> --to <RFC3339> --send-updates all --json
gog -a <account> calendar update <calendarId> <eventId> --scope single --original-start <RFC3339> ...
gog -a <account> calendar respond <calendarId> <eventId> --status declined --comment <short polite note>
gog -a <account> calendar create <calendarId> --event-type focus-time --summary <title> --from <RFC3339> --to <RFC3339> --timezone <IANA>
```

`--send-updates` defaults to `none`: an event created with attendees but
without it notifies no one, so it is not an invite. A `respond` reaches the
organizer by itself. As an attendee, propose a new time with
`gog calendar propose-time` rather than editing someone else's event. The
Hermes google-workspace create path has no notification setting; use it only
for private events, and say invites need `gog`.

## Readback before any claim

Read the event back with `gog calendar event <calendarId> <eventId> --json`
and check title, start, end and zone, attendees and their response status. Only
then say "booked" or "invited"; for an invite, the readback must list every
attendee. Record the event ID, calendar, safe proof and follow-up with
`pa.action_upsert`; after an exact-action call, `pa.action_result` records the
outcome. An unknown result is read back, never retried blindly.
