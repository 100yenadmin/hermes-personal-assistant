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

## Release closeout (required after every release, rc promoted to stable, or GA tag)
After the release is published and its receipt sent:
1. Close every issue the release fully served, with a comment naming the version (never an umbrella/parent issue whose own acceptance is not met). "Fully served" means the issue's own done-when is met by what shipped. An issue whose done-when needs a live run or an owner step stays open until that has happened, as ROADMAP.md's exit tests say, unless those live checks are moved, with a comment naming the release that shipped the build, to the milestone's live-exit tracker listed in ROADMAP.md.
2. Tick the boxes it completed on ROADMAP.md / VISION.md, roadmap or tracking issues, and closed issues whose checklists shipped; close a milestone once all its issues are closed.
3. Update every README / ROADMAP line that names the latest release or what ships next.
4. Post one closeout line as a comment on the release pull request: issues closed, boxes ticked, docs updated (or "none").
