---
name: travel-action-pack-manifest
description: Use when inspecting, validating, installing, or explaining the Travel Agent Skills bundle manifest, version, included skills, rollout status, or v0.1 customer-pilot package contents.
metadata:
  openclaw:
    skillKey: travel-action-pack-manifest
  hermes:
    category: travel
    tags: ["travel", "manifest", "bundle", "install", "version"]
---

# Travel Agent Skills Manifest

This directory carries the v0.1 customer-pilot bundle manifests for OpenClaw and Codex/Hermes-compatible skill installers.

Optional Chief of Staff skills: `cos-daily`, `cos-kickoff`, `cos-weekly`,
`cos-scout`, and `cos-radar`. Their `pa_mode: chief_of_staff` metadata gates native registration;
use them only when Chief of Staff mode is on (`/pa mode chief-of-staff on`).
They are not baseline required skills. Mode enablement starts no jobs; scheduled
reports and HB2 `at` follow-ups require the owner's approval.

Use the package only for enrolled pilot customers until the canary matrix passes:

- trip ledger pass
- provider-message/refund action proof
- Browserbase timeout/reattach proof
- payment readiness proof
- food final-page proof
- hotel/flight final-page proof

Do not represent this pilot release as broad-customer ready until those proofs exist.

Legacy aliases for migration/probing only:

- `openclaw-hermes-travel-action-pack`
- `personal-assistant-travel`
- `addon:travel-action-pack`
