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

The approved Support Control version remains `0.1.0`. The operator's support tooling must provide the
approved writable profile-local extension path before any fleet installation;
source or release metadata does not change that restriction.
