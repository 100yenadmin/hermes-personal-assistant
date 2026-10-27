---
name: restaurant-discovery
description: Use when choosing restaurants or asking where to eat. Curate local-language, sourced picks with dated photos, menu prices and hours for the actual day, then hand off to reservations.
metadata:
  openclaw:
    skillKey: restaurant-discovery
  hermes:
    category: travel
    tags: ["travel", "restaurants", "discovery", "local-language", "photos"]
---

# Restaurant Discovery

Every `references/...` path is relative to this skill directory.

Choose and showcase a place before trying to book it. This workflow is read-only:
no bookings, queue entries, calls, messages, sign-ups or account changes. A user
liking a recommendation is not permission to transact.

## Read and bind the request

- Read `references/local-platforms.md` for country-specific sources and queries.
- Read `references/evidence-and-evals.md` for the card format and live-eval rubric.
- Read `personal-assistant:personal-assistant`, then call
  `pa(operation="profile", data={"action":"list","kind":"preference"})`
  in the current authorized owner's PA binding **before searching**. Apply
  returned food, dietary, budget and presentation preferences in force
  (`active`/`filed`); proposed inferences are not confirmed constraints and
  retired/superseded rules are not in force. Honour an explicit current-meal
  exception without changing the stored rule. Retrieve the current stay and
  recent meals only through the available focused PA context.
  Read preference text, not fixed record IDs: never bake a particular owner's
  loves, avoids or photo/menu choices into this skill. If the runtime lacks the
  profile operation or the intended binding is unavailable, state that gap;
  do not silently read another profile, change runtime/config or call a fixture
  a live preference read. Do not expose private owner/stay records in searches
  or public citations. A temporary craving is not a preference write.
- Bind destination, local calendar date, timezone and meal/arrival time first.
  Resolve “today” from the live clock in the destination, not the host timezone.
  Use available context for party size, budget, distance and recent meals. Ask
  only for a missing constraint that would change the search; otherwise show
  assumptions (for example, dinner near Namba station, hotel unknown).

## Find candidates in this order

1. **Curated lists first.** Search the Michelin Guide's own site, distinguishing
   stars, **Bib Gourmand** and Selected. Follow with Tabelog Award / Hyakumeiten
   in Japan, Blue Ribbon Survey in Korea, Michelin and local food media in
   Taiwan. Record the edition/year when shown; a historical award is not a
   current one. For a category/location request, check the address or area of
   **every entry** on the official category list, including **pagination**,
   **before widening** the radius. Record the list's declared total, unique
   entries checked and each entry's area evidence. Account for every in-area
   match as a **pick, an exclusion or an unverified lead**, with a reason;
   conflicting dinner hours do not justify silently omitting a nearby match.
   If pages or addresses are inaccessible, report the coverage gap and do not
   claim the local category is exhausted. Any wider-area suggestions must be
   labelled as an expansion, not a satisfied strict-location request.
   No exact local guide match? Say so and continue locally; do not label a
   food-blog favourite Michelin or quietly widen the geography.
2. **Search as a local.** Translate the query, not just the answer. Use native
   place/branch names plus dish, neighbourhood, weekday and menu terms. Search
   Tabelog (JP), Naver / Kakao Map (KR), Google Maps + iFoodie (TW). Open the
   matched branch page; a search snippet is a lead, not proof of current facts.
   If English results are thin, pivot to local script immediately. When a
   platform is inaccessible, retain that limitation and use a public official
   page, local guide or dated local blog; never bypass a login or CAPTCHA.
3. **Read recent evidence.** Prefer reviews from the last 6 months, giving dates
   and sample size where available. Look for repeated complaints about queues,
   portion/value, service, smoke or cleanliness across independent visits,
   rather than ranking by mean score. One complaint is an anecdote, not a trend;
   copied roundups are not independent. If recent reviews cannot be read, say
   the recency check is incomplete. No “no complaints” claim from an empty sample.
4. **Menu and visual pre-filter.** Use the venue's own current menu, then recent dated
   local blogs or public no-login social posts. Quote currency and basis (per
   person, set, portion, buffet), menu/publication date, tax/service/deposit
   terms and any uncertainty. Do not convert ¥¥ or ₩ into a numeric budget.
   A page's new publication/update date does not refresh an explicitly older
   menu/photo inside it; retain the older evidence date beside the claim.
   Derive a per-person estimate only from sourced item prices and explicit
   party/order assumptions; show the arithmetic. Collect actual venue/dish/menu
   photo links without viewing pixels during broad search. Apply the bounded
   finalist-only procedure below after ranking, linking each selected original
   image and source page. Label each
   with capture date if known; otherwise publication date and “capture date
   unknown”. Retrieval date is not photo date. Old/undated imagery is labelled
   historical/undated, never “current”; do not fill a gap with stock/generated
   imagery. At this stage collect/pre-filter links only; **defer pixel inspection
   until after steps 5–6 have selected the supported finalists**.
   **When image viewing is available**, use this bounded procedure:
   - **Finalists only:** inspect the pick + at most two supported alternatives,
     after hours/identity screening and ranking. Never inspect during broad
     search or spend this budget on unverified/excluded leads.
   - **Pre-filter before viewing:** choose candidates next to relevant dish/menu
     text in the source article, using alt text and file names as leads, not
     proof. Skip logos, maps, staircases and storefront-only shots unless the
     venue itself is the point of the recommendation.
   - **Cap and stop:** at most **3 candidate images per finalist** (about **9
     total** for a three-option response). Stop for that finalist once **2 good
     photos** are confirmed; do not open a whole gallery to fill a quota.
   - **One batched helper:** where delegation is available, pass all pre-filtered
     finalist candidates to one cheap/fast image-capable helper in the existing
     authorized model lane. Ask it to inspect pixels and return only short
     visible-content captions plus **keep/reject** decisions/reasons. Keep image
     bytes and galleries out of the main conversation. Do not change runtime or
     silently use a paid/provider fallback to select a different model. Without
     delegation, inspect inline under the same cap.
   - Prefer the recommended dish, then useful menu/prices or venue views;
     **caption only what is visible**. Do not infer meat species, ingredients,
     exact dish names or tiny menu text. Source context is not a visual finding.
     HTTP 200, filenames, alt text and page extracts are not visual inspection.
   - Save the pre-filter rationale, candidate count, viewed IDs, captions and
     keep/reject results in eval evidence. If nothing passes, say **“no verified
     dish photo”** rather than send an unchecked image. With only one suitable
     image, show one and the gap; never exceed the cap to manufacture two.
   Only if viewing is genuinely unavailable or fails, provide labelled source
   links and say not visually inspected with the actual capability/failure gap;
   do not invent a caption or infer menu text.
5. **Verify the actual day before ranking.** For the exact branch, check today's
   weekday hours, breaks, last order / last entry, special closure notices,
   cash-only/payment rules, service charge, seating limits and booking-required
   policy. Check the latest official notice and a local listing where reachable;
   a guide award or old blog alone does not prove tonight's opening. Record
   source and access time; distinguish “scheduled open” from live confirmation
   or seat availability. Drop closed-today, dinner-ineligible, sold-out or
   relocated/closed branches from tonight's picks. Put unresolved hours,
   address conflicts or essential dietary suitability in a separate
   **unverified leads** section, not the bookable shortlist. Say “unknown” for
   last order, fees or other missing fields; do not invent them. Never resolve
   contradictory hours by silently choosing the convenient one.
6. **Rank for this owner.** Prioritise hard dietary/access constraints and open
   hours, then explicit loves/avoids, distance from the stay, budget, variety
   against recent meals and evidence quality. Cite factual reasons and label
   your taste recommendation as judgment. Do not promise allergen safety from
   a dish name or assume a preference, a prior meal or a hotel location.

## Show, then hand off

Return **one pick plus two alternatives** when supported, each with native name
and exact branch/address, why it fits, what to order, sourced price per person
(or an honest unknown), hours for the stated date, last order/entry and practical
terms, two verified dated photo links when available (or the explicit gap), and
a verified booking route or “route unknown”.
Cite every factual line, including hours, prices, award status and photo
provenance. Separate unknowns and source conflicts beside the relevant field.
Fewer supported options are better than invented completeness; report which
checks could not be completed. Closed exclusions are not alternatives.

End with a concrete choice: “My pick is X for Y. Want me to prepare a reservation?”
On selection, load `personal-assistant:restaurant-reservations` and pass the exact
branch, date/time/timezone, party size, preferences, menu/price basis, hours and
source freshness, policy gaps, public booking URL and known app/login/phone
needs. Do not fill a form or create a reservation action/checkpoint during pure
discovery. Reservation preparation, final-state confirmation, Browserbase user
final tap, fees, calls/messages and provider-result proof remain owned by that
skill and its approval/ledger routes; recheck changeable facts before acting.
