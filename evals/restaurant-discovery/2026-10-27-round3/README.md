# Restaurant discovery — round 3 (27 October 2026)

This is an additive follow-up to Eva's live-test findings on draft PR #72 at
`626c60cd03239cce50c824a30a81ac9b2cac55e0`. Earlier evals are unchanged.

## Deliverables

- [Compact Telegram text](telegram.md): ten recommendation lines, 1,913 UTF-16
  units; no outbound Telegram message was sent.
- [Photo groups](telegram-photos.md): six original-image links, visible-only
  captions, credits and publication-proxy dates; capture dates unknown.
- [Full output, evidence and self-grade](taipei-wednesday-lamb.md): separate
  evidence cards, actual queries, failures/fallbacks and explicit limitations.
- [Timing receipt](run-timing.json): **507.814 seconds** end-to-end, below the
  900-second budget; subsequent PR/review/CI work is outside this measurement.
- [Photo inspection](photo-inspection.json): one actual-image-input helper call,
  six candidates for three finalists, two kept each, hashes and pixel captions.
- [Citation ledger](sources.json): retrieved public URLs, not restaurant-quality
  certification. Original photo bytes are not committed or rehosted.

## Seven-finding change map

| Eva finding | Governing skill change | This eval / boundary |
|---|---|---|
| Deadline-aware guide scope | Declare end-to-end budget; skip a national sweep when the dated official scope excludes the city; preserve in-scope category accounting | Taipei is in scope, generic dinner not a Bib filter; excluded-city behavior is not claimed live-proven |
| Photo recency | Target <=12 months; separate capture date from publication proxy; explicit missing-recent-photo statement | All six have January/February/August 2026 publication proxies; captures unknown |
| Meal-window hours | Only load-bearing arrival/meal/last-order conflicts quarantine; disclose immaterial disagreements | 大黑屋 lunch differs; Wednesday dinner 17:00–23:00 is supported |
| Pixel captions | Adjacency/alt/filename are leads only; never dish/species evidence | Expected grill-region image actually showed plated slices; caption follows pixels |
| Compact Telegram first | About ten lines + photo groups, full cards only on request/separate attachment | Saved ten-line text and separate photo/evidence files; delivery/rendering untested |
| Route privacy | Private origin-bearing route evidence stays private; shared links destination-only | No private origin was used; public destination link only; no routed time invented |
| Review fallback | One different public no-login fallback after bounded failures; verify visit dates or front-load unchecked | Public Maps/Facebook extraction failed; opened originals insufficient; zero date-qualified visits, unchecked up front |

## Verification and limits

- New policy guards against unchanged `626c60cd`: **7 failed, 11 passed**.
- Candidate focused suite: **44 passed** (discovery, inventory parity, installed
  version probes). `scripts/validate_pack.py` and `git diff --check` pass.
- These are static/artifact/packaging guards, **not behavioral proof**. The live
  output self-grade remains **PARTIAL overall**: recent reviews unverified,
  current order-total discrepancy, no native PA-profile path, northward
  alternative explicitly expanded beyond the strict station core.
- Exact-head independent non-author verdict and hosted CI belong in the durable
  task/PR handoff, not an author self-certification in this file.
- No bookings, queues, logins, calls, messages, profile writes, runtime/config
  changes, merge or release. VERSION unchanged; Release impact: none.
