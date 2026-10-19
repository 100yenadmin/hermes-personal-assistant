# Transfer and Arrival Risk

Read this file **relative to the `itinerary-intake` skill directory** after extracting an itinerary and before calling a flight-to-flight connection safe, protected, tight, or complete, or before assessing late-arrival property access. It is provider-neutral guidance for a bounded, read-only assessment; it does not book, check in, message a property, or submit a provider action.

## Source discipline

Use the exact issued itinerary, ticket, booking confirmation, or carrier/airport/property source for each claim. An aggregator, search result, or user recollection can identify a candidate segment but cannot prove protection, interline handling, baggage-through, a cutoff, or property access.

## Air-connection scope

This worksheet is intentionally limited to a flight-to-flight connection. Do not apply its flight-number, airport/terminal, operating-carrier, bag-drop, or boarding-cutoff fields to rail-to-rail or rail-to-air transfers, and do not infer a multimodal transfer judgment from them. Retain the available rail facts and state that this bounded review does not cover the multimodal transfer. Late-arrival property-access checks remain in scope when the arrival may be late, regardless of the preceding mode.

For every segment and every connection, retain the source. If the required source or factual input cannot be obtained, mark the field **unknown**; if an inspected source is silent about an affirmative claim, mark it **not proven**. Record at least:

- exact travel date, local departure and arrival times, and source timezone;
- airport code and terminal at each end;
- marketing carrier and operating carrier, including any carrier handoff;
- flight number and two independent claims: `booking_reference_relation` (same, separate, or unknown booking reference/PNR) and `ticket_relationship` (one issued ticket/protected contract, explicitly separate tickets/contracts, or unknown); retain ticket numbers when available;
- checked and cabin baggage allowance, plus the source for any through-bag statement;
- the exact source for check-in, bag-drop, boarding, or other operating-carrier cutoffs;
- the arrival property's check-in window and late-arrival/access instructions when relevant.

Do not calculate durations mentally. If elapsed or connection time matters, use timezone-aware datetimes and keep each source-local date and timezone visible. Do not silently normalize a date-line or offset disagreement; if sources conflict, label **date/time ambiguity: unknown** until a source resolves it. Do not invent a minimum connection time (MCT). Do not invent a carrier cutoff, terminal transfer duration, or property access window. If the required factual value or authoritative source cannot be obtained, report it as unknown and identify the next read-only verification step; an inspected source that is silent about an affirmative claim is **not proven**, not unknown.

## Air connection worksheet

Use this worksheet only when the connection under review is flight-to-flight. Assess each air connection independently; one proven connection does not prove another.

1. **Exact itinerary/date:** match the issued segment, date, route, flight number, local times, airport, and terminal.
2. **Booking-reference relation:** record `booking_reference_relation` independently as same, separate, or unknown. A shared PNR/booking reference does not establish one ticket or a protected journey.
3. **Ticket relationship:** record `ticket_relationship` independently as one issued ticket/protected contract, explicitly separate tickets/contracts, or unknown. Retain ticket numbers when available, but distinct ticket numbers alone do not prove separate contracts or an unprotected transfer; require explicit source evidence for that relationship.
4. **Carrier handoff:** distinguish same operating carrier, explicit interline/protected itinerary, and a marketing-to-operating-carrier or full-service-to-low-cost handoff. A carrier name shown by an aggregator is not proof of the operating-carrier relationship.
5. **Airport/terminal:** verify same airport and terminal from a source. An airport change or terminal transfer is a separate operational step.
6. **Border and security path:** identify whether immigration, customs, baggage reclaim, re-check, terminal movement, and security are required or unknown.
7. **Transit/entry permission:** for an international flight connection or a self-transfer that may require landside entry, check the traveler's permission with the relevant official immigration or border authority, or official embassy/consulate guidance. Recover authorized context before asking. Use passport issuing country/citizenship, residence or visa status, onward-ticket, airside/landside, and other applicable factors only when required by that authority; do not assume nationality or location. A generic visa list is not a traveler-specific grant.
8. **Cutoffs:** use the operating carrier's exact check-in, bag-drop, and boarding cutoffs when published. Keep each cutoff separate; a general airport arrival suggestion is not a carrier cutoff.
9. **Through-bag proof:** require an explicit source statement for baggage-through at that specific connection. Record the bag-tag destination at origin when available. Through-bag proof is claim-scoped: it proves baggage-through for that claim only; it does not by itself prove airside status, waive immigration, customs, security, terminal movement, or onward check-in/bag drop, and it is not a protected-connection guarantee.

### Traveler-specific transit/entry eligibility

Check eligibility against the exact flight route, transit mode, and traveler factors at the relevant official authority. An official result explicitly matching those factors can prove permission; a generic country list, user recollection, or carrier/aggregator display cannot. Never ask for or retain a passport number, raw passport/document scan, or unnecessary identity-document contents. Recover authorized context first, then ask only for the minimum missing factor when no authorized value is available. Do not assume citizenship, passport issuing country, residence, visa status, or current location.

Use the evidence labels consistently: **Not proven** means the relevant source was inspected but failed to affirm traveler-specific permission; **Unknown** means the required traveler factor or authoritative result is unavailable, stale, or contradictory. If the permission result or a required factor is unknown, label **transit/entry eligibility: unknown**; if an official source was inspected but did not affirm permission, label **transit/entry eligibility: not proven**. Only **Proven** permission allows a safe or complete planning judgment: either label blocks a safe claim, so both `not proven` and `unknown` block calling the connection safe or complete until permission is proven. This gate governs the planning judgment, not the ticket fact: a separately evidenced `ticket_relationship` (for example, one protected ticket) is still reported as proven, while the overall connection stays unsafe/incomplete. A refusal or requirement from the authority must be reported as a source fact, not softened into planning reassurance.

### Evidence labels

Use one label per material claim:

- **Proven:** the exact source explicitly supports the claim, such as one ticket or an explicit baggage-through statement for this connection.
- **Not proven:** an authoritative or issued source for the specific claim was inspected, but it failed to affirm the claim (for example, an issued itinerary or ticket shows both flights but gives no through-bag statement). Say “through-bag status is not proven” rather than “bags are checked through.” Do not use this label when the required source or factual input was never available to inspect.
- **Unknown:** the required factual value or authoritative source is unavailable, stale, or contradictory (for example, no operating-carrier boarding cutoff was supplied, sources disagree about the transfer date, or only an aggregator display is available, because an aggregator is never the authoritative source for protection or baggage-through). Do not fill the gap with a remembered MCT, cutoff, or terminal rule, and do not relabel an inspected source that is merely silent as Unknown.
- **Planning judgment:** a separate practical recommendation based on the proven and unknown fields. It is not a carrier or airport guarantee.

Explicitly separate tickets/contracts, an unverified carrier handoff, missing through-bag proof, an international-to-domestic path, or an airport/terminal change should be surfaced as risk factors. Do not call the itinerary protected merely because the flights appear together or because through-bag handling is proven. “Same-terminal does not mean airside” and does not prove baggage-through.

## International arrival to a connection

For an international arrival followed by another flight, explicitly check each applicable step:

1. deplaning;
2. immigration;
3. baggage reclaim;
4. customs;
5. terminal or airport movement;
6. onward operating-carrier check-in or bag drop;
7. security;
8. the onward boarding cutoff.

If a step or cutoff is not proven by the relevant source, mark the evidence according to the labels above; if the required value or source is unavailable, mark it unknown. Do not replace this checklist with a generic MCT or a mental time calculation.

## Late arrival and property access

Landing time is not property-arrival time. Keep the arrival date and any midnight rollover in local time, then check qualitatively for deplaning, baggage, immigration/customs, airport-to-property transport, and the property's check-in or access process.

For a likely late arrival, require source evidence for the property's late check-in, concierge, locker, self-check-in, building registration, or ID requirements. If no property source is available, label **late-arrival property access: unknown**; if an inspected confirmation is silent about access, label it **late-arrival property access: not proven**. In either case, recommend confirming it before departure. Do not state that a room, key, host, or building will be available merely because the reservation exists, and do not contact the property without approval.

## Bounded output

Return one compact assessment per connection and one arrival-access note when relevant:

- exact date/route and local-time segment pair;
- ticket/reference relationship and operating-carrier handoff;
- airport/terminal and border/security steps;
- traveler-specific transit/entry eligibility and the relevant official authority;
- each proven, not-proven, or unknown cutoff and baggage claim;
- the single highest-consequence pinch point;
- a planning judgment that is clearly separate from source facts;
- one read-only verification step for each material unknown.

Lead with the operational pinch point. Do not declare every connection unsafe, and do not turn missing evidence into reassurance. The result is a source-grounded risk assessment, not proof of live airport conditions, provider acceptance, booking status, or property contact.
