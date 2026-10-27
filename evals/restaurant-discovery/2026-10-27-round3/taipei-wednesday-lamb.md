# Taipei Wednesday dinner — round-3 live eval

## Binding and proof boundary

Prompt: “Taipei, Wed 28 Oct dinner, near Taipei Main / Zhongshan, 3 adults; owner loves lamb.” Read-only public-web eval under a 15-minute end-to-end budget. Meal date is **2026-10-28, Wednesday, Asia/Taipei** (calendar checked in Python); **18:30–20:00 is an assumption**, not an owner-confirmed time. No budget, allergies, prior meal or private stay was invented. Lamb comes from the task, not a fabricated profile: the exposed native PA schema lacks `profile`; no Eva-profile access or live preference-read claim.

Candidate skill: round-3 policy patch based on `626c60cd03239cce50c824a30a81ac9b2cac55e0`; final immutable head is in the PR/task handoff. The timing receipt records the measured completion. This is an author-run live eval, not independent acceptance, a native-profile integration test, a Telegram delivery test, or provider availability proof.

## Compact recommendation — default chat output

**Wed 28 Oct · Taipei (UTC+8) · 3 adults · assume 18:30–20:00; Zhongshan-side lamb dinner.**
**Recent reviews unchecked.** These are scheduled-open options, not confirmed seats or temporary-closure guarantees; last order/entry unverified.
**Pick: 大黑屋・中山北路店** — my choice for your lamb preference: start with the mixed lamb platter; 中山北路二段74號. [Menu](https://www.daikokuya.com.tw/products/2/1) · [Branch](https://www.daikokuya.com.tw/branch/all/1)
Wed **17:00–23:00**; **NT$660/person minimum including 10% service**, not a full-meal estimate; dinner limit **90 min**. [Hours](https://www.daikokuya.com.tw/branch/all/1) · [Terms / booking route](https://inline.app/booking/-OUsZ90SqiIuR2hltEiw:inline-live-3/-OUsZ980klcwpsU_muEJ?language=zh-tw)
**Alt 1: 阿財蔬菜羊肉爐** — vegetable-broth pot + sliced meat; 長安東路一段58號; example three-person order **about NT$783/person**, January prices, fees extra/unknown. [Dated menu/order evidence](https://upssmile.com/267483/a-cai-mutton-hotpot)
Wed schedule **17:00–00:30**; a published guide says **three people must walk in**, so queues make it my backup, not the timed first choice. [Schedule](https://upssmile.com/267483/a-cai-mutton-hotpot) · [Three-person rule](https://supertaste.tvbs.com.tw/food/357614)
**Alt 2: 下港吔羊肉專賣店・天祥路18號** — pot + grilled ribs + shared noodles/stir-fry; **about NT$420/person**, August example prices, fees/drinks unverified. [Dated menu](https://hanblog.tw/mutton/)
Wed **11:30–01:00**; this is a **northward extension toward 民權西路, not a strict Taipei Main/Zhongshan-station-core match**. [Official hours](https://www.mutton.com.tw/shop194/index.php?action=news) · [Location](https://hanblog.tw/mutton/)
Travel times unverified; check the linked street addresses before choosing. No private origin or route URL is shared; detailed evidence is available separately.
**My pick is 大黑屋 for the lamb-led grill dinner. Want me to prepare a reservation?**

### Photo groups accompanying the compact output

All six originals were actually pixel-inspected in one helper call, two candidates per finalist, all kept; no extra gallery viewing. **Dates below are publication proxies within 12 months of the meal, not verified capture dates.** Capture dates are unknown; these are not claimed as October photographs. No image bytes are committed or rehosted.

- **大黑屋:** [1 — pale pink folded slices in a black bowl](https://dm0520.com/wp-content/uploads/2026/02/daikokuya-105.jpg); [2 — glossy pink-brown slices in a black bowl](https://dm0520.com/wp-content/uploads/2026/02/daikokuya-147.jpg). Credit **DAVID & MILLY**, published **11 Feb 2026**, capture dates unknown. Both are plated-food views, not a verified grill-action photo or visually proven meat species. [Original article](https://dm0520.com/blog/post/daikokuya).[20]
- **阿財:** [1 — pale broth with green pieces/red flecks and a filled ladle](https://upssmile.com/wp-content/uploads/2026/01/20000101-IMG_1149.jpg); [2 — red slices over green leaves on a white plate](https://upssmile.com/wp-content/uploads/2026/01/20000101-IMG_1132.jpg). Credit **upssmile**, published **18 Jan 2026**, capture dates unknown. `20000101` in the filename is not treated as a capture date. [Original article](https://upssmile.com/267483/a-cai-mutton-hotpot).[9]
- **下港吔:** [1 — broth-filled pot with browned chunks, leaves, white rounds and golden sheets](https://hanblog.tw/wp-content/uploads/2026/08/DSC03032.jpg); [2 — glossy browned bone-in pieces on a square plate](https://hanblog.tw/wp-content/uploads/2026/08/DSC03062.jpg). Credit **涵的足跡**, published **27 Aug 2026**, capture dates unknown; pictured pot is the source's larger shared serving, not a promise of the proposed one-pot order's portion. [Original article](https://hanblog.tw/mutton/).[16]

## Condensed live tool transcript

The ordered searches below are actual `web_search` calls, not reconstructed hypothetical commands. Opened sources used `web_extract`; direct ordinary no-login HTML fetches via `urllib.request` established image provenance and exposed an extractor/menu discrepancy. Only six selected images were downloaded/viewed. Publication metadata was read before the photo helper.

| Order | Query / tool | Decisive result |
|---|---|---|
| 1 | `site:guide.michelin.com tw 2026 必比登 台北 七 城市` | Official 14 Jul 2026 announcement: Taipei is in scope; 37 Taipei Bib entries. No out-of-scope-city skip is claimed in this Taipei eval.[1] |
| 2 | `台北 中山 台北車站 羊肉爐 羊肉 晚餐 2026 菜單` | Local-script leads included 阿財, 大黑屋 and lunch-only 莫里. Exa Places is a lead aggregator, not a current review sample or visit proof.[5] |
| 3 | `中山站 羊肉 餐廳 2026 菜單 營業時間` | PEKO/iFoodie sources; no restaurant promoted from a rating alone.[3][18] |
| 4 | `Taipei Main Zhongshan lamb dinner restaurant menu 2026` | Michelin Lin's at 吉林路327號, outside the intended station-core focus; no hours-complete recommendation or false Bib label.[4] |
| 5 | `大黑屋 中山北路 店 官方 菜單 營業時間 2026` | Exact branch, official schedule and public inline terms.[6][7][8] |
| 6 | `阿財蔬菜羊肉爐 upssmile 2026 週三 公休 菜單` | Exact address, all-week schedule and January menu/order basis.[9][10] |
| 7 | `青花驕 中山北店 菜單 羊肉 2026 營業時間` | Core-area generic-hotpot lead; not shortlisted because lamb suitability was not established. No photo budget spent on it. |
| 8 | `大黑屋 中山 2026 05 08 羊肉 菜單 照片 2026 三人套餐` | Dated official news supports service/minimum and exposes lunch-opening discrepancy; official product list opened.[14][15] |
| 9 | `下港吔 羊肉 2026 9月 食記 布雷克` | Opened August original blog and official notices. Search-date terms did not make January Blake content recent.[16][17][19] |
| 10 | `大黑屋 中山北路 2026 食記 羊肉 照片` | Opened DAVID & MILLY February original for documented photo provenance, not recent independent-visit proof.[20] |
| 11 | `web_extract` public Facebook and destination-only Maps, two attempts | Batch first returned only the reachable mutton site; explicit retry returned `Content was inaccessible or not found`. Stopped; no login, browser installation or CAPTCHA workaround.[11][12] |
| 12 | Opened iFoodie → original blogs | 阿財 records displayed March/January posting dates; 下港吔 August posts did not establish exact independent visit dates. Recent-review window remains unchecked, not “no complaints”.[18][9][10][16] |
| 13 | `urllib.request` HTML prefilter + six original-image downloads | Article publication metadata retained, candidates selected by article region only; no pixels inspected in broad search. `photo-inspection.json` records hashes, prefilter rationale and actual helper captions. |
| 14 | One `delegate_task` image-input call | Six images, 2/2/2, 21.94 seconds, all kept. Actual pixel-only captions; pick-2 was **not** the expected grill view, so its caption says plated slices. Model route was existing gpt-6.1-sol; no cheap/fast-route claim or provider/config switch. |

## Separate evidence cards — not default chat

### Guide scope and geography

The official 2026 announcement includes Taipei. This is a generic dinner request, **not** a Bib/category-filter request: no complete category sweep was required or claimed, and none of the three finalists is called Michelin. The new out-of-scope-city shortcut is policy/static coverage, **not exercised** by this in-scope city.[1]

The shortlisted public addresses are 中山北路二段74號, 長安東路一段58號 and 天祥路18號.[6][9][17] No numeric walking radius, private stay or routed travel time was supplied. 大黑屋 is on the 雙連 side; 下港吔 is explicitly a northward 民權西路 extension, not three strict station-core matches. If strict Taipei Main/Zhongshan-core walking distance is essential, the geographic criterion is incomplete rather than silently widened.[16][20]

### Pick — 大黑屋 中山北路店

Exact branch: 中山北路二段74號1、2樓, phone **+886 2 2536 8668**. Official branch listing says weekdays **17:00–23:00**; public booking terms and 6 May news add weekday lunch **11:30–14:00**. All support the complete assumed Wednesday 18:30–20:00 dinner window, so a lunch discrepancy is disclosed but does **not** exclude dinner.[6][7][8]

Public terms: **NT$600 minimum/person + 10% service**, dinner **90 minutes**, up to six people directed to inline; no takeaway/packing and no outside food/drinks. The numerical floor is `600 × 1.10 = NT$660/person`, `× 3 = NT$1,980` for three. This is not an adequate-meal quote; the eventual bill depends on the order. Last order, payment methods and 28 October temporary closure/seat availability remain unverified. The displayed August sample slots were not treated as October availability; no form was filled.[8][14]

Order judgment: start with **大黑拼盤**, whose four cuts are named in the official menu, then decide extras within the group's appetite.[15] The extractor returned older prices (**770** platter / **990** deluxe), while direct live HTML returned **中850、小570 / deluxe1070**. This is a real unresolved retrieval-version discrepancy, not silently selected pricing; the compact recommendation deliberately gives only the separately corroborated minimum, and a current order total is unknown.[15]

### Alternative 1 — 阿財蔬菜羊肉爐

Exact branch: 長安東路一段58號; phone **+886 2 2562 5522**. January and March original blogs list all-week **17:00–00:30**; TVBS says **17:00–01:00**. That closing difference is immaterial for 18:30–20:00; it is retained rather than called agreement on closing. Official Facebook/current notices could not be read. iFoodie's generic “today” state was not reinterpreted as tomorrow's Wednesday schedule.[9][10][18][21]

Proposed three-person order from January prices: base **1,000** + sliced meat **1,000** + rolls **150** + cabbage **50** + three noodles **3 × 50** = **NT$2,350**, **NT$783.33/person before unverified fees/drinks**. The reported one-noodle basket was NT$2,250; the proposal intentionally adds two more noodle portions. Seasonal 菜心 availability and current October prices are unconfirmed, and the pot size/adequacy must be checked before ordering.[9]

TVBS says **four or more only for advance reservation; three must walk in**. The blogs' generic booking advice is not proof three can book. This queue risk is why it is a backup. January report says two-hour dining limit; last order, current minimum, payment and service charge remain unknown. Booking preparation must first reconcile the party-specific rule; no queue was joined.[9][10][21]

### Alternative 2 — 下港吔羊肉專賣店

Exact branch: 天祥路18號; official phone **+886 2 2536 7922** and schedule **11:30–01:00**, with August original-blog support for the same interval. Re-review's ordinary public GET at **10:54:40Z** showed **2026/06/24 — 6/30-7/12宅配暫停出貨** as its newest visible news entry. Earlier `web_extract` output had returned **2026/09/11 — 10/16起宅配包裝重新調整，暫停出貨**; that entry could not be reproduced by direct GET. This is an extraction/source-version discrepancy, **not a verified latest-notice check**. Both texts concern shipping, not proof the dining room is closed. The bounded observations are retained in `notice-readback.json`; October 28 temporary closure and seats remain unconfirmed.[16][17]

Dine-in example uses the **27 Aug** blog, not the official e-commerce basket: pot **600** + ribs **360** + noodles **120** + stir-fry **180** = **NT$1,260 / 3 = NT$420/person before unverified fees/drinks**. The site's **500** pot is on a shipping/shopping surface, so it is **not** substituted for the dine-in price. Current October prices, last order, payment/time limit and whether a three-person booking is accepted remain unverified; official phone is a route to ask, not proof of eligibility.[13][16][17]

### Exclusions, leads and review coverage

- **莫里羊肉麵:** aggregator showed Mon–Fri **10:30–14:00** only; excluded from dinner candidates at lead-screening stage, not claimed officially closed. No photos inspected.[5]
- **Lin's Vegetable Lamb Hotpot:** official Guide address **327 Jilin Road** and lamb fit established, but not the requested station-core locality or actual-day hours; retained as an unverified farther lead, no photos.[4]
- **青花驕:** local lead, lamb-menu fit not established; not used to manufacture a third supported lamb option.
- Recent independent-review sample: **0 date-qualified visits established within 28 Apr–28 Oct 2026**. The public platform extraction failed, and opened originals do not provide verified recent visit dates/independence. Photo-publication recency and venue news do not repair this gap. No current complaint trend, safety assurance or “no complaints” claim.[9][10][16][18][20]
- Older evidence was not promoted as current: PEKO's March meat-portion complaint is a dated anecdote outside the six-month window; Blake's January article is outside it too.[10][19]

## Self-grade against the requested outcome and #71

| Criterion | Grade | Evidence / honest limit |
|---|---|---|
| End-to-end 15-minute budget | PASS for original timed run; later corrections disclosed | 507.814s from first search batch to saved output/photo evidence/self-grade; two provenance/notice defects were corrected after independent review, outside the frozen eval interval. Not a claim the publication revision existed before the deadline. |
| Curated/native-language source use | PASS | Official scope and lamb Guide lead checked; Chinese and English searches. No false Michelin/category-exhaustion claim. |
| Exact branch / owner fit | PARTIAL | Lamb is explicit prompt context and branch matches are sourced; live PA-profile path unavailable, no claim of a saved-preference read. |
| Geography | PARTIAL | Zhongshan-side branches; northward alternative explicitly expanded, no invented walk time or three strict-core matches. |
| Recent independent reviews | FAIL | Zero date-qualified independent visits; fallback attempted, “Recent reviews unchecked” up front. |
| Menu and numeric basis | PARTIAL | Source-backed arithmetic/minimum; current item-price retrieval conflict for pick and dated alternatives, not guaranteed October totals. |
| Actual-day dinner / conflicts | PARTIAL | Wednesday dinner scheduled support; lunch disagreement does not wrongly exclude pick; closures, last orders and seats unconfirmed. |
| Photos and recency | PARTIAL | Six inspected food images, two per finalist, all publication proxies within 12 months; capture dates unknown, not verified recent capture. |
| Pixel captions / bounded inspection | PASS | One call, 6 viewed, 2 per finalist, no gallery or wrong-species labels; unexpected plated pick-2 caption corrected from pixels. |
| Compact Telegram-first format | PASS for saved text, delivery untested | Ten recommendation lines plus three photo groups; full evidence separate; native Telegram rendering/attachment delivery not exercised. |
| Citations / privacy | PASS for public artifact | Factual lines link exact sources, no private stay/origin, no route-time invention; mechanically checked citation mapping is not source-truth proof. |
| Handoff/no provider actions | PASS | Offer only; public route/terms passed, no booking, login, calls, messages, queue entries, PA writes or runtime/config changes. |

**Overall: useful, bounded dinner recommendation; PARTIAL research completeness, not a blanket full pass.** The seven policy fixes are exercised where the case permits, with unchecked reviews/current pricing/geography kept visible. The out-of-scope-city path and a genuinely dinner-overlapping conflict need another case to prove behavior; static guards alone do not establish them. Independent review must judge the final immutable head separately.

## Sources

[1] https://guide.michelin.com/tw/zh_TW/article/michelin-guide-ceremony/taiwan-2026-bib-gourmand-list
[3] https://pekoblog.tw/mutton
[4] https://guide.michelin.com/us/en/taipei-region/taipei/restaurant/lin-s-vegetable-lamb-hotpot
[5] https://exa.ai/library/places?q=2aefdd17defd4135
[6] https://www.daikokuya.com.tw/branch/all/1
[7] https://www.daikokuya.com.tw/news/all/1
[8] https://inline.app/booking/-OUsZ90SqiIuR2hltEiw:inline-live-3/-OUsZ980klcwpsU_muEJ?language=zh-tw
[9] https://upssmile.com/267483/a-cai-mutton-hotpot
[10] https://pekoblog.tw/a-cai
[11] https://www.facebook.com/189745388300963
[12] https://www.google.com/maps/search/?api=1&query=北海道旭川成吉思汗大黑屋+中山北路二段74號
[13] https://www.mutton.com.tw
[14] https://www.daikokuya.com.tw/news_detail/31
[15] https://www.daikokuya.com.tw/products/2/1
[16] https://hanblog.tw/mutton
[17] https://www.mutton.com.tw/shop194/index.php?action=news
[18] https://ifoodie.com.tw/restaurant/559d80ecc03a103ee86c814a-%E9%98%BF%E8%B2%A1%E8%94%AC%E8%8F%9C%E7%BE%8A%E8%82%89%E7%88%90
[19] https://blake.com.tw/blog/post/xia-gang-ye-2601
[20] https://dm0520.com/blog/post/daikokuya
[21] https://supertaste.tvbs.com.tw/food/357614
