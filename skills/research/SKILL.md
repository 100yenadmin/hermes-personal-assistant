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

Use for "compare", "find the best", "what does X cost", "which should we use" and
similar questions. Answer in the owner's language. Research is read-only: never
sign up, request a quote with the owner's details, or contact a vendor without a yes.

## Before searching

1. Restate the question in one sentence, including the facts that change the
   answer (who, where, how many, by when, budget).
2. Fix three to six comparison criteria before looking at any option, and say
   them. If one missing fact would change the choice (a country, a headcount,
   a budget), ask that one question first; otherwise state your assumption and go.

## Searching

- Prefer primary sources: the provider's own pricing, terms or docs page, an
  official register, a filing. Use secondary sources only to find primary ones,
  and say when only a secondary source exists.
- Read each page you cite. A number goes in the answer only if it appears on the
  page you cite for it, in the same currency and unit, with any condition it
  carries ("from", "per employee per month", "billed annually", "plus tax").
- Note the date you read each page. A price without a date is not usable.
- When a price is behind a sales call or a login, do not guess or estimate it as
  if it were published: record it as not published.

## The answer (one page, then the appendix)

Keep everything before "Appendix" under about 350 words:

1. **Question**, restated in one line.
2. **Criteria**, as a short list.
3. **Recommendation**: the option and the reason, tied to the criteria, in two
   or three sentences.
4. **Comparison**: a compact table with one row per option, the option's name in
   the first column, and one column per criterion. Every number carries its
   source number, like `$29 per employee/month [2]`.
5. **Could not find**: what is unknown and why (not published, needs a quote,
   conflicting sources). Never leave this out; write "nothing material" only
   when that is true.

**Appendix**: numbered sources, each as `[n] title, URL, read YYYY-MM-DD`, then
any detail the owner may want.

No padding, no generic advice, no claims you did not check. If the sources
disagree, show both and say which you trust and why.

## After

If this was a real task for the owner, close it with
`pa(operation="evidence", data={"action":"update","identity":"<task identity>","status":"pass","closed_on":"<owner's local date>","facts":[{"item":"<number or fact>","source":"<URL>","ok":true,"facing":"money"}]})`
listing each number you checked (`facing` is `money` for a price or cost, else `internal`);
use `fail` and say so if you could not answer.
If a source would be stored redacted (a login or tracking link), cite the page
title and site instead.
