# Evidence cards and live evaluations

## Compact response contract

Telegram/default chat is **compact FIRST**: about 10 lines of recommendation text
for one pick plus two alternatives, fewer when unsupported, followed by
credited/dated photo group captions. Start with local date/timezone, meal,
assumed arrival and party size. Put “Recent reviews unchecked” up front if the
bounded fallback did not establish recent independent visits. For each option,
include native name/branch, fit/order advice, price per person or unknown, and
relevant dinner schedule/last order or entry (or unknown), with source links on
factual lines. Include critical caveats and no seats guarantee. Do not expose
private hotel or preference records as citations.

Target 2 suitable photos per finalist within the 3-candidate cap (about 9 total);
a third only if already justified under the cap, not a quota. Group captions
include visible content, credit, date basis, original image and source page.
Full evidence cards are on request or in a separate attachment; do not dump all
cards after compact text unsolicited.

## Full evidence card (not default chat)

Retain these details for a requested expansion, separate attachment or handoff:

```text
Pick / alternative — native name + branch [source]
Why: factual fit [source]; my judgment: why I'd choose it.
Where: branch address [safe destination-only link]; distance/travel time only if
       actually routed privately, otherwise unknown; never share an origin URL.
Order: dish(s) actually on the menu [source].
Price: currency, amount, per-person/set/portion basis and source date [source];
       estimated per-person order math if needed; tax/service/cash rules or unknown.
For YYYY-MM-DD (weekday, timezone): scheduled hours, break, last order/entry
       [source, accessed time]; special notices checked, or coverage gap.
Practical: time limit, booking-required and booking URL/app/phone needs [source],
       or unknown. Scheduled hours do not imply seats available.
Photos (target 2): linked actual image + original page, credit, capture date OR
       publication proxy with capture date unknown; historical/undated as needed.
       Inspect candidate pixels when viewing is available. Caption only visible
       content; prefer the recommended dish, menu/prices, then useful venue views.
       If only venue photos are suitable, state the missing dish/menu coverage.
       Say not visually inspected only with a real viewing-capability/failure gap.
Recent visits: dates, repeated themes and independent sample size [sources],
       or “Recent reviews unchecked”; don't turn one visit into a trend.
Unknown/conflicting evidence: name the gap next to the field it affects.
```

Use an inline source link on every factual line, not a citation dump at the end.
The source must support that exact branch, award category, date, price basis and
photo. When claims rely on a search snippet rather than the opened page, say so.
A reviewer's rating is a dated opinion, not proof that food is good or safe.
Use linked images/previews only where the delivery surface can show them; plain
links with dated provenance are the fallback. Do not rehost copyrighted photos
or imply a photo was inspected when only its URL was retrieved.

## Photo freshness and pixel evidence

Target within 12 months before the local meal date, or the user's stricter
window. Known capture date establishes capture recency; publication date with
capture unknown is only a publication proxy, not verified recent capture.
Prefer qualifying candidates before historical ones within the same cap and
deadline. Never derive capture dates from filenames, upload dates or retrieval.
If none meets the window on a documented capture/publication-proxy basis, say
exactly “No verified recent photo found”. Optional useful historical/undated
images remain labelled; a current article update cannot refresh an older photo.

Inspect only the final pick and at most two supported alternatives, after the
hours/identity gates and ranking. Adjacency, alt text and filenames are leads
only, not image-content evidence. Never infer species or exact dish names from
neighbouring article text or image position; captions must come from pixels.
Pre-filter using these leads; skip logos/maps/staircases/storefront-only
shots unless the venue itself is the point. Limit viewing to 3 candidates per
finalist (about 9 total); stop at 2 good photos. Use one batched, existing-lane
cheap/fast image helper where available, returning short captions + keep/reject
only, not image bytes to the main session; otherwise use the same cap inline.
If nothing passes, say “no verified dish photo”; never send an unchecked image
or open a whole gallery to fill the quota. Record any actual lane/model limit
without changing runtime/config or silently switching paid/provider routes.

## Meal-window conflict gates

List closed or dinner-ineligible exclusions separately with their evidence.
Gate conflicts on requested arrival and the entire meal interval, relevant last
order/entry, closures, address and essential dietary suitability. A lunch-opening
discrepancy is immaterial if all credible sources support the entire dinner
window: disclose it, do not silently pick a source or exclude for lunch alone.
A dinner-overlapping conflict quarantines the candidate under unverified leads,
not tonight's picks. Check scheduled hours against the actual requested arrival and
meal duration, breaks, last order/entry, holiday/temporary notices and timezone;
00:00–02:00 may belong to the prior service day. No blanket “open now” from a
weekday schedule. If same-day confirmation is unavailable, explicitly say
“scheduled open; temporary closure/availability not independently confirmed”.
Do not guarantee entry when last order is unknown.

## Deadline and guide-scope accounting

Before research bind a declared end-to-end deadline and elapsed-time budget;
default a requested quick dinner to 15 minutes unless the user sets another
limit. Reserve time for hours/identity, finalist photos and final delivery.
Record the official dated guide's scope URL, edition/year and caveat. If the
city is excluded, skip the out-of-scope national category sweep; this is not a
local exhaustion claim. For an in-scope category/location request, retain complete
paginated entry-area accounting before radius expansion: declared total, unique
entries checked, area evidence and every local match's pick/exclusion/unverified
disposition. A timebox or inaccessible pages means an explicit coverage gap,
not a completed sweep or local exhaustion. Label any expansion.

## Private routes and shared links

Use the authorized stay privately only; never put it in public/broad queries or
shared artifacts. Shared links are destination-only Maps/search/place links.
Strip origin-bearing route URLs and redact private screenshot data. Cite the
safe destination separately; private route evidence proves travel time only if
actually routed. Otherwise distance/travel time is unknown.

## Recent-review fallback

After at most two failures with the same cause, try one materially different
public no-login fallback within the deadline: exact-branch dated visit records
on another local platform or opened original independent visit posts (iFoodie →
original blog in Taiwan, Tabelog in Japan, public Naver/Kakao in Korea). Verify
visit date, not article update date; sponsored, press and venue posts are not
independent visits. Use the last 6 months and state dates and independent sample
size. One visit is not a trend. If still unavailable, put “Recent reviews
unchecked” up front in compact output; no “no complaints” from an empty sample.

## Repeatable live-eval protocol (PA #71)

Static wording/packaging checks are guardrails, not behavioural proof of
restaurant discovery. Run these
read-only against the real web using the candidate skill, recording synthetic
prompts and no private owner/stay information:

1. **Luodong Tuesday dinner:** “I love lamb.” Resolve an actual Tuesday and local
   dinner time. Find a lamb-focused option, exclude Tuesday-closed places, and
   show dated photos plus a sourced menu/price line.
2. **Osaka Namba:** request Bib Gourmand. Use Michelin's own current venue pages
   and direct Guide links; check every category-list entry's address/area across
   pagination before widening. Save declared total, unique entries checked and
   each in-area match's pick/exclusion/unverified disposition (including hours
   conflicts). Expose any inaccessible-entry coverage gap; do not claim local
   exhaustion without the sweep. Do not promote Selected, old awards or far-away
   Osaka venues as current Namba Bib Gourmand. State any radius expansion.
3. **Seoul or Songdo:** use Naver/Kakao or Blue Ribbon public evidence and native
   Korean queries, not an English-only roundup.

For the preference-fit case, read active preferences from the authorized PA
binding rather than merely copying the prompt into a fabricated profile. Record
which relevant rules were in force and how they changed ranking/presentation,
without publishing raw owner records or private context. A synthetic preference
fixture tests integration only; it does not prove a live profile read. If a
runtime/version gap forces a specifically authorized read-only backend path,
label that path and its scope rather than calling it the native `pa` tool.

For blocked retrieval, stop after two failures with the same cause; try one
materially different public fallback within the deadline or retain an explicit gap. Save and reuse
already retrieved evidence after interruption instead of repeating a search loop.
No fresh timestamp, repeated query or fallback refreshes the underlying source's
menu/photo date.

For each run save: timestamp/timezone, skill revision, exact prompt and declared
assumptions, declared deadline and budget allocation, guide scope URL/year/caveat,
ordered queries, tool names, returned URLs and short relevant
verbatim excerpts, blocked/failed attempts and fallbacks, final user-facing
output, and a criterion-by-criterion self-grade. Retain source publication and
visit/photo dates separately from retrieval time. When viewing is available,
record the images actually viewed, visible-content captions, selected/rejected
IDs and reasons; an HTTP probe is not this proof. Keep source-page publication
and unknown capture dates visible even after inspecting pixels. Save complete public tool
results locally when useful; publish only bounded non-sensitive evidence, not
private context, customer data, authenticated provider responses or ledgers.

Grade PASS / PARTIAL / FAIL for: curated/local-language source use; exact branch
and owner fit; recent review/complaint evidence; sourced menu and price basis;
actual-day meal-window hours and exclusions; target 2 suitable photos per option
with the 12-month date basis/gaps; compact-first one pick plus two
alternatives; every factual line sourced; reservation handoff with no actions.
Count unknowns and gaps honestly. A link with no date is not a dated photo; a
labelled price tier is truthful but does not satisfy a numeric price criterion.
If dated photos, recent reviews or current menu cannot be established, mark
that criterion PARTIAL/FAIL rather than filling it from model knowledge.

A separate non-author reviewer reads all three transcripts and outputs as well
as the diff, checks load-bearing sources, and records ACCEPT/REJECT/DEFER against
the exact PR head. Author self-grades, CI and reviewer verdict are distinct.
Any later change invalidates the old exact-head acceptance until re-reviewed.
