# Live eval: Luodong, Tuesday dinner, “I love lamb”

## Run contract

- Author-executed, real-web, read-only eval in Kanban `t_f9316036`, 2026-10-27; not a simulated provider run or an independent model evaluation.
- Initial retrieval/recovery skill revision: `f3b0b005765f6148e88aadced48a1c85eafbb2ee`. Preference-aware follow-up candidate: `a6a8f59cceb96cfc3bf35e8fc06b12381ce5b364`; the skill now explicitly calls the bound PA profile API rather than naming owner-specific IDs.
- Exact synthetic prompt: **“Luodong, Tuesday dinner. I love lamb. Find a pick and two alternatives for tonight; show photos, menu/prices and hours. Don't book.”**
- Declared assumptions: 2026-10-27, arrival 18:30 Asia/Taipei, two adults for comparison only; no known hotel, budget, dietary restrictions or recent-meal history. The initial pass had no PA profile read; the follow-up below read only the two operator-authorized food records. No preference write.
- Recovery clock recheck (`TZ=... date`): `Asia/Taipei 2026-10-27 Tuesday 15:05:57 CST`; `Asia/Tokyo 2026-10-27 Tuesday 16:05:57 JST`; `Asia/Seoul 2026-10-27 Tuesday 16:05:57 KST`. Initial research was interleaved across locales.

## Condensed live tool transcript

This is a bounded transcript of decisive tool calls and literal public-source excerpts, not a reconstruction of unrun tool output. Preliminary broad searches were interleaved with the other two locale evals.

| Tool / actual query or target | Observed evidence / decision |
| --- | --- |
| `web_search`: `"羅東" "site:guide.michelin.com"`; `web_extract` Guide restaurant index | No exact local Guide match was established; the locale landing index returned global restaurants, not evidence of a Luodong award. Switched to local media/blogs; no Michelin claim attached to these picks.[52] |
| `web_search`: `羅東 羊肉爐 正老林 菜單 2026 亞里士多德` → `web_extract` ayuulife | `2026 年 1 月 31 日`; `大人每人580元`; `用餐時間120分鐘`.[1] |
| `web_search`: `羅東 火曜日 週二 公休 羊肉爐 羊肉 火鍋 牛排 TVBS 2025 4` → `web_extract` 沙拉飯團 | `營業時間：15:00~00:00(週二公休)` for 羊舖子. Excluded, rather than padding the shortlist.[3] |
| `web_search`: `羊舖子 羅東 site:ifoodie.tw 週二` → `web_extract` exact listing | The weekday detail says `週二公休`; recovery recheck also says `今日休息`. Excluded for the actual Tuesday.[12] |
| `web_search`: `李家莊羊肉爐 羅東 2026 480 520 菜單` → `web_extract` dated blog and menu aggregator | Blog says weekday `450元` without service charge; aggregator says `480` plus `10%服務費`. Do not quietly select the cheaper figure.[9][11] |
| `web_search`: `阿灶伯當歸羊肉湯 2026 菜單 價格 營業時間` → `web_extract` marsfood and June news | August article explicitly says `菜單為2024年5月拍攝`; June news reports a price rise. Its NT$85 soup is not a verified October price.[5][53] |
| Public HTTP GET and isolated `browse open` / `snapshot` of yilanljz | Rendered shop products (e.g. `NT$ 680 / 份`), but no useful branch dine-in menu/hours. Did not turn a retail portion into a buffet price.[4] |
| Isolated `browse` → Google Maps, following the link from FonFood; reject optional cookies, no login | 李家莊 exact address/phone matched; Tuesday hours button: `Tuesday, 4 to 10:30 pm, Copy open hours`. Snapshot initially said `Closed · Opens 4 pm`, which is **not** closed for dinner.[37] |
| `browse` Google Maps native-name query for 正老林 | Exact branch at Tianxiang Rd 192; Tuesday hours button: `Tuesday, 4 to 10 pm, Copy open hours`. Owner notice shown dated Sep 13, 2026.[47] |
| `browse` Google Maps native-name query for 阿灶伯 | Phone `+886 3 954 7736` matched; Tuesday hours button: `Tuesday, 4 pm to 1 am, Copy open hours`.[48] |
| Public HTML photo extraction + public image GETs | Two distinct article images per option; all six returned HTTP 200 `image/jpeg`. Publication dates came from the article, never from upload-path guessing.[1][9][5] |

Access limitations: Facebook public GET returned no usable notice text; Google Maps gave a limited unauthenticated view (no readable recent-review stream). Exa's place proxy was only corroboration, not represented as a direct Google review read.[38][2][47]


## Recovery readback

The interrupted run's draft and public HTTP/browser evidence were recovered, not silently relabelled as a fresh independent-agent run. Current `web_extract` rechecks read the January lamb-buffet article, the August article's explicit 2024-05 menu date, and iFoodie's `今日休息` plus `週二公休`; these support the dated price caveat and Tuesday exclusion.[1][5][12] A fresh isolated no-login `browse` visit followed the exact 李家莊 place ID, rejected optional cookies and opened its hours control: `Tuesday, 4 to 10:30 pm, Copy open hours`. The timestamp and exact resolved branch URL are in [hours-evidence.json](hours-evidence.json).[37]

## Preference-aware follow-up (operator steering)

Follow-up prompt: **“Luodong, Tuesday dinner. Use my saved food preferences to choose a pick and two alternatives, with photos, menu prices and what to order. Don't book.”** Unlike the first prompt, this does not supply the lamb preference in the request.

The real scoped read at **2026-10-27T07:25:38.101665+00:00** verified `pref:loves-lamb` and `pref:restaurant-photos-menu` as **active**, owner-stated food preferences. Only a derivative attestation is published; no raw profile record or private path is copied.[55]

Khan's exposed native `pa` schema omits `operation="profile"`, so this is **not** a successful native `pa` tool transcript. Under the operator's explicit two-record read scope, the existing repository `Ledger.get(..., read_only=True)` backend read those identities only, with no environment rebinding, schema/config/runtime change or profile write. Ordinary use of the new skill still requires the correctly bound native profile API; that live native path is **not proven by this fallback**.[55]

| Actual follow-up step | Observed result / effect |
| --- | --- |
| `Ledger.get("action", <operator-named identity>)`, `read_only=True`, twice | Both records in force (`active`, `category=food`, `source=said`); applied the saved lamb priority and the photos/menu/prices/order presentation rule, rather than a canned owner preference in the skill.[55] |
| `web_search`: `羅東 羊肉爐 星期二 晚餐 菜單 價格 2026 正老林 羊排` | The preference-led Chinese query returned the exact ayuulife branch article first; the older place proxy was only corroboration.[1][2] |
| `web_extract`: `https://ayuulife.com/mutton-hot-pot/` | Re-read `2026 年 1 月 31 日`, `大人每人580元`, `用餐時間120分鐘`, and the lamb ribs/bones/tendons description. This did not refresh the menu or photos to October.[1] |
| Reuse checked branch hours, dated original photos and exclusion evidence | Same lamb-led pick remains the judgment below; stale/current-price and review gaps remain disclosed, so the preference for **recent** photos is only partially satisfied.[1][47][12] |

## Final user-facing output

**My pick is 正老林羊肉爐 羅東店:** the lamb buffet is the closest match to your saved lamb preference; the article lists lamb ribs, big bones and tendons.[1][55]

I applied your saved **lamb preference** and your saved request for **photos, menu prices and what to order**.[55]

The photo links below have dated article provenance, but some are historical; the **recent-photo** part of the preference is not fully met.[1][9][5] Images were not visually inspected in this run; the [photo provenance record](photos.json) and each link label retain that limitation.

I used **Tuesday 2026-10-27, 18:30 Asia/Taipei** for this comparison. Hotel distance, budget and recent meals are unknown, so I have not invented a walking time or a reason to avoid another night market.

### Pick — 正老林羊肉爐 羅東店[1]

- **Where / why:** 宜蘭縣羅東鎮天祥路192號; a lamb-focused all-you-can-eat hotpot. My judgment: start here for a full lamb dinner rather than a snack.[1][47]
- **Order:** lamb ribs, big bones and tendons; the dated article also describes red-braised, spicy and clear vegetable broths.[1]
- **Price per adult:** **NT$580** in the **2026-01-31** article, no service charge, 120-minute meal limit; **October price, cash/card rules and last entry/order remain unverified**. This is a dated menu/price reference, not a guaranteed current bill.[1]
- **Tonight:** **scheduled 16:00–22:00 Tuesday**, checked on Google Maps today. The old blog says 12:00–22:00; that lunch-opening conflict does not affect the 18:30 dinner window. Temporary closure and seats are not independently confirmed.[47][1]
- **Recent reviews / caveat:** the readable place proxy's latest review is **2026-02-28**, outside the desired six-month window; recent-review/complaint checking is incomplete, not “no complaints”.[2]
- **Booking route:** phone inquiry **03-9551314**; whether a reservation is required or accepted for this party is unknown. No call placed.[1]

- [Photo 1](https://ayuulife.com/wp-content/uploads/2026/01/1769834464045.jpg) — 小譽的食旅地圖; publication **2026-01-31 (historical)**; capture date unknown; **not visually inspected**; [original source page](https://ayuulife.com/mutton-hot-pot/).[1]
- [Photo 2](https://ayuulife.com/wp-content/uploads/2026/01/1769834466458.jpg) — 小譽的食旅地圖; publication **2026-01-31 (historical)**; capture date unknown; **not visually inspected**; [original source page](https://ayuulife.com/mutton-hot-pot/).[1]

### Alternative 1 — 李家莊羊肉爐（吃到飽）[9]

- **Where / fit:** 宜蘭縣羅東鎮復興路三段542號; another lamb-buffet option. Suggested order: ribs, big bones and tendons, as described in the dated visit.[9][37]
- **Price per adult:** **current price unknown**. The **2024-02-16** visit says weekday **NT$450**, no service fee; an undated aggregator says **NT$480 + 10%**. Do not budget from either as a verified October quote.[9][11]
- **Tonight:** **scheduled 16:00–22:30 Tuesday**, from today's exact-branch Google Maps readback; last order/entry and temporary closures unknown.[37]
- **Practical / recency:** the dated report is historical, not evidence of recent consistency; cash/card, seating limit and current booking-required policy are unknown. Contact/inquiry **03-965-9886** is matched to the branch; no call placed.[9][37]

- [Photo 1](https://twsala40.com/wp-content/uploads/pixnet/6a8089c28aa770bf33c03d733a1033c8.jpg) — 沙拉飯團; publication **2024-02-16 (historical)**; capture date unknown; **not visually inspected**; [original source page](https://twsala40.com/2024-02-16-1417/).[9]
- [Photo 2](https://twsala40.com/wp-content/uploads/pixnet/c80fc254ced6ea680d41845048c74556.jpg) — 沙拉飯團; publication **2024-02-16 (historical)**; capture date unknown; **not visually inspected**; [original source page](https://twsala40.com/2024-02-16-1417/).[9]

### Alternative 2 — 阿灶伯當歸羊肉湯[5]

- **Where / order:** the food article gives **民權路265號**, phone **03-9547736**; order **當歸羊肉湯**. My judgment: choose this if you want a smaller lamb-led meal rather than another buffet.[5][48]
- **Price per person:** **current amount unknown**. The August article's **NT$85 soup** belongs to a menu photographed **2024-05**; June 2026 news reports increases. I will not relabel that as tonight's price.[5][53]
- **Tonight:** **scheduled 16:00–01:00**, ending Wednesday morning, per today's Google Maps readback; the local article says **Wednesday closed**. Last order/entry unknown; this does not establish live seat or queue availability.[48][5]
- **Practical / reviews:** the August article describes separate dine-in/takeaway queues and recounts both an old rude-service visit and a more pleasant later visit; that is one author's mixed history, **not a repeated recent complaint trend**. Reservation route is unverified; no queue entry or call made.[5]

- [Photo 1](https://pic.pimg.tw/magianword/1716749450-1904733954-g_l.jpg) — 馬鈴薯大哥; publication **2026-08-24 (article publication; underlying menu explicitly 2024-05; photo may predate publication)**; capture date unknown; **not visually inspected**; [original source page](https://marsfood.tw/uncle-azao/).[5]
- [Photo 2](https://pic.pimg.tw/magianword/1716749450-1771767797-g_l.jpg) — 馬鈴薯大哥; publication **2026-08-24 (article publication; underlying menu explicitly 2024-05; photo may predate publication)**; capture date unknown; **not visually inspected**; [original source page](https://marsfood.tw/uncle-azao/).[5]

**Excluded for Tuesday:** 羊舖子當歸羊肉湯, 民權路110號 — the specific Tuesday-closed note is supported by the dated local report and iFoodie's detail section, and today's recovery readback also displays `今日休息`.[3][12]

**Choice:** I'd pursue 正老林 first for the lamb buffet.[1] Want me to prepare a reservation inquiry through `personal-assistant:restaurant-reservations`? I'd carry forward the exact branch, Tuesday 18:30 Asia/Taipei, your lamb preference, the still-unconfirmed party size/budget, dated price basis, unknown last order/payment rules and phone route—then recheck before any call or booking.

## Self-grade against #71

| Criterion | Grade | Evidence / limitation |
| --- | --- | --- |
| Lamb-focused option + owner fit | PASS for scoped saved-preference read | The follow-up prompt omits lamb; two actual active food records were read and used before the follow-up query. Native bound `pa profile list` is not proven by the labelled backend fallback.[55] Lamb-led picks are sourced.[1][9][5] |
| Tuesday exclusions / actual-day hours | PASS for scheduled hours | Direct exact-branch Google Maps weekly hours.[37][47][48] 羊舖子 excluded.[12] Not a same-day closure/seat guarantee. |
| Dated photos + menu/price line | PASS for dated provenance; PARTIAL for freshness | Two real image links each; article dates explicit. All six image GETs succeeded. Current October dine-in prices were not established.[1][9][5] |
| Curated + local-language/platform search | PARTIAL | Chinese queries, TVBS/iFoodie and direct Google Maps used.[6][12][47] No exact local Michelin result established.[52] |
| Recent reviews / repeated complaints | PARTIAL | No adequate last-six-month independent sample for the buffet pick; no average-rating ranking or invented trend.[2] |
| One pick plus two alternatives | PASS | Three sourced options, none scheduled closed at 18:30.[47][37][48] |
| Every factual output line cited | PASS, author check | Restaurant facts have inline sources; unknowns remain explicit. Citation checker validates mapping, not truth. |
| Reservation handoff / no actions | PASS | Offer only; no reservation form, booking, queue, message, call, account or preference change. |

**Overall: Taiwan's specific live acceptance behavior and a scoped live saved-preference read demonstrated, with material freshness/runtime-path gaps.** This is not a claim that every broader #71 quality goal is complete or that Khan's native `pa` surface supports the new profile API. Next improvement: a correctly bound native-profile live run, fresh branch-owned menus and a readable recent-review sample, plus visual inspection/captioning rather than source-photo links alone.

## Sources

[1] https://ayuulife.com/mutton-hot-pot
[2] https://exa.ai/library/place/c471g2j8rs2
[3] https://twsala40.com/2024-03-26-1452
[4] https://yilanljz.com
[5] https://marsfood.tw/uncle-azao
[6] https://supertaste.tvbs.com.tw/review/354838
[9] https://twsala40.com/2024-02-16-1417
[11] https://onelife.tw/menu/872
[12] https://ifoodie.tw/restaurant/5594c2dac03a10074185c33f-%E7%BE%8A%E8%88%96%E5%AD%90%E7%95%B6%E6%AD%B8%E7%BE%8A%E8%82%89%E6%B9%AF
[37] https://maps.google.com/?q=place_id:ChIJSfBaxTbkZzQRlsIX89_nQjc
[38] https://facebook.com/432129736659612
[47] https://www.google.com/maps/search/?api=1&query=正老林羊肉爐+羅東店
[48] https://www.google.com/maps/search/?api=1&query=阿灶伯當歸羊肉湯+羅東
[52] https://guide.michelin.com/tw/zh_TW/restaurants
[53] https://tw.news.yahoo.com/%E7%8D%A8%E5%AE%B6-%E7%BE%85%E6%9D%B1%E9%98%BF%E7%81%B6%E4%BC%AF%E7%BE%8A%E8%82%89%E6%B9%AF%E8%AA%BF%E6%BC%B2-%E7%BE%8A%E8%82%89%E6%B9%AF-%E9%BA%B5-%E7%A0%B4%E7%99%BE%E5%85%83-051200418.html
[55] ./preference-read-attestation.json — Operator-authorized scoped read-only PA food-preference attestation
