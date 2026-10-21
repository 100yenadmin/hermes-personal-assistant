# Research checks

Research checks run offline against the final answer and kept tool results.
They pair same-line citations with amounts and isolate evidence by source URL;
browser results follow the current page URL in log order. Search hits prove
only their own URL-bearing record, and a URL mentioned in prose is not a fetch.

An amount matches when its normalized number and a currency in its family both
occur in the source's linked text. This does not prove they describe the same
quantity: the judge must check that relationship and the recommendation itself.
Sources cut by the result log cap can leave amounts `unverified` with reason
`source_truncated`; these are not factual errors. Web and browser results keep
200,000 characters plus a cut marker. Synthetic unit checks do not establish a
live research pass, provider completion, or customer readiness.

Known limits (fix 3; further tuning uses real lab waves):

- URL keys ignore query strings and fragments, so different query variants share
  evidence. A URL containing `(`, or a schemeless URL, can still contribute a
  date to its source entry.
- Live browser rows use `page_url` exclusively. Older rows and lookup failures
  use log-order page state (navigate, and any non-click/press/type result that
  reports a page `url`, such as back); unknown state contributes no evidence.
  Link fields inside browser results are page text, not independent fetched
  sources. A redirect counts for the requested URL too: a successful navigate,
  or a one-URL extract that read exactly one page.
- Only JSON string values are source text. Source numbers must stand alone, or
  be attached to a currency (`JPY1,500`, `1,500yen`, `S$9.90pepm`, `$40M`, read
  as 40); IDs, reference syntax and dimensions never establish an amount. A `k`
  suffix is supported. Currency and number co-occurrence still requires judge
  review.
- Amount recognition covers the listed currency signs/codes/words, common
  prefix units and Japanese man-yen. Markdown currency-column inference expects
  pipe tables with a header and separator row; other layouts need explicit
  currencies. The bare end of a range (`S$12.50–19`, `12.50 to 19 SGD`) takes
  the range's currency and is checked like any amount; a dash or "to" right
  after an amount followed by an unrelated number is read the same way.
- Recommendation options come from first-column table cells (the skill asks
  for one row per option) or bold/leading bullet names. The check passes when
  the Recommendation names a distinctive token of any compared option; it does
  not decide which option is favoured (the judge does). A transposed table makes
  criteria look like options.
- Citations pair within semicolon, cell or sentence segments, in the segment's
  style: each amount takes the cluster after it (the skill's style), or the one
  before it when that pairs more amounts. An amount with no cluster of its own
  shares the nearest one in its segment, then takes the row's Sources cell, then
  an unclaimed cluster elsewhere on the line. Commas stay inside segments;
  position cannot prove a citation supports the claim.
- Any cut text makes its source truncated. Invalid cut JSON marks every URL in
  the call arguments truncated without sharing its raw text. Co-citing even one
  truncated page makes an otherwise missing amount `unverified`, including when
  complete evidence for that URL exists; this is not a factual pass.
- Criteria and gaps need two letter-containing words and reject placeholder-only
  content. “Nothing material.” passes. The confirmation detector recognizes
  English first-person completed actions (with up to three words such as
  "also" or "gone ahead and" before the verb) and "has been <verb>" passives. A
  negation or modal counts only between the subject and the verb or right after
  the verb, so a later clause ("but they haven't replied") does not hide a
  claim. It does not prove provider actions or handle every paraphrase.
