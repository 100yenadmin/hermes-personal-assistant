# Evidence cards and live evaluations

## Compact response contract

Start with destination-local date/time, requested meal, constraints and any
assumptions. Do not expose private hotel or preference records as citations.
Then one pick and two alternatives, with fewer if evidence cannot support three:

```text
Pick / alternative — native name + branch [source]
Why: factual fit [source]; my judgment: why I'd choose it.
Where: branch address [source]; stay distance/travel time [map route], or unknown.
Order: dish(s) actually on the menu [source].
Price: currency, amount, per-person/set/portion basis and source date [source];
       estimated per-person order math if needed; tax/service/cash rules or unknown.
For YYYY-MM-DD (weekday, timezone): scheduled hours, break, last order/entry
       [source, accessed time]; special notices checked, or coverage gap.
Practical: time limit, booking-required and booking URL/app/phone needs [source],
       or unknown. Scheduled hours do not imply seats available.
Photos (2–3): linked actual image + original page, credit, capture date OR
       publication date with capture date unknown; historical/undated as needed.
       If not visually inspected, say so; never invent the pictured dish.
Recent visits: dates, repeated themes and independent sample size [sources],
       or recent-review check incomplete; don't turn one complaint into a trend.
Unknown/conflicting evidence: name the gap next to the field it affects.
```

Use an inline source link on every factual line, not a citation dump at the end.
The source must support that exact branch, award category, date, price basis and
photo. When claims rely on a search snippet rather than the opened page, say so.
A reviewer's rating is a dated opinion, not proof that food is good or safe.
Use linked images/previews only where the delivery surface can show them; plain
links with dated provenance are the fallback. Do not rehost copyrighted photos
or imply a photo was inspected when only its URL was retrieved.

List closed or dinner-ineligible exclusions separately with their evidence.
Unresolved opening/address/dietary gates belong under unverified leads, not in
tonight's picks. Check scheduled hours against the actual requested arrival and
meal duration, breaks, last order/entry, holiday/temporary notices and timezone;
00:00–02:00 may belong to the prior service day. No blanket “open now” from a
weekday schedule. If same-day confirmation is unavailable, explicitly say
“scheduled open; temporary closure/availability not independently confirmed”.
Do not guarantee entry when last order is unknown.

## Repeatable live-eval protocol (PA #71)

Static wording/packaging checks do not test restaurant discovery. Run these
read-only against the real web using the candidate skill, recording synthetic
prompts and no private owner/stay information:

1. **Luodong Tuesday dinner:** “I love lamb.” Resolve an actual Tuesday and local
   dinner time. Find a lamb-focused option, exclude Tuesday-closed places, and
   show dated photos plus a sourced menu/price line.
2. **Osaka Namba:** request Bib Gourmand. Use Michelin's own current venue pages
   and direct Guide links; do not promote Selected, old awards or far-away
   Osaka venues as current Namba Bib Gourmand. State any radius expansion.
3. **Seoul or Songdo:** use Naver/Kakao or Blue Ribbon public evidence and native
   Korean queries, not an English-only roundup.

For each run save: timestamp/timezone, skill revision, exact prompt and declared
assumptions, ordered queries, tool names, returned URLs and short relevant
verbatim excerpts, blocked/failed attempts and fallbacks, final user-facing
output, and a criterion-by-criterion self-grade. Retain source publication and
visit/photo dates separately from retrieval time. Save complete public tool
results locally when useful; publish only bounded non-sensitive evidence, not
private context, customer data, authenticated provider responses or ledgers.

Grade PASS / PARTIAL / FAIL for: curated/local-language source use; exact branch
and owner fit; recent review/complaint evidence; sourced menu and price basis;
actual-day hours and exclusions; 2–3 dated photos per option; one pick plus two
alternatives; every factual line sourced; reservation handoff with no actions.
Count unknowns and gaps honestly. A link with no date is not a dated photo; a
labelled price tier is truthful but does not satisfy a numeric price criterion.
If dated photos, recent reviews or current menu cannot be established, mark
that criterion PARTIAL/FAIL rather than filling it from model knowledge.

A separate non-author reviewer reads all three transcripts and outputs as well
as the diff, checks load-bearing sources, and records ACCEPT/REJECT/DEFER against
the exact PR head. Author self-grades, CI and reviewer verdict are distinct.
Any later change invalidates the old exact-head acceptance until re-reviewed.
