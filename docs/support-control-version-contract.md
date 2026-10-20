# Support-Control Version Contract

Travel Agent Skills is tracked as an optional enrolled add-on, not as a required fleet baseline skill.

## Component Identity

- Component id: `addon:travel-agent-skills`
- Package name: `travel-agent-skills`
- Current channel: `pilot`
- Current version: `0.1.0`
- Owner repo: `100yenadmin/hermes-personal-assistant`
- Native install path: `~/.hermes/plugins/personal-assistant`
- Legacy archive path: `/root/.openclaw/workspace/packages/travel-agent-skills`
- Legacy aliases: `openclaw-hermes-travel-action-pack`, `personal-assistant-travel`, `addon:travel-action-pack`

## Tracking Rules

- Only enrolled targets get a `fleet_component_state` row for this add-on.
- Unenrolled customers must not be marked behind or missing.
- `current` means the installed version and package identity match the approved release metadata.
- `behind` means an enrolled target has an older observed version.
- `unknown` means an enrolled target is missing an observation or the probe could not confirm the package.

## Probe Contract

Run:

```bash
python3 scripts/probe_installed_version.py --json
```

The probe checks the profile-native path first and emits sanitized JSON with the
component id, observed version, package path, manifest path, Git or archive source
kind, exact pinned revision when available, declared dependency status, required
skill presence, and legacy alias status. Installed, enabled, loaded, and exercised
are separate fields; the read-only disk probe reports loaded/exercised as unknown
without runtime evidence.

For `native_git`, `observed_commit` retains the install metadata revision.
`checkout_commit` and `checkout_dirty` report the actual Git HEAD and porcelain
status. PA's own untracked local files (`clients.json`, `daily_ops.config.json`,
`daily_ops.state.json`, `location.json`) do not make the checkout dirty; any
other untracked or modified file does. `metadata_matches_checkout` compares HEAD
with that revision. These
fields are null when unavailable or inapplicable. A mismatch or dirty tree sets
`install_ok` and `source_identity_known` false, with `source_identity_reason`
of `source_mismatch` or `local_edits`. Unavailable Git sets
`source_identity_known` false with reason `checkout_unavailable`; it does not
itself invalidate the package's files. The release checker cannot report any
of these states as current. Git runs without inherited `GIT_*` variables and with optional index writes disabled.

A present, non-list `python_dependencies` returns only `ok: false`,
`installed`, `install_ok: false`, and `invalid_reason` naming the field and its
type; dependency values and other manifest contents are omitted.

`migration_required` is true for a legacy-only OpenClaw package. The release
checker reports `migration_required` and, when a release is available, proposes
the profile-scoped native `hermes plugins install ... --ref ... --no-enable`
command. It supplies no archive target for that state. Archive replacement
proposals require an existing native archive/copy target. All commands remain
operator proposals; diagnostics perform no installation or migration.

The approved Support Control version remains `0.1.0`. The operator's support tooling must provide the
approved writable profile-local extension path before any fleet installation;
source or release metadata does not change that restriction.
