---
name: airline-check-in
description: Use to prepare and complete airline online check-in after final confirmation, including boarding pass delivery, seats, bags, documents, and final check-in submission.
metadata:
  openclaw:
    skillKey: airline-check-in
  hermes:
    category: travel
    tags: ["travel", "airline", "check-in", "boarding-pass", "confirmation"]
---

# Airline Check-In

Every `references/...` path in this skill is relative to this skill directory.

Prepare airline check-in when the window opens. Ask before final check-in submit.

## Read

- `references/check-in-playbook.md` for airline check-in steps.
- `references/standing-orders.md` for final confirmation rules.
- `references/browser-workflows.md` before using airline websites.
- `travel-ledger` for check-in actions, Browserbase checkpoints, fees/payment readiness, and boarding-pass/check-in proof.

## Workflow

1. Find the itinerary from pasted details, email, calendar, or confirmation.
2. Verify airline, route, dates, traveler, confirmation code, check-in window, and account identity.
3. Open the airline or booking-provider page in the authenticated browser lane.
4. Review seat, bags, boarding-pass delivery, hazardous-material acknowledgement, destination documents, and any fees.
5. Use saved airline credentials, saved sessions, Browserbase, persistent browser profile, and Live Browser fallback to work through login/CAPTCHA/provider friction.
6. Pause only when the provider still requires a human response such as one-time verification, passport upload, visa/health attestation, signature, or document scan.
7. Build a final confirmation summary with kind `airline-check-in`, risk flag `final-check-in-submit`, and added flags for seat changes, bag fees, saved credential use, identity documents, or provider verification. Update `travel-ledger` to `awaiting-final-confirmation`.
8. After confirmation, re-check live fields and submit check-in only if they match.
9. Verify checked-in status or boarding pass availability. Record proof/status in `travel-ledger` before reporting.

## Must Not

- Do not change seats, add bags, alter passenger data, acknowledge legal attestations, or share identity documents without final-state confirmation.
- Do not claim check-in is complete without provider-visible confirmation.
