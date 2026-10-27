# Live eval: Seoul via Blue Ribbon and Korean local platforms

## Run contract

- Author-executed real-web, read-only eval in Kanban `t_f9316036`, 2026-10-27; not an independent-agent benchmark.
- Candidate skill revision for recovery: `f3b0b005765f6148e88aadced48a1c85eafbb2ee`. The initial content was exercised before interruption; the evidence-date and query-year clarifications were applied during the author run.
- Exact synthetic prompt: **“Find dinner in Seoul using the sources locals use, not just an English roundup. Show your pick, alternatives, photos, menu prices, today's hours and booking route. Read only; don't book.”**
- Assumptions: Tuesday 2026-10-27, 18:30 Asia/Seoul, two adults for comparison math only; district/stay, budget, dietary needs and recent meals unknown. No lamb preference carried across from the separate Taiwan case.
- Recovery clock recheck (`TZ=... date`): `Asia/Taipei 2026-10-27 Tuesday 15:05:57 CST`; `Asia/Tokyo 2026-10-27 Tuesday 16:05:57 JST`; `Asia/Seoul 2026-10-27 Tuesday 16:05:57 KST`. Initial research was interleaved across locales.

## Condensed live tool transcript

Decisive real calls and bounded literal excerpts, not invented full responses. Public extracted text is distinguished from direct browser access.

| Tool / actual query or target | Observed evidence / decision |
| --- | --- |
| `web_search`: `서울 영등포 강남 블루리본 청기와타운 티엔미미 육전국밥` → public Blue Ribbon venue pages | Native Korean lists, exact addresses/phones and dish names; 청기와타운 explicitly `서울 2026 선정`. Did not infer an edition/ribbon count for pages without one.[23][24][25] |
| `web_extract` Blue Ribbon 청기와타운 | 영중로10길 32-4; `월~일요일 11:30~22:00 (마지막 주문 21:00) 연중무휴`; older guide menu 수원왕갈비 `29,000원`.[23] |
| `web_search`: `청기와타운 영등포본점 네이버 메뉴 31000 2026`; `web_extract` Diningcode | `15cm 수원왕갈비 31,000원`; `2인분부터 주문 가능`; 미나리 들기름 막국수 `13,000원`. Newer-looking listing is still undated, so report the price conflict, not a guaranteed October amount.[27] |
| `web_extract` exact Naver Place owner feed | Owner notices **2026-10-20**, **2026-10-06**; `네이버 예약` route promoted, signature ribs and sides named; `21:00에 라스트오더`. These are owner posts, not independent reviews.[26] |
| Direct public GET and isolated `browse open` of Naver Place | Direct requests were rate-limited; browser displayed a service-access restriction. No login, CAPTCHA bypass or repeated browser retry. Later `web_extract` could read public indexed feed/home text; not claimed as successful direct Naver browser access.[26][50] |
| `web_search`: `"청기와타운 영등포본점" "2026. 9." 블로그`; `web_extract` Polle dated visit | Exact branch address matched; post date **2026-03-12**, two actual image URLs. Historical, not a fresh September visit.[35] |
| `web_extract` Diningcode and Naver Blog 육전국밥 서교점 | Current listing 육전국밥 `11,000원`, while Blue Ribbon says `10,000원`; dated **2026-06-07** Naver visit at 월드컵북로9-1 says `24시간 영업`, 곱해장 `13,000원`.[28][25][30] |
| `web_extract` Blue Ribbon / Diningcode / Naver Place 티엔미미 | Guide says 22:00 close, dinner LO21:00; local listing says 21:00 close, LO20:00; Naver Place supports LO20:00 and reopening17:00. **Closing-time conflict retained; quarantined as an unverified lead**, not a third tonight-ready pick.[24][36][33] |
| `web_search`: `"티엔미미 강남점" "2026. 10." 블로그` → public Naver Blog | Extracted a real dated visit **2026-04-27** after following a search result; did not turn the search query's October into a photo date.[44] |
| Public HTML photo extraction + image probes | Two actual original images for each of three researched branches, all six HTTP200 `image/jpeg`; no image content or caption invented, and none rehosted.[35][44][30] |


## Recovery readback

Current `web_extract` rechecks read all three Blue Ribbon listings, the exact barbecue Naver owner feed, Tian Mimi Naver home and the three Diningcode menus. The Blue Ribbon pick explicitly says `서울 2026 선정`; the Naver feed's latest readable owner post says `2026.10.20.`.[23][26]

Tian Mimi's closing/last-order conflict remains visible, so it stays outside the shortlist.[24][33][36]

## Final user-facing output

**My pick: 청기와타운 영등포본점**, a Korean barbecue dinner at the exact branch listed in **Blue Ribbon's Seoul 2026 selection**. That's my taste judgment, not a claim about an unknown owner preference.[23]

Compared for **Tuesday 2026-10-27, 18:30 Asia/Seoul**. Seoul-wide comparison because your stay/district is unknown; I have not invented travel times. I have **one pick and one supported alternative**; a third researched venue stays below under **unverified leads** because its closing time conflicts.[24][33][36]

### Pick — 청기와타운 영등포본점 / Blue Roof Town, Yeongdeungpo main branch[23][26]

- **Where / identity:** 서울 영등포구 영중로10길32-4; Blue Ribbon address matches the Naver owner feed and dated Polle visit. This is **not** a different 청기와타운 branch.[23][26][35]
- **What to order:** 15cm 수원왕갈비; the owner feed also lists 미나리 들기름 막국수 and describes staff grilling. No dietary/allergen safety claim is implied.[26][27]
- **Price example per person:** Diningcode lists ribs **₩31,000/portion, minimum two**, plus **₩13,000** for one shared 미나리 들기름 막국수: **(31,000×2 + 13,000) / 2 = ₩37,500/person**, excluding drinks and any unverified fees. Its menu is undated; Blue Ribbon's 2026 edition gives **₩29,000/250g** for 수원왕갈비, so **today's final price is not confirmed**.[27][23]
- **Tonight:** **scheduled 11:30–22:00, LO21:00, daily** per Blue Ribbon; public Naver feed also says LO21:00. Latest readable owner notice is Oct20, with no Oct27 closure shown in the inspected feed. That is not a guarantee against an unpublished same-day closure or a sold-out dining room.[23][26]
- **Practical / booking route:** Naver reservation is promoted by the **2026-10-06** owner post; app/login/foreign-visitor eligibility and tonight's slots remain untested. Public owner inquiry **0507-1316-1474**; no call or queue entry made.[26]
- **Recent evidence / caveat:** the independent Polle post is **March12**, older than the desired recent sample. Diningcode displays a June8 room-delay report without a year and older reviews; **I cannot establish a repeated recent complaint trend**. Owner posts are not counted as independent visits.[35][27][26]

- [Photo 1](https://d2uja84sd90jmv.cloudfront.net/posts/6pvah39KyLuckZzRHjs9iw/ms.jpg?updated=-62167392000) — 옘미 / Polle; publication **2026-03-12 (historical)**; capture date unknown; **not visually inspected**; [original source page](https://polle.com/j47433298/posts/1).[35]
- [Photo 2](https://d2uja84sd90jmv.cloudfront.net/posts/-OmWWClbKl9YACw2vt5hzw/ms.jpg?updated=-62167392000) — 옘미 / Polle; publication **2026-03-12 (historical)**; capture date unknown; **not visually inspected**; [original source page](https://polle.com/j47433298/posts/1).[35]

### Alternative — 육전국밥 서교점 / Yukjeon Gukbap, Seogyo branch[25]

- **Where / order:** 서울 마포구 월드컵북로9-1, 1층; order **육전국밥**, or **곱해장** if you want the offal soup described in the dated visit. Native address matches Blue Ribbon and the Naver Blog check-in.[25][30][28]
- **Price per person:** Diningcode lists **육전국밥 ₩11,000/bowl**, while Blue Ribbon has **육전소고기국밥 ₩10,000**; exact current price remains unconfirmed. **곱해장 ₩13,000/bowl** appears in the **2026-06-07** visit and current undated Diningcode menu; tax/service/payment acceptance details are unknown.[28][25][30]
- **Tonight:** **scheduled 24 hours daily**, corroborated by the dated Naver visit; no last-order/entry or latest official temporary-closure notice was established. This is a scheduled dinner fallback, not a confirmed seat.[25][30]
- **Recent evidence / caution:** June7 blogger praises cleanliness/service and says `내돈내산`; that is **one person's account**, not an independent audit or repeated trend. Diningcode's visible August21 review omits a year; its reported ₩12,000 spend is not relabelled as the menu price.[30][28]
- **Route:** public inquiry phone **02-322-6364**. Reservation acceptance, booking-required policy and an exact online booking route were not established; **booking route unknown**, so do not promise a reservation.[25]

- [Photo 1](https://mblogthumb-phinf.pstatic.net/MjAyNjA1MzBfMjM2/MDAxNzgwMTI1NTI0NDE4.lROXj07ahXe7tu5FR9zqbANJcKELn9FXoVHK6tLkD2cg.ciy_R7fL4iNcI3ZlaSuvJ-MpoSP3QKCW4vfUKHQAkcYg.JPEG/SE-8fa4554f-0ca0-4b37-be3e-8bb74d560847.jpg?type=w400) — 여행하는 Groot / Naver Blog; publication **2026-06-07**; capture date unknown; **not visually inspected**; [original source page](https://m.blog.naver.com/PostView.naver?blogId=kmi0508&logNo=224301021811).[30]
- [Photo 2](https://mblogthumb-phinf.pstatic.net/MjAyNjA1MzBfMTcz/MDAxNzgwMTI3NzM1NzE1.Jdt52vDhE29fXVTZ-Y22dD6YKTH5nTGPALTcEAWUclIg.pZ_42mNykU0XEH0tU7kLCbEwrc05awaQzH5a21GGmN0g.JPEG/%EB%8B%A4%EC%9A%B4%EB%A1%9C%EB%93%9C_(7).jpg?type=w400) — 여행하는 Groot / Naver Blog; publication **2026-06-07**; capture date unknown; **not visually inspected**; [original source page](https://m.blog.naver.com/PostView.naver?blogId=kmi0508&logNo=224301021811).[30]

### Unverified lead — 티엔미미 강남점 / Tian Mimi Gangnam — not a tonight-ready alternative[24][33]

- **Where / appeal:** 서울 서초구 사임당로143, 104-1/104-2/104-3; dim sum/Cantonese dishes, with the correct Gangnam Naver branch. Blue Ribbon says the venue relocated from Seochon in May2024; no old-Seochon photos are passed off as this branch.[24][33]
- **Order / price reference:** Diningcode lists **딤섬 SET ₩40,000/person, minimum two**, and 토마토탕면 **₩15,000/bowl**; menu date, tax/service terms and exact October price are unknown.[36]
- **Why not shortlisted:** Blue Ribbon says dinner **17:00–22:00, LO21:00**; Diningcode says **17:00–21:00, LO20:00**, and Naver supports LO20:00. All suggest an 18:30 service window, but the full closing-time conflict remains unresolved, so I am **not calling it verified/bookable tonight**. The pages' relative “today/Sunday” banners are not used as a Tuesday clock.[24][36][33]
- **Practical / reviews:** the **2026-04-27** local visit reports a roughly20-minute wait and tight table spacing; recent-looking Diningcode excerpts mention both reservations and walk-ins, but several dates lack a year or are relative. Catchtable is a **reported route to re-verify**, not proven account/foreign-visitor access; phone **0507-1476-1686** is on the native Naver branch page.[44][36][33]

- [Photo 1](https://mblogthumb-phinf.pstatic.net/MjAyNjA0MjNfMjMy/MDAxNzc2OTExMzM4NDIy.s3T2EV-1zYvKGihObWiHyO4KLUY_MOv0w24Aj7aMuHwg.eVOHi0r3NHFQEIWx6YmiZMyBA8mwSlsSs7RxCXMgAhEg.JPEG/KakaoTalk_20260423_103235521_04.jpg?type=w400) — 라니 / Naver Blog; publication **2026-04-27**; capture date unknown; **not visually inspected**; [original source page](https://m.blog.naver.com/raneeelog/224267190609).[44]
- [Photo 2](https://mblogthumb-phinf.pstatic.net/MjAyNjA0MjNfMTky/MDAxNzc2OTExNDAwNTQz.3vJPUhQm-6KjqWy8QCizDibE6vOLDF74BpNG_5xn1J8g.nnVXo5RE9bTbMVqpz-ebXr608cHyBWKcGZRe2c_-NbUg.JPEG/KakaoTalk_20260423_103235521_06.jpg?type=w400) — 라니 / Naver Blog; publication **2026-04-27**; capture date unknown; **not visually inspected**; [original source page](https://m.blog.naver.com/raneeelog/224267190609).[44]

**Choice:** I'd pursue 청기와타운's exact Yeongdeungpo branch first.[23][26] Want me to prepare the reservation through `personal-assistant:restaurant-reservations`? The handoff would keep Tuesday18:30 Asia/Seoul, party size still to confirm, unknown stay/budget/dietary needs, the dated/undated price conflict, scheduled hours/LO, source freshness and Naver/phone route. It would **not** register a queue, log in, call or reserve without that next workflow's checks and confirmations.

## Self-grade against #71

| Criterion | Grade | Evidence / limitation |
| --- | --- | --- |
| Korea native-platform / Blue Ribbon acceptance | PASS | Korean queries, three public Blue Ribbon listings, Naver Place feed/home and Naver Blog visits; not English-only.[23][24][25] |
| Exact branch / owner fit | PASS for identity; PARTIAL for personalization | Native addresses cross-matched; no private PA context read. District, budget and preferences remain unknown.[26][30][33] |
| Actual-day hours / unsafe option handling | PASS for scheduled shortlist | Two scheduled dinner choices; conflicting third venue quarantined, not silently “resolved”. Latest-notice coverage incomplete for fallback.[23][25][24] |
| Menu / per-person basis | PARTIAL | Numeric sourced references and explicit math, but conflicting/undated current menu amounts.[27][28][36] |
| Two dated photos per researched venue | PASS for provenance; PARTIAL for freshness | Six real links/date labels, no visual inspection; main pick's March images historical.[35][30][44] |
| Recency / repeated complaints | PARTIAL | Dated June visit and fresh owner notices; relative/yearless review dates and insufficient independent recent sample.[30][26][27] |
| One pick plus two supported alternatives | PARTIAL | Deliberately one pick + one alternative + one unverified lead; no invented completeness. |
| Every restaurant fact cited / safe handoff | PASS, author check | Unknowns and conflicts explicit; no bookings, queue entries, calls, login, sign-up or preference changes. |

**Overall: Korea's specific local-source live acceptance demonstrated; broader completeness and freshness remain partial.** Next improvement: resolve Tian Mimi's current hours from a fresh branch-owned schedule, obtain dated recent photographs for the barbecue pick, verify visitor booking eligibility, and read a larger date-qualified independent-review sample.

## Sources

[23] https://www.bluer.co.kr/restaurants/31098
[24] https://www.bluer.co.kr/restaurants/31240
[25] https://www.bluer.co.kr/restaurants/38830
[26] https://m.place.naver.com/restaurant/1244027748/feed
[27] https://www.diningcode.com/profile.php?rid=A1VsJaRXO2kN
[28] https://www.diningcode.com/profile.php?rid=Q2TZI5oTilQB
[30] https://m.blog.naver.com/PostView.naver?blogId=kmi0508&logNo=224301021811
[33] https://m.place.naver.com/restaurant/1277052112/home
[35] https://polle.com/j47433298/posts/1
[36] https://www.diningcode.com/profile.php?rid=deLs35hMcPFD
[44] https://m.blog.naver.com/raneeelog/224267190609
[50] https://m.place.naver.com/restaurant/1244027748/home
