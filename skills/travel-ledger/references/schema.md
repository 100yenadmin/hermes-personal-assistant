# Travel Ledger Schema

Store descriptors, not secrets.

## Trip Fields

- `destinations`
- `start_date`
- `end_date`
- `timezone`
- `lodging`
- `lodging_address`
- `flight_status`
- `ground_transport`
- `source_confidence`
- `open_gaps`
- `source_refs`
- `next_actions`

## Action Fields

- `kind`
- `provider`
- `merchant`
- `booking_descriptor`
- `order_descriptor`
- `user_intent`
- `budget`
- `final_amount`
- `currency`
- `payment_descriptor`
- `address_or_route`
- `dates_or_window`
- `refund_terms`
- `message_preview`
- `final_action`
- `confirmation_text`
- `proof`
- `follow_up_at`
- `next_executable_path`

## Browser Checkpoint Fields

- `provider`
- `lane`
- `session_id`
- `context_id`
- `url`
- `state`
- `cart_or_booking_state`
- `address_or_route`
- `total`
- `missing_fields`
- `last_user_intent`
- `expires_at`
- `cleanup_status`

## Payment Readiness Fields

- `provider`
- `status`
- `descriptor`
- `budget`
- `currency`
- `funds_status`
- `missing_setup`
- `card_attached_providers`
- `last_checked_at`

## Connectivity Profile Fields

Rows are keyed by `(subject_id, field_name)` in the existing ledger's `connectivity_profiles` table. Each row stores `value_json`, an aware ISO `confirmed_at`, a short `source`, and ledger timestamps.

- Device: `device_model`, `region`, `carrier_unlocked`, `esim_supported`, `os`
- Workload/constraints: `uses`, `livestream_direction`, `stream_bitrate_mbps`, `hours_per_day`, `hotspot_devices`, `data_gb_per_day`, `min_upload_mbps`, `max_latency_ms`, `budget_currency`, `budget_total`, `router_carry_ok`, `redundancy`
- Trip/ownership: `trip_countries`, `trip_start`, `trip_end`, `owned_connectivity`

Only these allowlisted fields are accepted. A small keyword and identifier-like numeric-pattern guard rejects some sensitive-looking values, including in `source`, but it is not DLP or exhaustive rejection. Callers must never submit IMEI/EID/QR data, credentials, phone numbers, passport data, payment data, or other secrets. Reading does not change `confirmed_at`; a stored JSON `null` is treated as an unknown/absent fact at read time, while write-time null values remain rejected atomically.
