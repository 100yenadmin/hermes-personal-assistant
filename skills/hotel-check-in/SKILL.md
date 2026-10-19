---
name: hotel-check-in
description: Use to prepare and complete hotel online check-in after final confirmation, including arrival time, room preferences, incidentals deposits, ID/payment gates, and final submission.
metadata:
  openclaw:
    skillKey: hotel-check-in
  hermes:
    category: travel
    tags: ["travel", "hotel", "check-in", "arrival", "confirmation"]
---

# Hotel Check-In

Every `references/...` path in this skill is relative to this skill directory.

Prepare hotel online check-in when available. Ask before final submit.

## Read

- `references/check-in-playbook.md` for hotel check-in steps.
- `references/standing-orders.md` for final confirmation rules.
- `references/browser-workflows.md` before using hotel websites.
- `travel-ledger` for check-in actions, Browserbase checkpoints, incidentals/payment readiness, and checked-in proof.

Use `phone-calls` when a phone call is needed.

## Workflow

1. Identify property, dates, guest, confirmation id, arrival time, room type, and loyalty account.
2. Open the hotel or booking-provider page in the authenticated browser lane.
3. Review arrival time, room preferences, parking, resort fees, incidentals deposit, ID requirement, payment descriptor, and cancellation/no-show terms.
4. Use saved hotel credentials, saved sessions, Browserbase, persistent browser profile, and Live Browser fallback to work through login/CAPTCHA/provider friction.
5. Pause only when the provider still requires human identity response, ID upload, signature, new card entry, or provider-required verification.
6. Build a final confirmation summary with kind `hotel-check-in`, risk flag `final-check-in-submit`, and extra flags for incidentals deposit, saved payment, profile change, or identity document. Update `travel-ledger` to `awaiting-final-confirmation`.
7. After confirmation, re-check visible details and submit only if they match.
8. Verify checked-in status, mobile key status, arrival note, or provider confirmation. Record proof/status in `travel-ledger` before reporting.

## Online Check-In Unavailable

If online check-in is not available but late arrival needs notice, prepare a message or call instead:

- Draft the exact message, recipient, booking reference descriptor, and arrival time.
- Use kind `message` for hotel chat/email/SMS or kind `call` for phone.
- Ask for final-state confirmation before sending or calling, even when no money is involved.
- Verify sent status, chat transcript, email sent item, call summary, or hotel acknowledgement before reporting.
- Record the sent message/call proof in `travel-ledger`.

## Must Not

- Do not upload ID, add payment, sign documents, change guest details, or accept unclear charges without final-state confirmation.
- Do not expose room numbers or sensitive stay details in public notes.
