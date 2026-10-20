import datetime as dt
import json

import pytest

from personal_assistant import concierge, trip_watch as tw
from personal_assistant.daily_ops import trip_context as daily
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger
from test_trip_facts import SEG
from test_trip_watch_arms import BASE


def test_airport_is_not_leave_time(tmp_path):
    ledger = Ledger(tmp_path)
    unknown = tw.plan(ledger, **BASE)
    assert unknown['leave_by'] is None and unknown['needs_airport_transfer']
    assert unknown['at_airport_by']['local_time'] == '09:00'
    known = tw.plan(ledger, trip_id='synthetic', airport_transfer_minutes=62, at=BASE['at'])
    assert known['leave_by']['local_time'] == '07:55'
    assert known['leave_by']['transfer_minutes'] == 62
    assert tw.plan(ledger, trip_id='synthetic', at=BASE['at'])['inputs']['airport_transfer_minutes'] == 62
    assert 'airport_transfer_minutes' not in tw.plan(ledger, **BASE)['inputs']
    [airport] = tw.departures(ledger, at=BASE['at'])
    event = {'id': 'flight', 'summary': 'Flight', 'start': {'dateTime': BASE['departure_at']}}
    [alert] = daily.leave_by_alerts({'travel': {'leave_by': True}, 'timezone': 'UTC'}, [event],
        dt.datetime.fromisoformat('2026-11-10T09:01:00+00:00'), None, departures=[{**airport, 'leave_by_at': None}])
    assert alert['line'] == '✈️ airport by 09:00 — Flight (transfer time unknown)'


@pytest.mark.parametrize('form', ['flat', 'string', 'dict'])
def test_save_flight_forms(tmp_path, form):
    expected = dispatch(tmp_path, {'operation': 'trip_watch_plan', 'data': {
        'action': 'record_facts', 'trip_id': 'array', 'source': 'user', 'segments': [SEG]}})
    data = {'action': 'record_facts', 'trip_id': form, 'source': 'user', **(
        SEG if form == 'flat' else {'segments': json.dumps([SEG]) if form == 'string' else SEG})}
    saved = dispatch(tmp_path, {'operation': 'trip_watch_plan', 'data': json.dumps(data)})
    assert saved['digest'] == expected['digest'] and saved['next_step']['offer_trip_watch']
    with pytest.raises(ValueError, match='record_facts'):
        tw.dispatch(Ledger(tmp_path), {'action': 'status', 'trip_id': form, **SEG})


def test_import_offers_watch_once(tmp_path):
    path = tmp_path / 'flight.ics'
    path.write_text('BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:f\nDTSTART:20991110T120000Z\nEND:VEVENT\nEND:VCALENDAR\n')
    args = {'operation': 'trip_import', 'data': {'trip_id': 'synthetic', 'ics_path': str(path)}}
    assert dispatch(tmp_path, args)['next_step']['offer_trip_watch']
    ledger = Ledger(tmp_path)
    assert ledger.list('action') == []  # A hint reserves and arms nothing.
    concierge.dispatch(ledger, {'action': 'record', 'trip_id': 'synthetic', 'offer_type': 'trip_watch', 'outcome': 'declined'})
    assert 'next_step' not in dispatch(tmp_path, args)


def test_night_watch_explains_required_setting(tmp_path):
    for night in (True, False):
        [arm] = tw.plan(Ledger(tmp_path), **BASE, arm=['watch'], night_alerts=night)['arm']
        assert arm['requires']['recommended_settings'].get('quiet_hours_urgent', False) is night


def test_unplanned_status_is_readable(tmp_path):
    assert dispatch(tmp_path, {'operation': 'trip_watch_plan', 'data': {
        'action': 'status', 'trip_id': 'missing'}}) == {'planned': False, 'trip_id': 'missing'}


def test_transfer_is_bound_to_facts_origin(tmp_path):
    from personal_assistant.trip_facts import record_facts
    ledger = Ledger(tmp_path)
    record_facts(ledger, 'synthetic', [SEG, {**SEG, 'origin': 'CDG', 'destination': 'HND',
        'scheduled_departure': '2026-11-20T12:00:00Z', 'scheduled_arrival': '2026-11-21T12:00:00Z'}], 'user')
    first = tw.plan(ledger, trip_id='synthetic', airport_transfer_minutes=60, at='2026-11-09T00:00:00Z')
    assert first['inputs']['airport_transfer_origin'] == 'HND'
    assert tw.status(ledger, 'synthetic', at='2026-11-19T00:00:00Z')['leave_by'] is None
    assert tw.plan(ledger, trip_id='synthetic', at='2026-11-19T00:00:00Z')['needs_airport_transfer']


@pytest.mark.parametrize('kind', ['past', 'all_day', 'missing', 'planned', 'opted_out'])
def test_offer_hint_suppression_is_read_only(tmp_path, kind):
    ledger = Ledger(tmp_path)
    ledger.put('trip', 'synthetic', {'events': [{'start': '2099-11-10T12:00:00Z' if kind != 'past' else BASE['at'],
        'all_day': kind == 'all_day', 'source_missing': kind == 'missing'}]})
    if kind == 'planned':
        tw.plan(ledger, **BASE)
    if kind == 'opted_out':
        concierge.dispatch(ledger, {'action': 'record', 'trip_id': 'synthetic', 'offer_type': 'trip_watch', 'outcome': kind})
    before = ledger.list('action')
    assert tw.offer_hint(Ledger(tmp_path, read_only=True), 'synthetic', at='2026-11-19T00:00:00Z') is None
    assert ledger.list('action') == before


RETURN = {**SEG, 'origin': 'CDG', 'destination': 'HND', 'origin_timezone': 'Europe/Paris', 'destination_timezone': 'Asia/Tokyo',
          'scheduled_departure': '2026-11-20T12:00:00+01:00', 'scheduled_arrival': '2026-11-21T08:00:00+09:00'}


def test_explicit_times_transfer_never_reaches_the_return_leg(tmp_path):
    from personal_assistant import trip_math
    from personal_assistant.trip_facts import record_facts
    ledger = Ledger(tmp_path)
    record_facts(ledger, 'synthetic', [SEG, RETURN], 'user')
    plan = tw.plan(ledger, trip_id='synthetic', departure_at=SEG['scheduled_departure'], arrival_at=SEG['scheduled_arrival'],
                   airport_transfer_minutes=75, at='2026-11-09T00:00:00Z')
    assert plan['inputs']['airport_transfer_origin'] == 'HND' and plan['leave_by']['local_time'] == '07:45'
    later = tw.status(ledger, 'synthetic', at='2026-11-19T00:00:00Z')
    assert later['leave_by'] is None and later['needs_airport_transfer']
    # An unbound transfer (no facts when given) applies only to the departure it was given for.
    unbound = {'airport_transfer_minutes': 75, 'departure_at': SEG['scheduled_departure']}
    assert trip_math.transfer_for(unbound, SEG) == 75 and trip_math.transfer_for(unbound, RETURN) is None
    assert trip_math.transfer_for(unbound, {}) == 75 and trip_math.transfer_for({**unbound, 'airport_transfer_minutes': 0}, SEG) == 0


def test_legacy_plan_moment_reads_as_airport_time(tmp_path):
    from personal_assistant.state_loop import StateLoop
    ledger = Ledger(tmp_path)
    tw.plan(ledger, **BASE)
    with ledger.connect() as conn:  # Rewrite the stored payload as a derivation-3 plan would have stored it.
        row = conn.execute("select payload_json from pa_events where event_id=?", (tw._event_id('synthetic'),)).fetchone()
        payload = json.loads(row['payload_json'])
        payload['derivation'] = 3
        payload['moments'] = [{**m, 'key': 'leave_by', 'note': 'Leave for the airport.'} if m['key'] == 'at_airport_by' else m
                              for m in payload['moments']]
        conn.execute("update pa_events set payload_json=? where event_id=?", (json.dumps(payload), tw._event_id('synthetic')))
    moments = {m['key']: m for m in tw.status(ledger, 'synthetic', at=BASE['at'])['moments']}
    assert 'leave_by' not in moments and moments['at_airport_by']['note'] == 'Be at the airport.'
    stored = json.loads(StateLoop(ledger).get_event(tw._event_id('synthetic'))['payload_json']
                        if 'payload_json' in StateLoop(ledger).get_event(tw._event_id('synthetic'))
                        else json.dumps(StateLoop(ledger).get_event(tw._event_id('synthetic'))['payload']))
    assert any(m['key'] == 'leave_by' for m in stored['moments'])  # The stored payload is unchanged.


def test_only_the_status_read_accepts_an_unplanned_trip(tmp_path):
    ledger = Ledger(tmp_path)
    with pytest.raises(ValueError, match='unknown event_id'):
        tw.dispatch(ledger, {'action': 'verify', 'trip_id': 'missing', 'wakes': [{'id': 'w_x', 'status': 'active'}]})
    assert ledger.list('action') == []  # verify reads the plan before it writes anything.
    with pytest.raises(ValueError, match='unknown event_id'):
        tw.dispatch(ledger, {'action': 'record_cancel', 'trip_id': 'missing', 'wake_id': 'w_x'})


def test_flat_flight_without_source_and_cancelled_offer(tmp_path):
    flat = {k: v for k, v in SEG.items()}
    saved = dispatch(tmp_path, {'operation': 'trip_watch_plan', 'data': {'action': 'record_facts', 'trip_id': 'flat', **flat}})
    assert saved['segments'] and saved['next_step']['offer_trip_watch']
    cancelled = dispatch(tmp_path, {'operation': 'trip_watch_plan', 'data': {
        'action': 'record_facts', 'trip_id': 'gone', 'source': 'user', **{**SEG, 'status': 'cancelled'}}})
    assert 'next_step' not in cancelled


def test_check_in_wake_never_after_the_leave_time(tmp_path):
    ledger = Ledger(tmp_path)
    # 12:00 departure, 4 h check-in window (08:00), 180 min lead (09:00 at the airport), 120 min transfer (leave 07:00).
    without = tw.plan(ledger, **BASE, check_in_window_hours=4, arm=['check_in_window'])
    assert without['arm'][0]['state'] != 'not_applicable'
    plan = tw.plan(ledger, **BASE, check_in_window_hours=4, airport_transfer_minutes=120, arm=['check_in_window'])
    moments = {m['key']: m['at'] for m in plan['moments']}
    assert tw._time(moments['leave_by']) < tw._time(moments['check_in_window'])
    assert plan['arm'][0]['state'] == 'not_applicable'  # A check-in wake after the leave time is useless.


def test_segments_schema_accepts_the_parsed_forms():
    import jsonschema
    from personal_assistant.entry import SCHEMA
    seg_schema = SCHEMA['parameters']['properties']['data']['properties']['segments']
    for value in ([SEG], SEG, json.dumps([SEG])):
        jsonschema.validate(value, seg_schema)
