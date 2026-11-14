# Life-admin radar

The radar surfaces renewals, important dates and deadlines ahead of time, and
lists offers nobody answered. It is read-only: reading it writes nothing.

## Record a radar item

Use one commitment action per item:

`pa(operation="action_upsert", data={"source_id":"owner-admin","action_kind":"radar","occurrence":"<short key>","action_type":"commitment","fields":{"title":"<safe summary>","radar_kind":"renewal","document":"Passport","expires_on":"YYYY-MM-DD","lead_days":183,"recurs":"none","source_ref":"<where the date came from>"}})`

| Field | Values |
|---|---|
| `radar_kind` | `renewal` (passport, visa, insurance, subscription, licence, vehicle), `important_date` (birthday, anniversary), `deadline` (a service or filing due) |
| `document` | The document or thing's name as a value, for example `Passport` or `Car service` |
| `expires_on` / `event_date` | The date, `YYYY-MM-DD`, or month-only `YYYY-MM` (read as the 1st); a birthday may use any year |
| `lead_days` | Days ahead to surface it; defaults 30 (renewal), 14 (important date), 7 (deadline). On an unanswered offer in the radar read, it is the `offer_days` wait after which the offer surfaces |
| `notice_days` | Renewal only: integer 0–730 (0–364 for a yearly record); `decide_by` is the occurrence date minus notice days, and `surface_at` is `decide_by` minus `lead_days` |
| `auto_renews` | Renewal only: boolean; whether it renews automatically |
| `cost` | Renewal only: `{amount: "9.99", currency: "USD", per: "month"}` or `per: "year"`; `annual_cost` uses exact decimal arithmetic |
| `counterparty` | Renewal only: the provider or other party's name as text |
| `recurs` | `yearly` rolls to next year after the date; `none` stays put |
| `source_ref` | Where the date came from |

Use these neutral keys. The privacy cleaner drops any key containing words such
as `passport` or `ticket number`, so never write `passport_expiry`; put the
document's name in `document` and the date in `expires_on`. Never store document
numbers.

## Read it

`pa(operation="next_action", data={"radar":true})` lists surfaced items
(`surface_at`, the date or renewal `decide_by` minus `lead_days`, has passed), trip offers still
`offered` after `offer_days` (default 3), and Chief of Staff notes still
`unknown` past `review_at`. `include_upcoming: true` adds items not yet due;
`next_surface_at` is the earliest coming one. Until it surfaces, a radar item
is left out of the ordinary `next_action` list. Keep a yearly item `pending`;
set `completed` or `cancelled` only when it should leave the radar for good.

## Timezone check

`timezone_check` means PA's timezone may be stale; `evidence` names a landed or departing flight, or home.
When `switch` is true (a flight marked landed arrived in the last 48 hours), switch and tell the owner in the same message, naming the flight and both zones; when `stored` is set, explain how to undo: "say 'keep Seoul time'" (use the old zone's name).
Otherwise ask once in the owner's language before switching.
Write `pa(operation="automations", data={"action":"preferences","changes":{"timezone":"<suggested>"}})`, then read back with `{"action":"status"}`.
If the owner says keep before a switch, write `{"timezone_kept":"<evidence_key>"}` the same way so this evidence does not ask again. If they undo after a switch, write `{"timezone":"<stored>","timezone_kept":"<evidence_key>"}` and read back.
If the owner names their home timezone, save `home_timezone` the same way.
Routines follow the preference unless pinned. Existing Hermes cron jobs keep their creation zone; if the owner has them, say their times did not move.

## Contracts and subscriptions

Record contracts, software subscriptions, domains, insurance and licences with
their end date, notice period, auto-renewal, cost (amount, currency, per month or
year), and counterparty. Keep the source of the terms in `source_ref`; never
store account numbers or contract numbers.

When one surfaces, give the owner ONE decision packet: what it is, annual cost,
renewal date, the last day to give notice (`decide_by`), and keep / cancel /
renegotiate with a recommendation and why. Say when a fact or cost is missing.
Only surfaced records get a decision. A record that has not surfaced yet counts in
the annual cost and the renewal windows, and is not listed as a decision.
In a review, offer to draft a notice; draft it only after the owner chooses.
If the owner chooses cancel or renegotiate, draft the notice to the counterparty.
Hold it for the owner's yes to the exact recipient and text through the governed
exact-action send path in `personal-assistant:follow-through`. A draft is not a send.

Say a missed notice (`notice: "missed ..."`) or a notice `gap` plainly and give the next possible
exit from the source terms; ask for those terms if unknown. Yearly records keep
the current renewal date until it passes, even if its notice deadline was missed.

`next_action` with `radar:true, contracts:true` covers records with contract terms (cost, notice, auto-renewal or counterparty) and gives annual cost per currency,
the missing-cost count, and what renews in cumulative 30/60/90-day windows,
including active records that have not surfaced yet. Never combine currencies.
