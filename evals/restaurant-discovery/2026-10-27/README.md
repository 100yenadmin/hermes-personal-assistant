# Restaurant discovery — live author evals, 2026-10-27

Related: [PA #71](https://github.com/100yenadmin/hermes-personal-assistant/issues/71)
and draft [PR #72](https://github.com/100yenadmin/hermes-personal-assistant/pull/72).

## Outputs and current self-grades

These are real public-web, read-only **author-executed** evaluations, not mocked
search/provider responses, fresh independent-agent benchmarks or bookings.
Each output retains its initial decisive transcript and recovery boundary,
then records the round-2 corrections, final response and per-criterion grade.
The exact reviewed revision is the PR head recorded in the Kanban handoff;
older skill SHAs in the run contracts identify the earlier retrieval phases.

| Case | Transcript, output and self-grade | Specific #71 behaviour | Remaining quality gaps |
| --- | --- | --- | --- |
| Luodong Tuesday, “I love lamb” | [luodong-tuesday-lamb.md](luodong-tuesday-lamb.md) | Lamb-led shortlist, actual-day scheduled hours and Tuesday exclusion, dated menu/price and viewed food/menu photos | PARTIAL: historical prices/photos, insufficient recent-review sample; scoped backend preference read is not native `pa profile` proof |
| Osaka Namba, Bib Gourmand | [osaka-namba-bib.md](osaka-namba-bib.md) | Own-site Michelin links; all 59 official category entries checked for address/area; Minato surfaced as in-area hours conflict before retaining wider cards | PARTIAL: no verified core dinner pick; explicit Shinsaibashi/Shimmachi/Tanimachi expansion, dated menu/photo and review gaps |
| Seoul via local platforms | [seoul-local-platforms.md](seoul-local-platforms.md) | Korean queries, Blue Ribbon/Naver evidence and viewed grill/soup/menu photos | PARTIAL: only one supported alternative, third venue quarantined for hours conflict; price/recency gaps |

The locale-specific behaviours are demonstrated; the broader quality grades
remain **PARTIAL**, not a claim that every proposal goal is fully satisfied.
Author self-grades, passing static checks and independent acceptance are distinct.

## Round-1 review and corrections

Eva's separate non-author review requested changes at
`a82298c15aaf8199f82190aaa59c8cf67f6aac9f`: account for the missed Minato and inspect
actual photos, replacing the foreground pork/beef freezer and Morimoto staircase.

- The skill now requires every category-list entry's address/area across
  pagination **before widening**, with each in-area match retained as a pick,
  exclusion or unverified lead. It must disclose an incomplete sweep.
- [osaka-area-audit.md](osaka-area-audit.md) / [JSON](osaka-area-audit.json)
  enumerate all **59 unique entries** from the **48 + 11** official-list pages.
  Each has an opened Michelin address excerpt and explicit disposition. The
  scope is a declared locality judgment, not an invented numeric radius; all
  twelve conservatively flagged fringes remain visible. Minato is **not a
  dinner pick**: Michelin/mobile Tabelog lunch-only conflicts with desktop
  Tabelog dinner hours. The raw source spelling of addresses is retained.
- Source clocks in that audit mark collection start, not per-request access
  times. Direct list GETs returned empty 202; public `web_extract` supplied the
  actual list/venue evidence. Failed locale/slugs and remaining gaps are retained.

## Operator-bounded photo procedure and actual proof

The skill now explicitly requires: **finalists only**, pre-filter from source
article position/dish/menu text, alt text and filenames; **at most 3 candidates
per finalist / about 9 per response**; stop at **2 good photos**. Skip logos,
maps, staircases and storefront-only images unless the venue is the point.
Use **one batched** cheap/fast image helper where the existing authorized lane
supports it, returning only short visible-content captions and keep/reject.
No images to the main session; same cap inline if delegation is unavailable.
Nothing passes → **“no verified dish photo”**, not an unchecked illustration.

[photo-inspection.json](photo-inspection.json) records the actual final pass:
**one helper call, 16 candidates for eight supported finalists**: 6 Taiwan,
6 Japan, 4 Korea. Each finalist had two pre-filtered candidates, both kept;
no additional gallery was opened and no unverified lead was included in that
pass. Only captions/decisions returned to the main session. The current
`delegate_task` schema has no per-call model selector, so the existing authorized
image-input model was used; a cheaper/faster route is **not proven** and no
runtime/provider/config change or silent paid fallback was made.

An earlier **120-panel broad author sweep preceded that operator steering and
exceeded the later cap**. It informed the final pre-filter. The bounded pass is
therefore a recheck, not a fresh blind experiment or evidence that the whole
session respected the later cap. That history is disclosed, not erased.

[photos.json](photos.json) now holds **16 selected original image links**, two
per supported finalist, with literal visible-content captions, source/publication
date, credit, selected ID and image SHA-256. Capture dates remain unknown.
Fourteen links matched source image tags beside article text; two Polle links
come from the recovered post photo array, not a claimed current static image-tag
match. Images were viewed as labelled contact-sheet previews, not separately
enlarged originals. No image bytes are committed or rehosted.

Morimoto's pair shows whole-serving/detail views of the same fried-rice serving;
it is not two independent dishes or a photograph of the chicken/noodle order.
Oribe's seasonal plated dishes are not promised to be the exact price-example
order. The Korean table-order screen is not today's bowl quote. Photos of the
unverified Tian Mimi lead are omitted from the final response rather than
spending finalist inspection budget on it. Historical imagery stays labelled.

## Preserved earlier evidence and privacy boundaries

- [sources.json](sources.json): shared retrieval URL → citation ledger. Each
  Sources block is mechanically rendered. Per-case unused-ID warnings are
  expected; citation-map integrity is not semantic truth/freshness proof.
- [photo-probes.json](photo-probes.json) and
  [photo-curl-fallback.json](photo-curl-fallback.json): **earlier 18-link** HTTP
  probes, not the current 16-photo selection or visual proof. Two old Ayamedo
  Python TLS failures succeeded via system-TLS curl; TLS was not disabled.
- [hours-evidence.json](hours-evidence.json): exact-branch Google Maps published
  weekly schedules, not live seats or unpublished temporary-closure absence.
- [public-fetches.json](public-fetches.json): bounded original public HTTP
  metadata/failures. Full HTML, credentials, cookies and host paths are omitted.
- [preference-read-attestation.json](preference-read-attestation.json): derivative
  attestation of the operator-authorized two-food-record read. The Luodong
  follow-up omits lamb and uses the actual in-force preference. The existing
  `Ledger.get(read_only=True)` fallback is explicitly **not native `pa` proof**;
  no raw owner record, private path or unrelated context is published.

No booking, queue entry, call, message, signup, login, preference write, runtime
activation/configuration change, merge or release occurred. No owner stay or
private profile export is included. Japan/Korea remain separate synthetic cases.

## Verification and acceptance boundary

- Focused discovery/artifact, exact inventory-parity and installed-version probe
  checks: **37 passed** after the round-2 changes. These are integrity/policy
  guards, not restaurant-quality proof. New policy and evidence tests were
  demonstrated red before their corresponding fixes. On an isolated checkout
  of round-1 head `a82298c`, the current discovery test file produced **5 failed,
  6 passed**; the same file passes on the new candidate.
- Citation maps are verified for the three outputs and complete area-audit
  document; the human/non-author still checks load-bearing source meaning.
- Full package/archive/release-contract/two-pin native lifecycle matrices run
  only on hosted CI. Fresh exact-head CI is required for this changed head.
- Keep the PR **draft** until a separate non-author run reads all three outputs,
  the audit and photo evidence as well as the diff, and records
  ACCEPT / REJECT / DEFER on that exact head. Any later head invalidates approval.

Next: native bound-profile live test in the supporting owner runtime; fresh
branch-owned menus/reviews; resolve Minato's and Tian Mimi's hours; owner-approved
Namba radius; verify a cheap/fast image-helper lane without changing the bound
runtime. Do not use a booking/call/login to turn a PARTIAL grade green.
