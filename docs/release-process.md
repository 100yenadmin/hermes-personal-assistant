# Personal Assistant Plugin release process

The native Hermes plugin ID is `personal-assistant`. The GitHub repository and
legacy archive name remain `skill-personal-assistant` and
`travel-agent-skills` respectively. The travel ledger remains profile data at
`state/travel-ledger/travel.sqlite`; it is never packaged into a release.

This repository has two delivery paths. An ordinary implementation pull request
may change source, tests, documentation, and release tooling, but its merge must
not publish a tag or asset. A release pull request deliberately changes
`VERSION`, adds matching release notes, and declares `Release impact: publish`.
Only the merge of that reviewed release pull request to `main` may publish.

Releases from `0.10.0` (including prereleases) require `scorecard.json` and `scorecard.md` in `releases/<version>/`, with schema 1, the matching version and reviewed implementation commit, 14 areas, and the `# PA <version> VA scorecard` Markdown heading.
HTML comments are removed from extracted release notes before publication, and the remaining notes must be substantive.

## Candidate validation

Every pull request runs the required `validate` check. It aggregates package
validation, the affected test suite, deterministic archive checks, PR metadata,
the release-contract dry run, and the native lifecycle matrix on both supported
Hermes commits. A skipped, cancelled, or failed mandatory job fails the aggregate.

The current supported Hermes pins are:

- `49c6d4a9e0dddc64d6333c5b1fcc9d911463a8fd`
- `6e2b8e070d28b1a3381a3fb290b6b8d6cce13cef`

The native matrix uses disposable synthetic profiles. It installs the plugin
from Git with a full 40-character commit SHA, explicitly enables it, verifies
`pa` and qualified skill discovery, imports one timed and one all-day event,
exports them, and checks ledger replay. It then performs an explicit pinned
reinstall and proves that allowlisted local PA configuration and the profile
ledger survive. Disable/re-enable and missing dependency/access cases must remain
truthful. These checks do not use real profiles or provider credentials.

## Native install and approved revision changes

Hermes treats a Git checkout and a downloaded release archive differently.
Native Git installation records the source and exact revision in the profile's
install metadata. An extracted archive has release metadata and checksums, but
it is not an updateable Git installation.

Install an approved Git revision explicitly and leave it disabled for review:

```bash
hermes plugins install 100yenadmin/hermes-personal-assistant \
  --ref <40-character-approved-commit> --no-enable
```

After reviewing the install output and `after-install.md`, install the declared
Python dependencies into the intended Hermes environment yourself. Hermes only
surfaces `python_dependencies`; it does not install them. Enable and reload at an
authorized idle point:

```bash
hermes plugins enable personal-assistant
```

Pinned installations never move automatically. `hermes plugins update` refuses
them. After a newer revision is approved, use the repository's preservation
wrapper from the currently installed plugin. It backs up only the documented PA
configuration files in memory, retains the prior package and its activation
membership in the profile's `plugin-backups/personal-assistant/` directory,
runs a full-SHA force reinstall, restores current configuration, and does not
enable the plugin or restart Hermes:

```bash
python3 ~/.hermes/plugins/personal-assistant/scripts/reinstall_pinned.py \
  --source 100yenadmin/hermes-personal-assistant \
  --ref <40-character-approved-commit> \
  --hermes-home ~/.hermes
```

The result names the retained rollback snapshot. If acceptance fails, roll the
package back explicitly:

```bash
python3 ~/.hermes/plugins/personal-assistant/scripts/reinstall_pinned.py \
  --rollback <snapshot-id> --hermes-home ~/.hermes
```

Rollback restores the prior package and native install metadata while retaining
the current local PA configuration and activation membership. Ledger, session,
memory, job, and provider state live outside the plugin package and are never
copied or rewound. The rollback itself retains a recovery snapshot of the
replaced package.

An archive operator downloads the `.tgz`, `.sha256`, and external
`.manifest.json` into one staging directory. After reviewing the version and
source SHA, the same helper verifies all three assets, retains the prior package,
and replaces the canonical discovery path `plugins/personal-assistant`:

```bash
python3 ~/.hermes/plugins/personal-assistant/scripts/reinstall_pinned.py \
  --archive-dir /absolute/path/to/verified-release-assets \
  --version <approved-version> --hermes-home ~/.hermes
```

The helper removes stale Git install metadata so the read-only probe identifies
the canonical tree as `native_archive` from its internal release identity. Git
and archive replacement both preserve current configuration and activation and
require the same explicit post-replacement inspect/reload decision.

## Read-only release check

`scripts/check_release.py` uses the already-authenticated `gh` CLI. It never
downloads or executes release assets and never substitutes credentials. Stable
releases are checked by default; the `--channel pilot` flag is required to see a
prerelease. The result distinguishes:

- installed native Git revision or archive metadata;
- selected release version, source SHA, and asset digest;
- release notes since the installed version;
- the exact profile-bound native pinned reinstall command, or the verified
  archive replacement command and canonical operator archive path.

Missing GitHub access, missing dependencies, absent install metadata, and an
unreleased installed commit are reported as such. They are never converted into
an update-ready result.

## Packaging and publication

Build from the exact clean candidate commit. `VERSION`, `plugin.yaml`, native
and legacy manifests, release notes, and the selected `releases/<version>` entry
must agree. The packager rejects dirty input and missing required files, writes a
sorted archive with commit-derived normalized timestamps and ownership, emits a
portable basename-only checksum file, and writes an external manifest containing
the source SHA, native ID, artifact digest, and tested Hermes pins. The external
manifest is outside the archive so it does not create a self-hash cycle.

```bash
bash scripts/package_release.sh --output-dir dist
```

On an exact `main` merge of a valid release pull request, the publication job
builds without write credentials, re-runs archive and download verification, and
then grants only `contents: write` to the final publication step. It creates the
immutable `v<VERSION>` tag and GitHub prerelease. A retry may resume a partial
draft only when the existing tag target, approved title, approved release-note
body, prerelease setting, and every existing asset byte-for-byte match. It
refuses unknown or edited draft metadata and never clobbers a mismatched tag or
asset.

The `v0.4.0-rc.1` initial publication left an approved empty draft while its
original build remained attached to Actions run `34879649204`. After the
recovery change is reviewed and merged, an owner may run
`gh workflow run release-recovery.yml --ref main`. This dispatch downloads that
exact artifact, verifies its run, source commit, version, file set and pinned
digests twice, then uses the corrected publisher from reviewed `main` to resume
the existing draft. It cannot rebuild, retag, or select another artifact or
version.

The pilot release is `v0.4.1-rc.2`. Release selection is a separate PR after
implementation acceptance. Main requires CI and resolved conversations, but no
mandatory non-author GitHub approval. Independent semantic review evidence for
changed installation/release paths is retained. Support Control stays at
approved version `0.1.0`; publication never authorizes fleet installation.

## Proof boundary

Passing source, archive, and native synthetic CI can establish a reviewable
release candidate and the integrity of its packaged bytes. It does not establish
merge, tag publication, installed runtime activation, provider qualification,
fleet approval, or customer readiness. Those states need their own exact-head,
runtime, and end-user evidence.
