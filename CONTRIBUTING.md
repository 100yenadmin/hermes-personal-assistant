# Contributing

Start from an assigned issue in this repository and keep each pull request to
one reviewable outcome. Use synthetic data. Never copy live profiles, local
configuration, credentials, provider responses, or travel ledgers into source,
tests, logs, or artifacts.

Complete the pull request template. `Closes`, `Fixes`, `Resolves`, or `Related`
must link at least one issue. Set `Release impact: none` for ordinary source,
test, documentation, and workflow changes. These pull requests must leave
`VERSION` unchanged and cannot publish.

A release pull request is separate. It sets `Release impact: publish`, changes
`VERSION`, adds the matching `releases/<version>/manifest.json`, updates
`CHANGELOG.md`, and includes release notes. The merge must retain the required
`validate` check and applicable independent semantic review evidence. A non-author
GitHub approval is not mandatory for this repository. After the exact merge reaches
`main`, the release workflow builds and verifies immutable assets before its
narrowly scoped publication job receives `contents: write`.

For local development, run only the smallest affected test file. Push the
candidate to use the hosted package, archive, release-contract, and exact-Hermes
native lifecycle checks. Do not use a real operator or customer profile, or
commercial provider as a development fixture.

The release and installation boundaries are documented in
[`docs/release-process.md`](docs/release-process.md). Support Control approval,
managed profile installation, activation, fleet rollout, and customer proof
remain separate gates.
