# Browser And Auth

Use an existing profile credential integration, saved sessions, and the configured browser route. If the route cannot progress, use another attended browser while preserving the cart checkpoint. Store any user-authorized credential only through the profile's existing credential integration.

Provider login and verification are execution steps. Fill/use saved credentials, click visible verification controls, hand a visible CAPTCHA to the user (the live view link in a Browserbase session, where CAPTCHA solving is off), and keep the checkout session alive. Do not call an email login modal a CAPTCHA unless a CAPTCHA challenge is actually visible or detected.

Use account descriptors, payment descriptors, and credential reference descriptors in final confirmation summaries. Do not repeat raw credential, cookie, token, card, or identity-document values in user-facing output.
