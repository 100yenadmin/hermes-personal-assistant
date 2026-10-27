# Restaurant discovery — live author evals, 2026-10-27

Related: [PA #71](https://github.com/100yenadmin/hermes-personal-assistant/issues/71).

## What was exercised

The repository's `restaurant-discovery` skill was applied by Khan against the
real public web, read-only, using synthetic requests. The three outputs include
condensed decisive tool transcripts, native-language queries, source excerpts,
final user-facing responses and criterion-by-criterion author self-grades:

| Case | Transcript, output and self-grade | Specific #71 live acceptance | Wider quality grade |
| --- | --- | --- | --- |
| Luodong Tuesday dinner, “I love lamb” | [luodong-tuesday-lamb.md](luodong-tuesday-lamb.md) | Lamb-led picks; Tuesday-closed venue excluded; dated image links and numeric dated menu reference | PARTIAL: current prices, recent-review sample and visual inspection incomplete |
| Osaka Namba, Bib Gourmand | [osaka-namba-bib.md](osaka-namba-bib.md) | Own-site Michelin category evidence and direct Guide links | PARTIAL: geography explicitly widened; some historical menu/photos and incomplete reviews |
| Seoul via local platforms | [seoul-local-platforms.md](seoul-local-platforms.md) | Korean queries, Blue Ribbon, Naver Place and Naver Blog, not English-only | PARTIAL: only one supported alternative; third venue quarantined for hours conflict; current-price/review gaps |

This demonstrates the three **locale-specific** live acceptance behaviours. It
does **not** establish that every wider proposal goal is fully satisfied. The
individual factual claims and declared gaps, not this summary table, are the
review target. A non-author may disagree with these self-grades.

## Provenance and interruption boundary

The initial task run was interrupted before publication. Its local skill commits,
authored drafts, citation ledger and real public HTTP/browser records were
recovered in the same task. Key load-bearing sources were opened again in the
recovery run; each output has a **Recovery readback** section. The missing exact
李家莊 Google Maps hours record was freshly retrieved, with browser timestamp.
The two unpublished implementation commits were reauthored to Khan to correct
inherited local Git identity before any push. Each case names the candidate
skill revision. The final review must bind the PR's exact head, not just that
skill-only revision.

These are **author-executed live tool evaluations**, not fresh independent-agent
benchmarks, raw full-session exports or successful provider transactions. Query
rows are grouped by locale, not an invented globally ordered transcript; the
public HTTP index retains its actual recorded access timestamps. Recovery did
not silently rerun all earlier queries or manufacture responses for blocked
pages. Full HTML and isolated browser state stay outside source control.

## Reviewable evidence files

- [sources.json](sources.json): shared citation ID → retrieved URL ledger. Each
  output's Sources block was rendered mechanically from this ledger, restricted
  to its cited IDs. Citation-map verification passes for all three; the helper
  warns about unused IDs because the ledger also covers the other cases. This
  does not validate semantic truth or evidence freshness.
- [photos.json](photos.json): the 18 original image URLs, original page,
  publication date, credit and source ID, grouped by the nine researched venues.
  All captions state **capture date unknown / not visually inspected**; article
  date is not passed off as camera date. Historical/possibly older evidence is
  labelled. No image bytes are rehosted or generated.
- [photo-probes.json](photo-probes.json) and
  [photo-curl-fallback.json](photo-curl-fallback.json): real image GET results.
  Sixteen succeeded in the initial probe; two Ayamedo image requests failed
  Python TLS verification, then succeeded with the system-TLS `curl` fallback.
  TLS verification was not disabled. Serving an image proves neither its content
  nor its date; those remain source-provenance claims with explicit limits.
- [hours-evidence.json](hours-evidence.json): bounded exact-branch Google Maps
  hour readbacks. Original results without embedded times say so; no invented
  access timestamp. These prove a published weekly schedule, not temporary
  closure absence or seat availability.
- [public-fetches.json](public-fetches.json): bounded original HTTP metadata,
  including request URL, timestamp, status/type/hash when present, and failures.
  Host paths, full HTML, credentials, cookies and unrelated page text are omitted.
  Direct 403/429/TLS failures are retained rather than claimed as successful reads.
  A failed direct GET does not contradict a separately identified `web_extract`
  read of public indexed text; those are different retrieval paths.

Only public business/review sources and synthetic prompts are included. No live
owner profile, stay address, customer ledger, authenticated provider response,
booking, queue entry, call, message, sign-up or preference write was used.

## Local and hosted checks

`tests/test_restaurant_discovery_skill.py` covers packaging, both entry routes,
read-only/confirmation boundaries and the saved artifacts' citation/photo
structure. It is **not** a substitute for reading the live outputs. The four
original focused tests failed on unchanged base
`1564e079e221df6c6036dad3818c56180ea888e7` and passed with the skill.
Full package/archive/release-contract/two-pin native lifecycle checks belong to
hosted CI, per repository guidance.

## Independent review and next iteration

Keep the PR draft until a **separate non-author run** reads all three full
outputs and the diff, checks load-bearing sources and records
ACCEPT / REJECT / DEFER against the exact PR head. Author self-grades and green
CI are not that verdict. Any changed head needs renewed acceptance. No merge,
release, runtime installation/activation or fleet/customer acceptance is implied.

Recommended next improvement: obtain fresh branch-owned menus and a dated,
independent recent-review sample; visually inspect/caption the photos; tighten
Namba travel radius from an approved starting point; resolve the Korean third
venue's hours before adding it as an alternative. Do not use a booking/call or
login merely to turn a PARTIAL grade green.
