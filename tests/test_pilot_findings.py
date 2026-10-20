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
