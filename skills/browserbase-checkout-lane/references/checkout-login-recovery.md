# Checkout Login Recovery

Use this reference when a provider checkout is stuck on login, CAPTCHA, address validation, provider verification, or an account wall.

## Browse CLI Gotchas

- `browse cloud sessions create` does not support `--json` in `browse/0.8.2`; capture the default output instead.
- Use `browse eval`, not `browse evaluate`.
- Use `browse key Enter` or `browse press Enter` when clicking a provider login button does not progress.
- Use `browse cloud sessions list`, `browse cloud sessions get <session-id>`, and `browse cloud sessions debug <session-id>` to recover or hand off an active session before creating another one.
- For checkout/login friction, prefer `--solve-captchas --proxies --keep-alive --timeout 1200`. CAPTCHA solving is handled by Browserbase; add `--context-id <provider-context-id> --persist` when saved login state should carry forward.
- Timeout budget: Browserbase hosted sessions cap at 20 minutes (`--timeout 1200`) to avoid credit waste when a browser is left open. Page open is 120 seconds. Instacart/grocery active shopping uses repeated 60-second wait/snapshot/action cycles; when progress continues near expiry, checkpoint cart/address/session details and renew a fresh 20-minute Browserbase session with the same Context.

## Checkout Checkpoint

After each meaningful step, record a compact checkpoint:

- Browserbase session id and Context id.
- Provider, store, product/cart summary, quantity, address/route, delivery/pickup window, and selected payment descriptor.
- Current total and visible required fields.
- Whether the agent is before login, after login, before payment selection, at final confirmation, or blocked on a provider-required field.

Before creating a new browser lane, reattach to the last session. If it expired, create a new bounded Browserbase session with the same Context and restore from the checkpoint. Use another configured attended browser only after reattach or Context restore fails.

If a final submit attempt reveals a new required field, the task is not complete. Ask for or retrieve that field, update the checkpoint, and resume from the same session.

## Provider Login State Machine

Classify what is actually visible before reporting a blocker:

1. If the page shows only an email/login modal, call it `login modal`, not `CAPTCHA` or `reCAPTCHA`.
2. Fill the saved email or delegated provider username, click Continue, then snapshot.
3. If the same modal remains, try Enter from the field, click Continue again, inspect visible validation text, and check whether the button is disabled or an overlay intercepted the click.
4. If password, phone, Google, Facebook, passkey, or magic-link options appear, use the saved credential/session lane or the provider login method the user delegated. Use connected email/SMS/device lanes when available instead of handing the whole task back.
5. If a visible CAPTCHA or bot-check challenge appears, use repeated Browserbase wait/snapshot cycles, not a single short wait. For Instacart/grocery checkout, wait 60 seconds, snapshot, act on the current state, and continue while the page is making progress. If the session nears the 20-minute cap, checkpoint and renew with the same Context. If it still does not progress after several unchanged snapshots, recreate the session with the strongest available Browserbase mode, proxies, keep-alive, and the provider Context before trying another browser lane.
6. Preserve the cart, address, selected store, and delivery window across retries. If a remote session is live, reconnect or hand it off before stopping it.
