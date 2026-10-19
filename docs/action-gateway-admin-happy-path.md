# PA Action Gateway — Native Plugin Review and Activation

## Correction

Andrew confirmed that Hermes plugins can register lifecycle hooks directly. The Personal Assistant plugin therefore does **not** need a separately configured shell hook, command allowlist, or administrator-owned `hooks.pre_tool_call` entry.

The supported design is now:

```text
Personal Assistant plugin loads
        ↓
plugin register(ctx) registers pa + pre_tool_call
        ↓
Hermes invokes the plugin callback before every tool dispatch
        ↓
pass ordinary calls, enforce an attached exact scope, or always deny
```

The previous managed-shell-hook proposal is superseded. The legacy launcher and YAML example remain only as reference material while this PR is reviewed; they are not the activation path.

## Human TL;DR

The workflow author is building PA workflows with policy contracts. Ordinary ad hoc Hermes calls must continue to work when the PA plugin is installed. A PA workflow can deliberately attach a short-lived exact-action scope; only calls in that server-bound scope receive PA's changed-argument, ambiguity, and replay enforcement.

The plugin architecture already provides that final checkpoint through `ctx.register_hook("pre_tool_call", callback)`. Installing and enabling the reviewed plugin is sufficient to register the callback; ordinary workflow changes do not require managed Hermes configuration edits.

## Required outcome

The installed PA plugin must:

- run immediately before consequential tool dispatch in CLI and gateway sessions;
- bind authorization to the exact tool and complete canonicalized arguments;
- atomically consume a one-use authorization before dispatch;
- pass ordinary unscoped and unknown tools to normal Hermes policy;
- bind opt-in scopes to Hermes-provided profile, session, and task identity;
- block changed, replayed, ambiguous, or malformed calls inside an active scope;
- close expired or cancelled scopes without globally protecting the session;
- catch internal callback failures and return an explicit block because Hermes skips uncaught plugin callback exceptions;
- rely on Hermes's bounded plugin-hook timeout, which fails closed for `pre_tool_call`;
- retain no raw provider arguments or confirmation text in receipts;
- leave other sessions, tasks, cron jobs, and ad hoc calls unaffected;
- preserve provider readback and normal action-approval requirements.

## Implementation

- `__init__.py` registers both the `pa` tool and the native `pre_tool_call` callback.
- `plugin.yaml` declares `provides_hooks: [pre_tool_call]`.
- `personal_assistant/action_gateway.py` performs classification, canonical hashing, exact matching, one-shot atomic claims, and redacted receipts.
- `config/pa-action-gateway-policy.example.json` is the reviewed policy shipped with this candidate. Unlisted tools pass through; only listed denied tools are always blocked.
- PA exposes `authorization_prepare`, `authorization_confirm`, `authorization_cancel`, and `authorization_status`; the handler injects server runtime identity.
- Tests prove native registration, ordinary pass-through, exact allow-once behavior, replay denial, argument mutation, expiry/cancellation, session/task isolation, concurrency, redaction, and the older shell-wire adapter.

## Important authority limitation

The one-shot gateway proves that the dispatched call matched recorded authorization. The current `authorization_confirm` operation does **not** cryptographically prove that a human originated the confirmation, because workflow code invokes the PA tool.

Before release or activation, the reviewer must decide whether that is sufficient for the intended risk level or whether confirmation should be replaced or supplemented by Hermes's native `{"action": "approve"}` human-approval directive. This semantic decision is not proven by unit tests.

## Review and release path

1. Review the native hook registration, shipped pass-through policy, failure handling, and authority limitation.
2. Complete exact-head CI and repository review.
3. Merge through normal governance only if approved.
4. Publish/install through the existing PA plugin release process; no separate hook configuration is required.
5. Enable the plugin in an isolated profile and verify that Hermes reports the plugin and declared hook.
6. Run the synthetic proof below.
7. Separately authorize any live provider proof.

Merging this PR does not install, release, enable, or activate the gateway.

## Synthetic proof

With no provider connected, use a fixture tool name and synthetic arguments:

1. Invoke an unknown or Calendar fixture tool without a scope. Expect normal pass-through.
2. Prepare and confirm one exact synthetic authorization through `pa`; verify profile/session/task were server-injected.
3. Change one argument in the matching scope. Expect `DENY_ACTION_MISSING` and zero downstream calls.
4. Invoke the exact fixture call. Expect one allow and one `ALLOW_CLAIMED` receipt.
5. Replay it. Expect `DENY_ALREADY_CLAIMED`.
6. Invoke the same tool from another session/task. Expect normal pass-through.
7. Expire or cancel the scope. Expect the ordinary call to pass again.
8. Verify receipts contain hashes and reason codes but no raw arguments or confirmation text.

## Readback

Record:

- exact plugin source commit and package digest;
- installed plugin version and path;
- `plugin.yaml` declaration for `pre_tool_call`;
- Hermes plugin validation/list output showing the hook registration;
- plugin hook timeout setting;
- synthetic denial, allow-once, replay-denial, and internal-error receipts;
- downstream fixture dispatch count of zero for every denied call.

`hermes config get hooks` is no longer the activation readback because this design does not use config-driven shell hooks.

## Rollback

At an agreed idle point:

1. disable or restore the prior PA plugin version through the normal plugin lifecycle;
2. restart/reload only if that lifecycle requires it;
3. verify that the prior plugin identity is active and the candidate hook is absent;
4. preserve the PA ledger and redacted receipts unless retention policy requires otherwise;
5. never retry an uncertain provider write merely because activation or rollback failed.
