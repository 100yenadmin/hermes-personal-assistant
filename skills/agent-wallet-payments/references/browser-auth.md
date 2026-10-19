# Browser And Auth

Payment vaults and credential lanes are separate, but both are usable execution lanes. Browser profiles may save sessions, passwords, passkeys, provider cookies, and browser wallet/autofill state for checkout.

Use the configured browser route for CAPTCHA and provider verification, then another attended browser if needed. Pause when the provider still requires human identity, one-time verification, private-key, or funding-source input.

Use account descriptors, payment descriptors, and credential reference descriptors in final confirmation summaries. Do not repeat raw credential, cookie, token, card, private-key, seed phrase, or identity-document values in user-facing output.
