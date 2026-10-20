# Browser And Auth

Use the configured browser route for authenticated checkout, CAPTCHA support, persistent context and session replay. Use another attended browser when it cannot finish a provider step, while preserving the same action checkpoint.

Store user-authorized app credentials only through an existing profile credential integration or authenticated browser profile. Treat saved payment, password, session and cookie state as private profile state.

Provider verification is an execution step. Click through visible verification controls, hand a visible CAPTCHA to the user (the live view link in a Browserbase session, where CAPTCHA solving is off), use connected email/SMS/device lanes when needed, and keep the browser session alive. Do not ask the user to restart or manually rebuild the workflow while a configured lane remains.

Use account descriptors, payment descriptors, and credential reference descriptors in final confirmation summaries. Do not repeat raw credential values in user-facing output.
