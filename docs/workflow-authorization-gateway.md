# Workflow-Agnostic PA Action Gateway

- **Status:** Implementation candidate
- **Decision owner:** Personal Assistant plugin maintainers
- **Product owner:** the workflow owner
- **Release impact:** none

## Decision

Register one workflow-agnostic `pre_tool_call` callback from the Personal Assistant plugin. Ordinary calls remain under normal Hermes policy. A PA workflow may explicitly attach a short-lived, server-bound exact-action scope that the callback validates and atomically consumes immediately before dispatch.

Hermes plugins support `ctx.register_hook("pre_tool_call", callback)` in CLI and gateway sessions. Therefore this design does not require a config-driven shell hook, matcher, command allowlist, or administrator-owned executable path.

## Architecture

```text
Workflow checks its project policy
        ↓
PA records an exact authorization envelope with trusted runtime scope
        ↓
Hermes invokes PA's native pre_tool_call callback
        ↓
deny policy → scoped lookup → exact-match → atomically claim once
        ↓
allow or block before provider dispatch
        ↓
provider readback and reconciliation
```

The gateway is action-aware but workflow-opaque. It knows the generic authorization protocol, exact tool name, complete argument digest, server-injected profile/session/task identity, reliability profile, freshness, preconditions, and one-shot execution budget. It does not contain email-, calendar-, client-, or workflow-specific business logic.

## Native registration and fail-closed behavior

The plugin entry point registers both capabilities:

```python
def register(ctx):
    ctx.register_tool(...)
    ctx.register_hook("pre_tool_call", enforce_action_authorization)
```

Hermes bounds plugin callback duration through `plugins.hook_callback_timeout`; timed-out `pre_tool_call` callbacks fail closed. The PA callback catches scoped enforcement errors and returns an explicit block directive. Calls with no matching active scope pass without consuming authorization state.

`plugin.yaml` declares `provides_hooks: [pre_tool_call]`, allowing plugin validation to compare declared and actual registrations.

## Classification

Every call follows one of three lanes:

- **Denied:** a tool in the reviewed always-denied set is blocked.
- **Scoped:** a fresh authorization for the same server-injected profile/session/task and exact tool activates exact-argument, one-shot enforcement.
- **Unscoped:** every other call passes through to normal Hermes policy without touching PA authorization state.

Unknown tools are unscoped by default. A workflow cannot enlarge the one-shot execution budget, supply profile/session/task identity, bypass complete-argument binding, or disable the hook.

### Degraded mode when PA state is unavailable

The callback classifies a fixed set of local, read-only diagnostic tools (`read_file`, `search_files`, `session_search`, `skill_view`, `skills_list`) before it constructs the PA ledger. These calls pass even when durable state is missing, unreadable, locked, or malformed, so an operator can still inspect the host. They cannot carry a governed scope: `authorization_prepare` rejects them, and the always-denied policy still applies.

When ledger construction fails, every other call is blocked with `DENY_STATE_UNAVAILABLE`, a sanitized `diagnostic_code` (`STATE_UNAVAILABLE_MISSING`, `_PERMISSION_DENIED`, `_LOCKED`, `_MALFORMED`, or `_UNKNOWN`), and a short recovery hint. Paths and raw exception text are never returned. Construction failures are not cached, so the next call retries and normal enforcement resumes once storage is readable. Degraded mode performs no repair, migration, or restoration.

## Authorization envelope

A workflow calls `pa(operation="authorization_prepare")` with:

- protocol, action ID, workflow ID and revision;
- exact tool name and complete JSON argument object;
- reviewed reliability profile (`exact` initially);
- risk class and authority metadata;
- source revision and freshness deadline;
- execution budget exactly equal to one;
- required projections and their precondition states;
- expected provider readback contract.

The registered PA handler injects the active profile, session ID, and task ID from Hermes runtime metadata; caller-supplied identity fields are rejected. PA canonicalizes and hashes the complete argument object, stores only the digest, and rejects unsupported envelope fields. `authorization_confirm` records a digest of confirmation text rather than the text itself. `authorization_cancel` closes an unused scope, and `authorization_status` returns redacted state.

## Pre-dispatch algorithm

For each callback:

1. Validate tool name and argument shape.
2. Load the reviewed policy.
3. Block a tool in the reviewed always-denied set.
4. Look for a fresh authorization bound to the server-injected profile/session/task and exact tool.
5. If no active scope or fresh replay tombstone matches, return `None` without touching PA authorization state.
6. Canonicalize all arguments and compute SHA-256.
7. Within an active scope, reject changed arguments, ambiguity, or open state.
8. Atomically claim with SQLite `BEGIN IMMEDIATE` before dispatch.
9. Retain the fresh claimed row as an exact replay tombstone.
10. Write a redacted allow/block receipt.
11. Return `None` to allow or a Hermes block directive to deny.

Changed arguments, ambiguity, or replay block only inside the matching server-bound scope. Expired or cancelled scopes close cleanly and no longer govern ordinary calls. Another session or task is unaffected.

## Authority limitation

Exact binding and one-shot consumption do not prove who originated confirmation. The current workflow invokes `authorization_confirm` through the PA tool, so workflow code could fabricate confirmation text.

Before release, reviewers must decide whether this is sufficient for the intended risk level or whether protected calls should use Hermes's native `{"action": "approve"}` human-approval directive. Unit tests do not resolve this semantic authority question.

Provider readback remains mandatory after dispatch. Gateway authorization does not prove that a provider completed the requested action correctly.

## Workflow freedom

Without changing the plugin or Hermes configuration, the workflow owner may change:

- workflow IDs, steps, branches, prompts, and terminology;
- project-owned contracts, projections, deterministic checks, and freshness rules;
- exact provider arguments for a newly prepared action;
- approval presentation, provided it does not weaken the enforcement floor;
- fixtures, simulation, readback, reconciliation, and workflow rollback.

A reviewed plugin release is required to weaken or bypass registration, change the scoped lookup or atomic-claim mechanism, alter callback failure behavior, or change the always-denied policy. Connector credentials and managed account bindings remain separate platform controls.

## Evidence and tests

Required synthetic proof:

- native plugin loading registers `pre_tool_call`;
- an ordinary unknown or Calendar fixture passes without a scope;
- exact authorization allows once;
- exact replay blocks;
- argument mutation and ambiguity block inside the matching scope;
- another session/task remains unaffected;
- expired and cancelled scopes no longer govern ordinary calls;
- caller-supplied identity is rejected;
- concurrent identical calls allow exactly one claim;
- policy/callback evaluation failure returns `DENY_INTERNAL_ERROR`;
- PA state initialization failure returns `DENY_STATE_UNAVAILABLE` for non-diagnostic calls while read-only diagnostics pass;
- pass-through works without protected-action state;
- denied calls never reach a fixture provider;
- receipts contain only hashes, IDs, timestamps, policy identity, and reason codes.

Implemented reason codes include:

- `ALLOW_CLAIMED`
- `DENY_ADMIN_POLICY`
- `DENY_INVALID_PAYLOAD`
- `DENY_ACTION_MISSING`
- `DENY_ALREADY_CLAIMED`
- `DENY_ACTION_AMBIGUOUS`
- `DENY_INTERNAL_ERROR`
- `DENY_STATE_UNAVAILABLE`

## Release, activation, and rollback

1. Review the native registration, policy, failure behavior, and authority limitation.
2. Require exact-head CI and normal repository approval.
3. Package and install the exact merged plugin without automatically enabling it.
4. In an isolated profile, verify plugin identity, `provides_hooks`, and actual hook registration.
5. Run denial, allow-once, replay, mutation, concurrency, timeout, and internal-error proofs with zero provider effects.
6. Separately authorize active-profile activation and any live provider test.

Rollback by disabling/restoring the previous PA plugin version, verifying candidate hook removal, and preserving the ledger and redacted receipts. Never retry an uncertain provider write merely because activation or rollback failed.

## Proof boundary

A reviewed and green PR proves source behavior and synthetic native-hook coverage only. It does not prove merge, release, installation, activation, live provider interception, or customer readiness.
