# Final Confirmation Summary Fields

Required for every summary: kind, provider, merchant, final action label, confirmation requirement, traveler, summary, risk flags, and evidence.

Required for monetary travel actions: amount, currency, dates, refund policy, payment descriptor, and spend cap when a funded/reloadable lane has a cap.

Required for account access: account descriptor for saved session, saved credential use, browser profile, passkey, or credential lane; credential reference descriptor when the credential lane exposes one. Do not include the credential value.

Required for v1 final actions: data shared for check-ins, delivery address for food, pickup/dropoff for rideshare, and no-show/deposit terms for reservations.

Required for non-monetary actions: recipient and message preview for messages, recipient for calls, calendar visibility and attendees for calendar writes, changed fields and data shared for profile changes.

Never include full card number, CVV, one-time code, password value, passport scan, raw cookie, session token, private key, or seed phrase.
