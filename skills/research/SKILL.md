---
name: research
description: Answer a research or comparison question with fixed criteria, a one-page answer with a recommendation and its reason, every number sourced and dated, and declared gaps.
metadata:
  openclaw:
    skillKey: research
  hermes:
    category: productivity
    tags: ["personal-assistant", "research", "comparison", "sources"]
---

# Research

Read `reporting.md` in `../personal-assistant/references/` (relative to this skill directory) for reporting, bridge recovery, progress and pre-send checks.

Use for "compare", "find the best", "what does X cost", "which should we use" and
similar questions. Answer in the owner's language. Research is read-only: never
sign up, request a quote with the owner's details, or contact a vendor without a yes.

## Before searching

1. Restate the question in one sentence, including the facts that change the
   answer (who, where, how many, by when, budget).
2. When the answer is a choice between options, know what matters most to the
   owner (lowest cost, coverage, service, speed). A direct lookup ("what does
   plan X cost?") needs no priority. For a choice it almost always changes the
   pick, so if they have not said it, here or in
   their saved preferences, ask it first in one short question, together with
   any other fact that would change the choice (a country, a headcount, a
   budget), and wait for the answer before searching. If they have no
   preference, take lowest total cost, say so, and go. For a missing fact that
   would not change the pick, state your assumption and go.
3. Fix three to six comparison criteria, with the owner's top priority first,
   before looking at any option, and say them.

## Searching

- Prefer primary sources: the provider's own pricing, terms or docs page, an
  official register, a filing. Use secondary sources only to find primary ones,
  and say when only a secondary source exists.
- Read each page you cite. A number goes in the answer only if it appears on the
  page you cite for it, in the same currency and unit, with any condition it
  carries ("from", "per employee per month", "billed annually", "plus tax").
  Name what the price is for in the page's own words; never relabel a fee
  (a setup fee is not a monthly fee, and an add-on is not the base price) or
  widen its terms (a price billed annually is not a monthly-billing price, and
  a one-time fee is not charged per entity or per country unless the page says
  so).
- Before you write "Could not find" for something, check the pages you already
  read for it (setup fees, minimums and terms often sit lower on a pricing page).
- Note the date you read each page. A price without a date is not usable.
- When a price is behind a sales call or a login, do not guess or estimate it as
  if it were published: record it as not published.

## The answer (one page, then the appendix)

Keep everything before "Appendix" under about 350 words. Use these six
headings, exactly and in this order, even when you are confident of the answer.
The owner reads the criteria before the pick, so never open with the
recommendation:

```
## Question
<the question in one line, with the facts that change the answer>
## Criteria
- <criterion 1: the owner's top priority>
- <criterion 2>
- <criterion 3>
## Recommendation
<the option and the reason, tied to the criteria, in two or three sentences>
## Comparison
| Option | <criterion 1> | <criterion 2> | <criterion 3> |
|---|---|---|---|
| <option name> | $29 per employee/month [2] | ... | ... |
## Could not find
<what is unknown and why: not published, needs a quote, conflicting sources>
## Appendix
[1] <title>, <URL>, read YYYY-MM-DD
[2] <title>, <URL>, read YYYY-MM-DD
<then any detail the owner may want>
```

- **Comparison**: one row per option, the option's name in the first column,
  one column per criterion.
- **Every amount from a source**, anywhere in the answer and in the appendix
  detail, carries the `[n]` of the page that shows it, right after the amount:
  `$29 per employee/month [2]`. When a cell or sentence holds two amounts, each
  gets its own: `$29 per employee/month [2]; <add-on, in the page's words> $10
  per employee/month [2]`, never one `[n]` at the end for both. Give each source
  its own brackets: `[2][5]`, never `[2,5]` or `[1–3]`. Amounts the owner gave
  you, such as a budget, need no `[n]`.
- **No sums you worked out.** State each published fee as the page prints it,
  each with its own `[n]`, but do not combine them: no price times the
  headcount, no fees added together, no saving or effective rate. A starting
  price times a headcount is not a quote, and no page shows that number. When
  cost decides the pick, say in words which option costs less at the owner's
  headcount and which fee decides it ("at the published prices and 10 people,
  Birch's $29 per employee [2], with no platform fee, costs less than Cedar's
  $20 per employee [1] once Cedar's $250 monthly platform fee [1] is
  counted"), and put the all-in total under "Could not find" as something to
  get in a written quote.
- **Could not find**: never leave it out; write "nothing material" only when
  that is true.
- **Appendix**: one `[n]` line per source, each carrying its own read date on
  that line. Do not use one shared "All sources read" line: each source must
  stand alone when the owner forwards it.

No padding, no generic advice, no claims you did not check. If the sources
disagree, show both and say which you trust and why.

## After

If this was a real task for the owner, close it with
`pa(operation="evidence", data={"action":"update","identity":"<task identity>","status":"pass","closed_on":"<owner's local date>","facts":[{"item":"<number or fact>","source":"<URL>","ok":true,"facing":"money"}]})`
listing each number you checked (`facing` is `money` for a price or cost, else `internal`);
use `fail` and say so if you could not answer.
If a source would be stored redacted (a login or tracking link), cite the page
title and site instead.
