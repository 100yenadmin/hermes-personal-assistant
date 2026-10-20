# Checkout Login Recovery

Use this reference when a provider checkout is stuck on login, CAPTCHA, address validation, provider verification, or an account wall.

## Remote Browser Gotchas

- Create through `pa(operation="browser_session", data={"action":"create"})`; attach with `agent-browser --session <task-name> connect <connect_url>`; `browse open --cdp` cannot attach to Browserbase.
- Use `agent-browser --session <task-name> press Enter` when clicking a provider login button does not progress.
- Recover a fresh handoff link with `pa(operation="browser_session", data={"action":"live_view","bb_session_id":"<id>"})` (a step in another tab uses that tab's link from `tabs`); release when done or abandoned with `pa(operation="browser_session", data={"action":"release","bb_session_id":"<id>"})`.
- Send the live view link for card, OTP, passport, or CAPTCHA entry and wait for the user. Do not snapshot or read back payment fields after handoff; the user's final tap completes checkout.
- Timeout budget: hosted sessions cap at 20 minutes. Page open is 120 seconds. Poll active shopping at 60-second intervals; checkpoint non-sensitive cart/address/session details before expiry. Recording, logging, and CAPTCHA solving are disabled.

## Checkout Checkpoint

After each meaningful step, record a compact checkpoint:

- Browserbase `bb_session_id` and expiry, never connection or live view URLs.
- Provider, store, product/cart summary, quantity, address/route, delivery/pickup window, and selected payment descriptor.
- Current total and visible required fields.
- Whether the agent is before login, after login, before payment selection, at final confirmation, or blocked on a provider-required field.

Before creating a new browser lane, reattach to the last session: get a fresh `connect_url` with `pa(operation="browser_session", data={"action":"connect","bb_session_id":"<id>"})` and attach it with `agent-browser`. If expired, create a bounded session and restore from the checkpoint. This route does not persist login Contexts; use another configured attended browser if recovery fails.

If the user's final submit reveals a required field, the task is not complete. Hand it back in the live view, update the checkpoint without sensitive values, and wait.

## Provider Login State Machine

Classify what is actually visible before reporting a blocker:

1. If the page shows only an email/login modal, call it `login modal`, not `CAPTCHA` or `reCAPTCHA`.
2. Fill the saved email or delegated provider username, click Continue, then snapshot.
3. If the same modal remains, try Enter from the field, click Continue again, inspect visible validation text, and check whether the button is disabled or an overlay intercepted the click.
4. If password, phone, Google, Facebook, passkey, or magic-link options appear, use the saved credential/session lane or the provider login method the user delegated. Use connected email/SMS/device lanes when available instead of handing the whole task back.
5. If a visible CAPTCHA or bot-check appears, send the live view link with the exact step and wait for the user. Near expiry, checkpoint non-sensitive progress and create a fresh bounded session if needed.
6. Preserve the cart, address, selected store, and delivery window across retries. If a remote session is live, reconnect or hand it off before stopping it.
