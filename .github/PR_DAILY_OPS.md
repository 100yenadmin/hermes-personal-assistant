## Outcome

Repairs the PA daily-ops addition into read-only, profile-bound components: morning brief, evening register, priority/leave-by watchdog, optional tenant client connector, doctor and existing PA/R5 integration. This PR ships source, package support, skill and tests—not a fleet deployment.

## Current scope (supersedes earlier PR descriptions)

- No unattended mailbox mutations: cleanup enable requests fail before provider calls. Existing interactive PA recipes unchanged.
- Provider command grammar allowlists read operations, validates data/flags, uses actual GOG `--page` with metadata preserved; exact read scopes and positive per-account check proof required.
- Accepted destination references existing PA rule + notification claim/receipt lifecycle; payload/rule revision/profile/account/target/timezone are bound to delivered proof. The existing ledger trusts caller-supplied provider evidence, not cryptographic attestation.
- Typed bounded packets with exact time windows and explicit incomplete coverage; zero-byte quiet watchdog. Updated-category priority mail included, stable opaque thread/occurrence phase dedup, restart-safe private locked atomic state.
- Trip context comes from existing PA trip ledger; unknown origins stay unknown. Literal-consent geography, public-IP DNS pinning with proxies disabled, cadence constrained, catch-up `now` phase remains eligible through event start.
- Optional tenant-bound Stripe/Supabase connector invalidates incomplete/failed/malformed indexes before reporting failure. No tenant defaults or bypass.
- Packaging uses tracked-source allowlist and text/runtime-data checks; artifact records content identity and dirty/clean provenance. Redaction/scans are not universal PII detection.

## Scheduling and deferred functionality

Existing R5 retains two native routines: morning brief and due-source evening check. No automatic installation or third/fourth routine. Client sync is **on request**, not an automatically registered 09:45 job. Watchdog components are executable but require separately accepted host execution within existing job limits. Config fields alone do not establish scheduling or transport delivery. These limits are documented in the skill and example config.

## Independent review and proof

Independent candidate review plus scoped repair reviews cleared the implemented security/customer-data/evaluation boundaries; last two regressions were reproduced failing-first and independently approved. Author self-review did not substitute for required independent approval.

Parent verification before final commit: **89 tests passed plus 3 subtests** in isolated environment; source and extracted package validation and actual five-entrypoint smoke with synthetic providers. Real local GOG help checked for flags; synthetic tests are not live provider/customer success proof. Final commit CI and artifact must be rechecked before merge. The historical fixture failure was missing git object `103d6ef` in a shallow clone; fetching the real repository object fixed full-suite execution without weakening tests.

## Release boundary

No live Google/Stripe/Supabase/geo calls during repair validation; no installed operator plugin/scripts/crons or customer state changed. Merge is not release, installation, live canary, complete out-of-box fleet scheduling or customer usefulness validation. A separately authorized canary/rollout remains required. All review discussions require evidence-backed terminal dispositions before merge.
