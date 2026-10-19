---
name: agent-wallet-payments
description: Optional guidance for an explicitly selected virtual card or payment integration; never required for PA setup.
metadata:
  openclaw:
    skillKey: agent-wallet-payments
  hermes:
    category: travel
    tags: ["travel", "payments", "wallet", "virtual-card", "confirmation"]
---

# Agent Wallet Payments

Every `references/...` path in this skill is relative to this skill directory.

Load this optional skill only when the user has selected a virtual card or
payment integration. PA setup and transaction preparation work with any already
configured payment method and do not require a wallet vendor.

## Read

- `references/payments-provider-evaluation.md` for provider choice.
- `references/browser-auth.md` for wallet versus browser profile boundaries.
- `references/standing-orders.md` for final payment confirmation rules.
- `travel-ledger` for payment readiness, wallet descriptors, missing funds/setup blockers, and proof after paid actions.

## Provider stance

Use the payment integration the user already selected. Keep instructions
provider-neutral and do not recommend, install, or require a vendor as part of
ordinary PA setup.

## Setup Flow

1. Explain the payment lane in one sentence.
2. Open a provider setup page only when the user explicitly asks to configure that provider.
3. Use an existing configured browser route for funding setup, verification, and browser friction. Store user-authorized app credentials only through an existing profile credential integration; do not assume a VM-specific credential lane.
4. Save only a safe payment descriptor and any user-defined limit or expiry after setup.
5. Before using the wallet at the final button, include provider, limit, amount, merchant, final action, and risk flags in the final confirmation summary.

## Readiness Check

Before a paid submission, verify the selected payment method exists and can cover the current total. Include fees, taxes and incidentals when they apply.

If the selected method is missing or cannot cover the total, preserve the same provider context and name one setup or payment-choice action. Do not route every user into this optional skill.

Record readiness in `travel-ledger` as `ready`, `missing`, `underfunded`, `unknown`, or `blocked`, including only safe payment descriptors, budget, currency, funds status, and missing setup.

After the wallet is ready, proceed action-first: log in, fill forms, choose the in-budget option, reach final submit, show one concise final-state confirmation, submit after confirmation, and verify the receipt/status.

## Browser Wallet Guidance

An authenticated browser profile and browser-saved payment state may be used when already configured and authorized. Include only descriptors in final confirmation summaries.

## Never

- Do not print or repeat raw card numbers, CVV, one-time codes, credential values, private keys, seed phrases, raw cookies, or session tokens in final confirmation summaries or reports.
- Do not lecture the user when they delegate credentials for ordinary app accounts. Save them in the configured lane and reply: "Saved. I'll use this for <provider> when you ask."
- Do not use wallet funds for a different merchant, trip, traveler, or amount than approved.
- Do not split charges to avoid a user-confirmed limit or final confirmation.
- Do not click final wallet funding or add a new payment method without the final-state confirmation.
