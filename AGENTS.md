# Personal Assistant repository guidance

- Preserve the native Hermes plugin ID `personal-assistant`, the legacy archive
  name `travel-agent-skills`, and the profile ledger path
  `state/travel-ledger/travel.sqlite`.
- Do not commit credentials, live profile configuration, raw customer data,
  provider receipts, or generated ledgers. Use synthetic fixtures only.
- Installation must not enable the plugin, register jobs, restart Hermes,
  download executables, or perform provider actions automatically.
- Keep `VERSION`, `plugin.yaml`, legacy manifests, and
  `releases/<version>/manifest.json` aligned.
- Every pull request links an issue and declares exactly one
  `Release impact: none|publish` line. Ordinary implementation PRs use `none`
  and must not change `VERSION`.
- A release PR uses `publish`, changes `VERSION`, `CHANGELOG.md`, and the matching
  release manifest, and supplies substantive release notes. Publication occurs
  only from the trusted merged-PR workflow.
- Run focused local checks only. The full package, archive, release-contract,
  and two-pin native lifecycle matrices run on GitHub-hosted CI.
- Source/CI proof does not prove merge, publication, runtime activation, fleet
  approval, provider completion, or customer readiness.
