Personal Assistant Plugin now has a versioned native Hermes installation and approved-update path. This private pilot prerelease also packages the September PA improvements previously delivered through source and operator-built archives.

### Highlights

- One PA entry point with qualified skills for trips, calendar preparation, follow-ups, household administration and executive assistance.
- Focused context retrieval, clearer preparation/confirmation paths, and calendar briefs that retain event times and accepted calendar scopes.
- Read-only release checks, explicit pinned updates, and package rollback that preserves current profile data.

### Changes and fixes

- Includes September functionality from PRs #25, #27 and #28: out-of-box PA workflows, durable action/projection records and deterministic freshness checks.
- PR #33 adds native dependency declarations and installation handoff, profile-aware probes, canonical archive replacement and retained-package rollback.
- Release PRs now select the version and notes; hosted Actions builds deterministic archives and verifies immutable publication/download identity. Ordinary feature merges do not publish.
- Main keeps required CI and resolved conversations. A non-author GitHub approval is not mandatory; independent semantic review evidence remains recorded for the changed installation/release paths.

### Installation and approved updates

Select the intended profile and resolve the immutable tag to its full commit. Compare that commit with `source_sha` in the attached external manifest before installation:

```bash
export HERMES_HOME="/absolute/path/to/intended/hermes-profile"
PA_RELEASE_SHA="$(gh api repos/electricsheephq/skill-personal-assistant/git/ref/tags/v0.4.0-rc.1 --jq .object.sha)"
printf '%s\n' "$PA_RELEASE_SHA"
hermes plugins install electricsheephq/skill-personal-assistant --ref "$PA_RELEASE_SHA" --no-enable
```

Use the intended Hermes Python environment to install the declared requirements; Hermes displays dependencies but does not install them. Follow `after-install.md`, then explicitly enable/reload at an authorized idle point.

For an existing native Git installation, after approving the exact revision:

```bash
python3 "$HERMES_HOME/plugins/personal-assistant/scripts/reinstall_pinned.py" --source electricsheephq/skill-personal-assistant --ref "$PA_RELEASE_SHA" --hermes-home "$HERMES_HOME"
```

The command preserves supported local configuration and retains a package-only rollback snapshot. It does not restart Hermes or rewind the ledger, sessions, memory, jobs or completed actions. Read-only update checks use `--channel pilot` to select prereleases; checking creates no job and activates nothing. Native `plugins update` does not advance pinned or archive installs.

Offline/operator users should download all three attached assets and follow [archive verification, replacement and rollback](https://github.com/electricsheephq/skill-personal-assistant/blob/v0.4.0-rc.1/docs/release-process.md). Extracting an archive does not create native Git update metadata.

### Known boundaries

This is a private pilot prerelease, not a stable-channel or fleet-approved update. No operator or customer runtime update is included. Managed self-service remains gated by the operator's support tooling; commercial-provider qualification remains PA #3 and #8. Legacy-only migration and diagnostics for manually altered/corrupt installations remain [#34](https://github.com/electricsheephq/skill-personal-assistant/issues/34); do not use the replacement helper as a legacy migration.

### Release verification

The attached manifest records the exact release merge SHA, archive SHA-256 and both tested Hermes identities: `49c6d4a9e0dddc64d6333c5b1fcc9d911463a8fd` and `6e2b8e070d28b1a3381a3fb290b6b8d6cce13cef`. Portable checksums accompany the archive. [Implementation acceptance](https://github.com/electricsheephq/skill-personal-assistant/actions/runs/34853786163) covers native install/export, repeat update, archive replacement and rollback preserving newly accepted state; [historical baseline](https://github.com/electricsheephq/skill-personal-assistant/actions/runs/34854454777) preserves core native behavior on the same pins. The release workflow verifies downloaded bytes before and after publication. Publication evidence and follow-through belong to [delivery #30](https://github.com/electricsheephq/skill-personal-assistant/issues/30).
