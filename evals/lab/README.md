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

Known limits (fix 2; further tuning uses real lab waves):

- URL keys ignore query strings and fragments, so different query variants share
  evidence. A URL containing `(`, or a schemeless URL, can still contribute a
  date to its source entry.
- Live browser rows use `page_url` exclusively. Older rows and lookup failures
  use log-order page state; unknown state contributes no evidence. Link fields
  inside browser results are page text, not independent fetched sources.
- Only JSON string values are source text. Source numbers must stand alone;
  adjacent Latin letters (including a currency code without a space), IDs,
  reference syntax and dimensions do not establish an amount. A `k` suffix is
  supported. Currency and number co-occurrence still requires judge review.
- Amount recognition covers the listed currency signs/codes/words, common
  prefix units and Japanese man-yen. Markdown currency-column inference expects
  pipe tables with a header and separator row; other layouts need explicit
  currencies. Recommendation options come from first-column table cells or
  bold/leading bullet names; distinctive capitalized name tokens and mention
  counts are a format heuristic, not a semantic preference judgment.
- Citations use nearest clusters within semicolon, cell or sentence segments,
  then unclaimed line clusters and Sources-cell fallback. Commas stay inside
  segments; proximity cannot prove a citation supports the claim.
- Any cut text makes its source truncated. Invalid cut JSON marks every URL in
  the call arguments truncated without sharing its raw text. Co-citing even one
  truncated page makes an otherwise missing amount `unverified`, including when
  complete evidence for that URL exists; this is not a factual pass.
- Criteria and gaps need two letter-containing words and reject placeholder-only
  content. “Nothing material.” passes. The confirmation detector recognizes
  English first-person completed actions and skips a whole sentence containing
  a negation; it does not prove provider actions or handle every paraphrase.
