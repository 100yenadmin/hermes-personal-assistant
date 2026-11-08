# Find a time across people and zones

1. **Inputs.** Duration, attendees, the window to search, and the owner's
   Calendar rules (lengths, buffers, focus blocks, horizon). Read each
   attendee's `profile` person rules and saved zone. An attendee with no known
   zone or hours is asked about once, or labelled unknown.
2. **Busy time.** Read free/busy per attendee:
   `gog -a <account> calendar freebusy <calendarId>,<attendee> --from <RFC3339> --to <RFC3339> --json`.
   Free/busy for people outside the owner's domain often comes back empty or
   unknown. Unknown is not free: propose slots for that person to confirm.
3. **Working hours.** Intersect each person's working hours in their own IANA
   zone, not the owner's. Keep the owner's buffers and protected focus blocks.
4. **DST.** Compute every offset for the actual date. When any participant's
   zone changes offset inside the window, or in the week of a slot, flag it
   ("New York moves to EST on 1 Nov: 09:00 there is 23:00 in Tokyo, not 22:00").
5. **Propose 2–3 slots.** Label each slot with every participant's local time
   and UTC offset, for example
   `Tue 10 Nov 09:00–09:45 Asia/Tokyo (+09:00) · Mon 9 Nov 19:00–19:45 America/New_York (-05:00)`.
   Say which rule each slot keeps (buffer, focus block) and which person's
   hours are tight.
6. **Stop.** No hold, tentative event or invite without the owner's yes on one
   named slot. Then follow `calendar-writes.md`.
