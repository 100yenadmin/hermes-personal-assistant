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
| `lead_days` | Days ahead to surface it; defaults 30 (renewal), 14 (important date), 7 (deadline) |
| `recurs` | `yearly` rolls to next year after the date; `none` stays put |
| `source_ref` | Where the date came from |

Use these neutral keys. The privacy cleaner drops any key containing words such
as `passport` or `ticket number`, so never write `passport_expiry`; put the
document's name in `document` and the date in `expires_on`. Never store document
numbers.

## Read it

`pa(operation="next_action", data={"radar":true})` lists surfaced items
(`surface_at`, the date minus `lead_days`, has passed), trip offers still
`offered` after `offer_days` (default 3), and Chief of Staff notes still
`unknown` past `review_at`. `include_upcoming: true` adds items not yet due;
`next_surface_at` is the earliest coming one. Until it surfaces, a radar item
is left out of the ordinary `next_action` list. Keep a yearly item `pending`;
set `completed` or `cancelled` only when it should leave the radar for good.
