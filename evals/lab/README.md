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
