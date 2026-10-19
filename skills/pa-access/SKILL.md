---
name: pa-access
description: Route Personal Assistant access through existing Secure Access, attended local Browserbase, managed Browserbase, and optional 1Password callbacks.
metadata:
  hermes:
    category: auth
    tags: ["personal-assistant", "secure-access", "browserbase", "1password"]
---

# Personal Assistant access

Use the existing native `secure_access_list`, `secure_access_check` and
`secure_access_materialize` tools when available. The Python
`personal_assistant.access.AccessManager` helper is a callback adapter for
integration and contract testing; it is not an additional credential tool. It does not install a
vault, create a login, read a profile, or authenticate with a provider.

Inject only already-configured native callbacks.  Their return values are
treated as untrusted metadata and are sanitized before the helper returns
them.  Secure Access materialization is represented by an opaque path, a list
of variable names, and an expiry; values, cookies, bearer URLs, and private
keys are discarded.

The callback shapes are:

```python
secure_access_list(owner_id=None, context_id=None) -> list[dict]
secure_access_check(source_ref, owner_id, context_id=None) -> dict
secure_access_materialize(source_ref, owner_id, context_id=None) -> dict
managed_create(owner_id, provider=None) -> dict
managed_release(owner_id, session_id) -> dict
browserbase_handoff(owner_id, context_id=None, provider=None, attended=True) -> dict
onepassword_resolver(item_ref, owner_id=None, context_id=None) -> dict
```

Secure Access is optional. When its tools are present, rediscover an already
authorized reference, check it, and materialize only when needed. When they are
absent, report the capability as unavailable and use a different already
configured Hermes credential or authenticated-browser route if one exists. Do
not require an Electric Sheep dashboard for an arbitrary Hermes user and do not
create a second login merely because this optional route is absent. Never ask
for passwords in chat or inspect secret file contents for notes. Secure Access
owns temporary-file cleanup.

Use opaque source, session, and context references.  A callback may return
`owner_id` and `context_id` so the helper can verify exact identity, but those
values are removed from returned metadata.  Handoff checkpoints retain only
the context handle, fingerprints, status, lease expiry, and capability flags.
`live_view_url`, `connect_url`, and `debug_url` are never included in a
checkpoint.  A transient Live View URL belongs to the owner-controlled UI
handoff and must not be persisted or returned by the helper.

`acquire(..., cached_session=...)` makes cache use explicit.  A denied,
revoked, expired, or identity-mismatched Secure Access result raises and never
falls back.  If the source is unavailable, an explicitly supplied cache may be
returned with `fallback_used: true` and `fallback_reason` so the caller can
surface that fact.

The managed Browserbase route exposes create/release only.  Its capabilities
explicitly report `context`, `durable_context`, `live_view`, and `debug` as
false.  Local Browserbase handoff capabilities are callback-configured and
`verified: false` until a separate product smoke proves the actual route.

1Password is optional.  If no native resolver is injected,
`resolve_onepassword` raises `OptionalResolverUnavailableError`; do not install
or create a new resolver.  A configured resolver is still metadata-only.

The helper's output is suitable for a ledger checkpoint, but source/fixture
results do not prove provider, customer, fleet, release, or runtime readiness.
