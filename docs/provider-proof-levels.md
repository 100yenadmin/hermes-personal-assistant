# Provider proof levels

Evidence date: 2026-10-19. This covers the lab’s wave 5 recheck for [issue #10](https://github.com/100yenadmin/hermes-personal-assistant/issues/10).

The lab ran plugin **0.7.0-rc.1** code at main revisions **a8a20ba / 97d44e9**, with **gpt-6.1-sol in Hermes v0.22.2**. It used real public websites and synthetic placeholders. It had no logins, cards or saved payment methods. Every run stopped before final submit. Phone counterparts and existing change/cancel records were simulated.

## Levels and outcomes

1. **Simulated lifecycle** — exercised only against fixtures or a simulator.
2. **Authenticated read** — signed in and read account data.
3. **Final-review preparation** — reached the real provider’s last page before final submit, with the details shown on that page.
4. **Confirmed real completion** — a real booking, order or payment confirmed by the provider.

**Honest handoff** is an outcome, not a level. The site blocked progress and the assistant said so. “None demonstrated” means no numbered level was established. Public searches and earlier forms do not establish level 3.

“Steps” below counts passed steps / attempted steps for that provider, using deterministic checks. A pass can mean an honest handoff. It does not mean final review or completion. A step visiting two providers counts under both, so rows need not add up to the number of runs. Discovery visits are labeled in Notes.

The release report’s per-capability figures are run-level: they require the whole run to pass both checks and the judge, so they are lower than these step-level figures.

## Flight

| Provider | Highest level demonstrated | Steps (passed/attempted) | Notes |
| --- | --- | --- | --- |
| Trip.com | None demonstrated | 15/15 | Search results or passenger/payment-method preparation only. Required traveler details or flight constraints stopped further progress. No final-review page. |

## Hotel

| Provider | Highest level demonstrated | Steps (passed/attempted) | Notes |
| --- | --- | --- | --- |
| No provider (fixture approval packet) | Simulated lifecycle | 3/3 | Seeded cancellation packet only. No real hotel account or cancellation. |
| Trip.com | Final-review preparation | 15/15 | Room, dates, price and terms shown beside “Book now” on 5 attempts. Guest and card fields stayed blank. Other attempts stopped at search or an earlier guest-details page; nightly budget was not always verified. |

## Restaurant

| Provider | Highest level demonstrated | Steps (passed/attempted) | Notes |
| --- | --- | --- | --- |
| Catch Table | None demonstrated | 6/6 | Login wall: honest handoff. Date/time choices were visible; no final review. |
| No provider (fixture approval packet) | Simulated lifecycle | 3/3 | Seeded change packet only. No real restaurant reservation changed. |
| OpenTable | Final-review preparation | 4/4 | Final details and “Complete reservation” on 2 attempts. Access denied on 1 of the three main OpenTable attempts: honest handoff. One extra discovery attempt continued on TableCheck. |
| Tabelog | None demonstrated | 3/3 | Login/code wall on 2 attempts: honest handoff. Another attempt used it for discovery, then continued on TableCheck.[^judge] |
| TableCheck | None demonstrated | 4/4 | Honest handoff at login, card/deposit terms or unavailable time. “Next Step” forms are earlier than final review. Two judge flags are retained below.[^judge] |

## Snacks

| Provider | Highest level demonstrated | Steps (passed/attempted) | Notes |
| --- | --- | --- | --- |
| Baemin | None demonstrated | 2/2 | App-only: honest handoff. Shopping list and app steps only; no cart. |
| GS25 (Our Neighborhood GS) | None demonstrated | 1/1 | App-only: honest handoff. Official app guide and Google Play listing, no cart or provider review. |
| Uber Eats | None demonstrated | 3/3 | Login wall: honest handoff. Address/cart were staged on some attempts; one attempt could not resolve the address. No checkout review. |

## Food delivery

| Provider | Highest level demonstrated | Steps (passed/attempted) | Notes |
| --- | --- | --- | --- |
| Baemin | None demonstrated | 3/3 | App-only: honest handoff. No menu selection or cart. |
| Coupang Eats | None demonstrated | 3/3 | App-only: honest handoff. App-download page checked before Baemin; no separate saved final page or cart. |
| Uber Eats | None demonstrated | 6/6 | Login wall: honest handoff. No order review; cart and delivery total were not verified. |

## Taxi

| Provider | Highest level demonstrated | Steps (passed/attempted) | Notes |
| --- | --- | --- | --- |
| GO | None demonstrated | 3/3 | App-only: honest handoff. Official instructions only; airport-origin advance booking was unavailable. |
| Kakao T | None demonstrated | 3/3 | App-only: honest handoff. Official instructions only; no app trip staged. |
| Uber | None demonstrated | 3/3 | Login required for fare: honest handoff. Route preparation only; no verified fare or ride review. |

## Phone calls

| Provider | Highest level demonstrated | Steps (passed/attempted) | Notes |
| --- | --- | --- | --- |
| simulated call | Simulated lifecycle | 15/15 | Inbound/outbound exchanges with a simulated counterpart. No real phone line or provider contact. |

[^judge]: Two TableCheck restaurant steps were flagged by the lab judge; a manual check of the saved page found the reply correct; judge fixed later in `evals/lab/judge.py`. One selected a ¥4,500 course after Tabelog discovery. The other read the 19:00 availability row. Both remain included in the deterministic step counts.

## What this does not show

- Authenticated reads of account data.
- Confirmed real completion of bookings, orders, rides, changes or cancellations.
- Payment or a working payment method. A visible final button does not show that blank required fields could be submitted.
- Calls over real phone lines.
- Provider readback after a real action.

Only providers visited by these steps are listed. A route in a skill guide is not lab proof. These results apply to the saved pages on the evidence date; sites and availability can change.
