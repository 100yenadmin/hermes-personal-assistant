# Live eval: Osaka Namba, Bib Gourmand

## Run contract

- Author-executed, real-web, read-only eval in Kanban `t_f9316036`, 2026-10-27; not a fresh independent-agent quality test.
- Candidate skill revision for recovery: `f3b0b005765f6148e88aadced48a1c85eafbb2ee`. The initial content was exercised before interruption; the evidence-date and query-year clarifications were applied during the author run.
- Exact synthetic prompt: **“I'm around Osaka Namba. Find Bib Gourmand dinner options for tonight, with Michelin links, photos, menu prices and today's hours. Don't book.”**
- Assumptions: Tuesday 2026-10-27, 18:30 Asia/Tokyo; two adults for illustrative menu math only; hotel, radius, budget, cuisine preference and recent meals unknown. This is not the Taiwan prompt's lamb preference.
- Recovery clock recheck (`TZ=... date`): `Asia/Taipei 2026-10-27 Tuesday 15:05:57 CST`; `Asia/Tokyo 2026-10-27 Tuesday 16:05:57 JST`; `Asia/Seoul 2026-10-27 Tuesday 16:05:57 KST`. Initial research was interleaved across locales.

## Condensed live tool transcript

Bounded decisive calls and literal public-source excerpts; failed requests are retained as failures. No unrun response is represented as a tool result.

| Tool / actual query or target | Observed evidence / decision |
| --- | --- |
| `web_search`: `難波 ビブグルマン ミシュラン 2026 火曜日 ディナー`; `web_extract` Michelin Osaka Bib filter | Own-site Bib-filtered list includes 中華旬彩 森本 and オリベ. The page is Osaka-wide, **not Namba-only**.[7] |
| `web_extract` Michelin Morimoto / Oribe / Ayamedo venue pages | Morimoto and Ayamedo explicitly say `Bib Gourmand: good quality, good value cooking`; Oribe's venue extract lacks that label, so its Bib claim is supported by the **official Bib-filtered list**, not invented from its description.[13][15][7] |
| `web_extract` Michelin Macauda | `Tuesday closed`. Excluded; no attempt to rescue it from a more convenient old roundup.[16] |
| `web_search`: `中華旬彩 森本 食べログ メニュー 2026 よだれ鶏 料金`; `web_extract` exact menu | `更新日 : 2026/10/18`; `中¥2,300 大¥2,800`; `小\1,800 大\2,300` for tantanmen.[17] |
| `web_extract` exact Tabelog Morimoto main page | Tuesday dinner `18:00 - 22:00`, food LO `21:00`, drinks LO `21:30`; dinner last entry `21:00`; cover `お一人様￥３５０`.[54] |
| `web_extract` Tabelog review list | Three visible May-2026 lunch visits include a 10:40 arrival for 11:30 opening, a five-minute table wait, and a later walk-in without queuing. These do not establish dinner wait time.[18] |
| `web_search`: `"中華旬彩 森本" "ブログ" "よだれ鶏" 2026` → `web_extract` はんつ遠藤 | Article dated `2026年08月17日`; branch address and phone match; fried rice `小2200円、大2800円`.[42] |
| `web_extract` / public GET Oribe official menu and October closure notice | Tax-inclusive menu; one drink per customer; October closure dates `5日(月)、11日(日)、12日(月)、19日(月)、21日(水)、26日(月)` — not Oct 27.[32][41] |
| `web_extract` TableCheck public Oribe policy page — **no form interaction** | Dinner 18:00–22:00, LO 21:00, 2–2.5-hour visit; `Reservations cannot be made on behalf of another person`; same-day cancellation ¥11,000/person.[46] |
| `web_extract` Tabelog Ayamedo | Tuesday 17:30–20:30; `蕎麦売り切れしまい`; `予約不可`; card/e-money/QR all unavailable, no cover.[20] |
| `web_search`: `"そば切り文目堂" "2026" "写真" ブログ` → `web_extract` dated Japanese visit | `2026 3/05`; `細切り 鴨汁そば1,600円なり`.[43] |
| Public HTML photo extraction and GET probes | Two original article image URLs each; six images served 200 image content, recorded in [photo-probes.json](photo-probes.json) and [photo-curl-fallback.json](photo-curl-fallback.json). Ayamedo Python TLS verification failed, then system-TLS `curl --fail --location` succeeded. No TLS verification was disabled. |

Initial direct Python HTTP requests to Tabelog were not useful; later `web_extract` returned public menu/listing/review excerpts. No login or CAPTCHA bypass. Recent full-review and official temporary-notice coverage remains incomplete for Morimoto and Ayamedo.[17][18][20]


## Recovery readback

Current `web_extract` rechecks read the three Michelin venue pages and official Osaka Bib filter. Morimoto/Ayamedo explicitly label Bib; Oribe remains on the official Bib-filtered list even though the venue extract omits that label.[13][15][7]

The October-18 menu and TableCheck's `Reservations cannot be made on behalf of another person` were re-read, not inferred.[17][46]

Macauda still says `Tuesday closed`.[16]

## Round-2 visual readback after independent review

This phase exercises the working skill after `a82298c`, including its new complete category/area sweep and bounded photo procedure; the new exact PR head is bound in the review handoff, not the earlier recovery-only skill SHA.

After the operator's cap steering, **one batched author-side image helper** inspected **2 pre-filtered candidates per finalist**, stopping with two kept photos each: **6 candidates for Taiwan, 6 for Japan, 4 for Korea**, 16 total across eight supported finalists. No unverified lead was included; only short captions and keep/reject decisions returned to the main session, not image bytes. The [inspection record](photo-inspection.json) includes article-position/alt/filename pre-filter evidence, selected IDs and hashes. Two Polle links come from the recovered post photo array rather than a current static image tag.[121]

An earlier **120-panel broad sweep preceded this steering and exceeded the later cap**; it informed the pre-filter, so this is a bounded recheck, not a fresh blind test or a claim that the whole session respected the later cap. The helper schema has no per-call model selector; the existing authorized image-input lane was used without a runtime/provider/config switch, not a proven cheap/fast route. This is **not independent PR review**. Original images were viewed as contact-sheet previews, not separately enlarged; dates were not refreshed by viewing.[121]

## Round-2 category/area sweep before retaining the wider fallback

The official English list and its second page declare **48 + 11 = 59** category entries. All **59 unique entries** now have opened Michelin address evidence; the [complete per-entry accounting](osaka-area-audit.md) records each address and pick/alternative/exclusion/unverified disposition. The core versus fringe classification is declared author judgment, not an invented routed-distance boundary. The only core match under that comparison scope is Minato; twelve deliberately conservative fringe flags remain visible rather than silently discarded.[56][57][120]

The direct HTTP list fetches returned empty **202** responses, so the actual evidence lane was public `web_extract`, not a claimed successful scrape.[120] Minato's official page and Tabelog desktop/mobile were freshly opened: Michelin has Tuesday `11:00-15:00`, desktop Tabelog `17:30 - 20:50`, and mobile `10:30 - 16:00` only.[58][59][60] FineDiningIndex separately gives Tuesday `10:30 - 15:40` without dinner.[61] These conflicting schedules are not proof of an open dinner slot; Minato stays an in-area unverified lead.[58][59][60]

## Final user-facing output

**My pick: 中華旬彩 森本 in Shinsaibashi**, for the current Bib Gourmand listing and a dinner menu with chicken, dim sum and noodles.[13][17]

**Namba accounting first:** I checked the addresses/areas of **all 59** entries across Michelin's two category-list pages before retaining an expanded shortlist; no nearby match is silently dropped for inconvenient hours. The full address/disposition table records one core match and twelve conservatively flagged outer-fringe candidates.[56][57][120]

**In-area unverified lead — とんかつ みな斗 / Tonkatsu Minato:** **大阪市中央区島之内2-9-26**; Tabelog classifies it under **難波・日本橋・道頓堀**, 380 m from Nippombashi. It is on Michelin's current Bib list, but **not a dinner pick**: Michelin gives Tuesday **11:00–15:00 only**, mobile Tabelog **10:30–16:00 only**, versus desktop Tabelog **17:30–20:50 dinner**. That dinner conflict remains unresolved; I will not select the convenient schedule or imply a seat.[58][59][60]

**Geography caveat:** the three cards below are an explicit **Shinsaibashi, Shimmachi and Andojimachi/Tanimachi expansion**, not three strict-Namba matches or an approved walking radius.[13][14][15] Hotel/radius and routed journey times are unknown; if Namba-only is a hard limit, I have **no verified core dinner shortlist** from this sweep, not permission to move you elsewhere. Other fringe leads and scheduled Tuesday closures are accounted for in the audit, not promoted as extra alternatives.[120]

Compared for **Tuesday 2026-10-27, 18:30 Asia/Tokyo**. All three are scheduled to serve dinner at that time, not confirmed to have seats; no same-day temporary-closure guarantee.[13][14][15]

### Pick — 中華旬彩 森本 / Chukashunsai Morimoto[13]

- **Award / where:** current Michelin venue page explicitly labels **Bib Gourmand**; 燕京ビル B1F, 大阪市中央区心斎橋筋1-4-14. Tabelog's separate Chinese WEST Hyakumeiten selection is **2024**, not a claimed 2026 Tabelog award.[13][54]
- **Order:** 四川式よだれ鶏 (**¥2,300 medium / ¥2,800 large**) and 金の胡麻香る濃厚担々麺 (**¥1,800 small / ¥2,300 large**), tax-inclusive menu updated **2026-10-18**; dim sum is also on that menu.[17]
- **Price per person:** Tabelog's shop-listed dinner **budget ¥6,000–¥7,999/person**, **not a fixed course quote**; it separately lists a **¥350/person dinner cover**. Whether that budget includes the cover or drinks is unknown.[54]
- **Tonight / last entry:** **18:00–22:00**, food LO/last entry **21:00**, drink LO **21:30**. Latest official temporary notices were not independently verified.[17][54]
- **Practical:** cards and PayPay listed; parties of three or fewer may share a six-person table. Readable listing/review pages differ on e-money acceptance, so I would not rely on e-money without rechecking.[54][18]
- **Recency / complaints:** the visible May-2026 lunch excerpts show uneven queue experiences; the August food-journalist visit supplies recent dish evidence. This is not a representative recent dinner complaint sample.[18][42]
- **Booking route:** exact-branch Tabelog online reservation route; direct shop phone **06-6252-6022**, with the listing asking diners to prefer online because calls may not connect. No slot or form selected.[54]

- [Photo 1](https://livedoor.blogimg.jp/hants/imgs/b/7/b73f7b81-s.jpg) — **Fried rice in a blue-and-white handled bowl.** はんつ遠藤; publication **2026-08-17**; capture date unknown; **visually inspected (contact-sheet pixels)**; [original source page](https://hants.livedoor.biz/archives/52236222.html).[42]
- [Photo 2](https://livedoor.blogimg.jp/hants/imgs/3/0/3079e6b3-s.jpg) — **Close-up of the fried rice in the patterned bowl.** はんつ遠藤; publication **2026-08-17**; capture date unknown; **visually inspected (contact-sheet pixels)**; [original source page](https://hants.livedoor.biz/archives/52236222.html).[42]

**Photo scope:** Morimoto's food photograph is a dish from the August article, not proof of the chicken/noodle order above; Oribe's photos below are seasonal plated dishes, not a guarantee of the exact example order.[42][39][40]

### Alternative 1 — 鉄板焼き お好み焼き Oribe / オリベ[14]

- **Award / where:** included in Michelin's current official **Bib Gourmand-filtered Osaka list**; 大阪市西区新町1-6-18 テラスレジデンス四ツ橋1F. This is **Shimmachi, not Namba**.[7][32]
- **Order:** キャベツのステーキ ゴルゴンゾーラ **¥1,100**, then スペシャルお好み焼き **¥1,980**; the official menu lists A5 wagyu ichibo **100g ¥4,520**.[32]
- **Price example, per person:** for two sharing that 100g steak, cabbage and one special okonomiyaki, plus **¥550 cover and one ¥660 black oolong each**, **(4,520 + 1,100 + 1,980 + 550×2 + 660×2) / 2 = ¥5,010/person**. These are tax-inclusive online menu prices, not a fixed meal or guaranteed sufficient order; menu publication date and any additional charge are unknown.[32]
- **Tonight / practical:** **18:00–22:00, LO 21:00**. Official October closure notice does **not** list Oct 27; latest seasonal post is Oct 26. Allow **2–2.5 hours**; maximum party four; no seats verified.[46][41][39]
- **Booking policy:** public **TableCheck** route requires the **visiting diner** to reserve and explicitly bans reservations on another person's behalf. I can prepare the details, but **cannot submit this for you**. Card required; same-day cancellation/reduced-party fee **¥11,000/person**; special-item deadlines differ and require fresh review.[46]
- **Reviews / fit caveat:** official menu says no vegan options; no independent recent-review sample was established, so I am not claiming a service/quality trend.[32][46]

- [Photo 1](https://o-ri-be.com/wp-content/uploads/2026/10/oribe20161024.png) — **Shell-on seafood with orange sauce on a white plate.** Oribe (venue); publication **2026-10-26**; capture date unknown; **visually inspected (contact-sheet pixels)**; [original source page](https://o-ri-be.com/2026/10/26/20261026/).[39]
- [Photo 2](https://o-ri-be.com/wp-content/uploads/2026/09/20260926h-705x571.jpg) — **Stacked food under dark glossy sauce with green garnish.** Oribe (venue); publication **2026-09-29**; capture date unknown; **visually inspected (contact-sheet pixels)**; [original source page](https://o-ri-be.com/2026/09/29/20260929/).[40]

### Alternative 2 — そば切り文目堂 / Ayamedo[15]

- **Award / where:** Michelin venue page explicitly labels **Bib Gourmand**; 大阪市中央区安堂寺町2-2-26, a **Tanimachi-area extension**, not a Namba branch. Tabelog lists Soba WEST Hyakumeiten **2025**.[15][20]
- **Order / price per person:** 細切り 鴨汁そば **¥1,600 for one bowl** in the **2026-03-05** visit—**historical, October price unverified**. Tabelog separately gives a shop-listed dinner budget **¥2,000–¥2,999/person**, not a course or guaranteed bill.[43][20]
- **Tonight / practical:** **17:30–20:30**, closing earlier if soba sells out; fixed last order/entry unknown. Listing says **no reservations**, no card/e-money/QR payment and no cover; use cash. Latest temporary-closure notice not independently verified.[15][20]
- **Recency:** two October-2026 visit excerpts are visible on Tabelog, but not enough readable recent detail to establish repeated service/cleanliness complaints. No mean-score ranking used.[20]
- **Route:** walk-in according to Tabelog; shop phone **06-7504-5260** for an hours inquiry, not a promise they will reserve. Michelin's generic contact-to-book wording is weaker than the explicit local `予約不可` field; booking must be rechecked before any action.[20][15]

- [Photo 1](https://xn--88jtb2b9cgc8sdee4yf22343aopua.net/wp-content/uploads/2026/03/2603051745424112-scaled.jpg) — **Noodles on a woven tray beside a black bowl.** 釣りするカツオに食べるカツオ; publication **2026-03-05 (historical)**; capture date unknown; **visually inspected (contact-sheet pixels)**; [original source page](https://xn--88jtb2b9cgc8sdee4yf22343aopua.net/2026/03/05/sobakiri-bunmokudou/).[43]
- [Photo 2](https://xn--88jtb2b9cgc8sdee4yf22343aopua.net/wp-content/uploads/2026/03/2603051736182612-1024x768.jpg) — **Printed Japanese menu held open.** 釣りするカツオに食べるカツオ; publication **2026-03-05 (historical)**; capture date unknown; **visually inspected (contact-sheet pixels)**; [original source page](https://xn--88jtb2b9cgc8sdee4yf22343aopua.net/2026/03/05/sobakiri-bunmokudou/).[43]

**Excluded tonight:** マカウダ / Macauda — Michelin's exact venue page lists **Tuesday closed**.[16]

**Choice:** I'd start with Morimoto for this first pass.[13][17] Want me to prepare a reservation through `personal-assistant:restaurant-reservations`? The handoff would preserve the exact branch, Tuesday 18:30 Asia/Tokyo, unknown party/budget, sourced dinner budget/cover, LO/last entry, source dates and Tabelog route. Oribe would instead need an **owner-made reservation**, and Ayamedo a walk-in/inquiry, not an invented booking route.[54][46][20]

## Self-grade against #71

| Criterion | Grade | Evidence / limitation |
| --- | --- | --- |
| Michelin-sourced Bib results with Guide links | PASS | Two venue pages explicitly label Bib; Oribe is on the own-site Bib filter. No Selected-to-Bib promotion.[13][15][7] |
| Namba accounting / fit | PASS for complete category/area accounting; PARTIAL for strict-location dinner fit | 59/59 addresses checked; Minato surfaced before expanded cards with its dinner conflict. All in-area/fringe dispositions visible; no verified core dinner pick claimed.[56][57][120] |
| Native-language local review/menu use | PASS | Tabelog public menu/listings/reviews.[17][18][20] Japanese blogs opened after native-name queries.[42][43] |
| Menu / per-person price basis | PASS for provenance; PARTIAL for freshness | October Morimoto menu, official undated Oribe menu; Ayamedo numeric dish price historical.[17][32][43] Budgets distinguished from quotes.[20] |
| Actual-day hours / closures | PASS for scheduled hours | Dinner windows checked; Oribe monthly notice checked.[13][41][15] Macauda excluded; temporary-notice gaps explicit.[16] |
| Two dated photos per option | PASS for provenance + bounded visual inspection; PARTIAL for freshness/exact-order coverage | Staircase removed; Morimoto now has whole-serving/detail food views, Oribe two plated dishes, Ayamedo noodles + menu. Six pre-filtered candidates, one batched helper across all evals. Dates remain historical/unknown capture; no exact example-order photo guarantee.[121] |
| Recent complaints rather than averages | PARTIAL | Some recent local excerpts, no adequate independent sample for all three; no manufactured trend.[18][20] |
| One pick plus two alternatives | PASS, widened geography | Three scheduled dinner options, location caveat prominent.[13][14][15] |
| Factual citation / safe handoff | PASS, author check | Every restaurant fact attributed; third-party booking restriction retained; no booking, call, login or form interaction.[46] |

**Overall: Japan's specific Michelin-link live acceptance demonstrated; broader location/freshness quality is partial.** Next improvement: strict-radius routing from an approved starting point and resolution of Minato's dinner conflict, newer Ayamedo menu/photos, and representative recent dinner review coverage. Static tests and this self-grade are not independent review acceptance.

## Sources

[7] https://guide.michelin.com/jp/ja/osaka-region/restaurants/bib-gourmand
[13] https://guide.michelin.com/en/osaka-region/osaka/restaurant/chukashunsai-morimoto
[14] https://guide.michelin.com/en/osaka-region/osaka/restaurant/oribe
[15] https://guide.michelin.com/en/osaka-region/osaka/restaurant/ayamedo
[16] https://guide.michelin.com/en/osaka-region/osaka/restaurant/macauda
[17] https://tabelog.com/osaka/A2701/A270201/27086074/dtlmenu
[18] https://tabelog.com/osaka/A2701/A270201/27086074/dtlrvwlst
[20] https://tabelog.com/osaka/A2701/A270204/27040266
[32] https://o-ri-be.com/home/menu
[39] https://o-ri-be.com/2026/10/26/20261026
[40] https://o-ri-be.com/2026/09/29/20260929
[41] https://o-ri-be.com/2026/09/26/2026oct
[42] https://hants.livedoor.biz/archives/52236222.html
[43] https://xn--88jtb2b9cgc8sdee4yf22343aopua.net/2026/03/05/sobakiri-bunmokudou
[46] https://www.tablecheck.com/shops/oribe/reserve
[54] https://tabelog.com/osaka/A2701/A270201/27086074
[56] https://guide.michelin.com/jp/en/osaka-region/restaurants/bib-gourmand
[57] https://guide.michelin.com/en/jp/osaka-region/restaurants/bib-gourmand/page/2
[58] https://guide.michelin.com/jp/ja/osaka-region/osaka/restaurant/tonkatsu-minato
[59] https://tabelog.com/osaka/A2701/A270202/27141118
[60] https://s.tabelog.com/osaka/A2701/A270202/27141118
[61] https://finediningindex.com/ja/osaka/tonkatsu-minato
[120] ./osaka-area-audit.json
[121] ./photo-inspection.json
