import json

import pytest
from jsonschema import validate

from personal_assistant import trip_facts as tf, trip_watch as tw
from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.privacy import clean
from personal_assistant.state import Ledger

SEG = dict(carrier='JL', number='45', origin='HND', destination='CDG',
    origin_timezone='Asia/Tokyo', destination_timezone='Europe/Paris',
    scheduled_departure='2026-11-10T12:00:00+09:00', scheduled_arrival='2026-11-10T19:00:00+01:00',
    status='scheduled', terminal_departure='3', terminal_arrival='2E')
T0, T1, T2 = '2026-11-01T00:00:00+00:00', '2026-11-02T00:00:00+00:00', '2026-11-03T00:00:00+00:00'


def put(root, seg=None, source='user', at=T0, **kwargs):
    return tf.record_facts(Ledger(root), 'synthetic', [SEG if seg is None else seg], source, observed_at=at, **kwargs)


def watch(root, **kwargs):
    return tw.plan(Ledger(root), 'synthetic', at='2026-11-09T00:00:00+00:00', hb2_timezone='UTC', **kwargs)


@pytest.mark.parametrize('key,value', [('carrier', 'jL'), ('number', '12345'), ('origin', 'HN'),
    ('destination', 'cdg'), ('origin_timezone', 'No/Such_Zone'), ('scheduled_departure', '2026-11-10T12:00:00'),
    ('scheduled_arrival', '2026-11-09T12:00:00+09:00'), ('status', 'missing'),
    ('terminal_arrival', 'too-long-terminal'), ('terminal_departure', '2;rm'), ('origin', 42)])
def test_validation(tmp_path, key, value):
    with pytest.raises((ValueError, KeyError)):
        put(tmp_path, {**SEG, key: value})


def test_missing_unknown_and_excess_segments(tmp_path):
    missing = dict(SEG)
    del missing['scheduled_departure']
    for seg in [missing, {**SEG, 'booking_reference': 'synthetic-restricted'}]:
        with pytest.raises(ValueError):
            put(tmp_path, seg)
    with pytest.raises(ValueError):
        tf.record_facts(Ledger(tmp_path), 'synthetic', [SEG] * 9, 'user')
    with pytest.raises(ValueError):
        put(tmp_path, source='web')


def test_digest_ignores_source_observation_and_clean_roundtrip(tmp_path):
    first = put(tmp_path, source='calendar')
    again = put(tmp_path, source='user', at=T1)
    assert first['digest'] == again['digest'] and again['revision'] == 1 and not again['changed']
    assert first['segments'][0]['segment_id'] == 'JL45:2026-11-10'
    stored = tf.facts(Ledger(tmp_path), 'synthetic')
    assert clean(json.loads(json.dumps(stored))) == stored
    assert stored['segments'][0]['source'] == 'user'
    assert stored['history'][-1] == {'digest': again['digest'], 'source': 'user', 'observed_at': T1}
    assert Ledger(tmp_path).get('action', 'pa:trip-facts:synthetic')['action_type'] == 'trip_facts'
    readonly = Ledger(tmp_path, read_only=True)
    assert tf.facts(readonly, 'synthetic') == stored


def test_older_observation_ignored(tmp_path):
    first = put(tmp_path, at=T1)
    old = put(tmp_path, {**SEG, 'status': 'cancelled'}, at=T0)
    assert not old['changed'] and old['digest'] == first['digest'] and old['revision'] == 1
    assert old['segments'][0]['observed_at'] == T1


def test_scheduled_precedence_but_new_estimates_and_status(tmp_path):
    first = put(tmp_path, source='inbox')
    shifted = {**SEG, 'scheduled_departure': '2026-11-10T13:00:00+09:00',
               'estimated_departure': '2026-11-10T14:00:00+09:00', 'status': 'delayed'}
    observed = put(tmp_path, shifted, source='observer', at=T1)
    seg = observed['segments'][0]
    assert seg['scheduled_departure'] == first['segments'][0]['scheduled_departure']
    assert seg['estimated_departure'] == '2026-11-10T05:00:00+00:00' and seg['status'] == 'delayed'
    overridden = put(tmp_path, shifted, source='user', at=T2)
    assert overridden['segments'][0]['scheduled_departure'] == '2026-11-10T04:00:00+00:00'
    assert overridden['revision'] == 3


def test_compare_and_set_rolls_back_and_history_bounded(tmp_path):
    first = put(tmp_path)
    with pytest.raises(ValueError, match='digest changed'):
        put(tmp_path, {**SEG, 'status': 'cancelled'}, expected_digest='wrong', at=T1)
    assert tf.facts(Ledger(tmp_path), 'synthetic')['digest'] == first['digest']
    assert put(tmp_path, at=T1, expected_digest=first['digest'])['revision'] == 1
    for _ in range(22):
        put(tmp_path, at=T2)
    assert len(tf.facts(Ledger(tmp_path), 'synthetic')['history']) == 20


def test_facts_mode_scheduled_baseline_and_material_revisions(tmp_path):
    first = put(tmp_path)
    planned = watch(tmp_path)
    assert planned['inputs']['departure_at'] == SEG['scheduled_departure']
    assert planned['inputs']['arrival_at'] == SEG['scheduled_arrival']
    assert planned['inputs']['arrival_timezone'] == 'Europe/Paris'
    assert planned['inputs']['facts_digest'] == first['digest'] and not planned['facts_stale']
    delay = {**SEG, 'estimated_departure': '2026-11-10T15:00:00+09:00', 'status': 'delayed'}
    put(tmp_path, delay, at=T1)
    delayed = watch(tmp_path)
    assert delayed['revision'] == planned['revision'] and delayed['facts_stale']
    assert delayed['facts']['segments'][0]['status'] == 'delayed'
    small = {**delay, 'scheduled_departure': '2026-11-10T12:40:00+09:00'}
    put(tmp_path, small, at=T2)
    assert watch(tmp_path)['revision'] == planned['revision']
    material = {**small, 'scheduled_departure': '2026-11-10T12:45:00+09:00'}
    put(tmp_path, material, at='2026-11-04T00:00:00+00:00')
    shifted = watch(tmp_path)
    assert shifted['revision'] != planned['revision']
    assert shifted['inputs']['departure_at'] == material['scheduled_departure']
    put(tmp_path, {**material, 'status': 'cancelled'}, at='2026-11-05T00:00:00+00:00')
    cancelled = watch(tmp_path)
    assert cancelled['revision'] != shifted['revision'] and cancelled['arm'][0]['state'] == 'not_applicable'
    assert cancelled['arm'][0]['reason'] == 'cancelled'


@pytest.mark.parametrize('field,value', [('number', '46'), ('scheduled_departure', '2026-11-11T12:00:00+09:00')])
def test_different_flight_or_date_changes_plan(tmp_path, field, value):
    put(tmp_path)
    original = watch(tmp_path)
    seg = {**SEG, field: value}
    if field == 'scheduled_departure':
        seg['scheduled_arrival'] = '2026-11-11T19:00:00+01:00'
    put(tmp_path, seg, at=T1)
    assert watch(tmp_path)['revision'] != original['revision']


def test_round_times_to_five_minutes(tmp_path):
    result = watch(tmp_path, departure_at='2026-11-10T12:04:59+09:00', arrival_at=SEG['scheduled_arrival'])
    assert result['inputs']['departure_at'] == SEG['scheduled_departure']


def test_needs_input_read_only_and_stored_inputs_replay(tmp_path):
    ledger = Ledger(tmp_path)
    readonly = Ledger(tmp_path, read_only=True)
    assert tw.plan(readonly, 'empty')['status'] == 'needs_input'
    assert ledger.list('action') == []
    with ledger.connect() as conn:
        assert not conn.execute("select name from sqlite_master where name='pa_events'").fetchone()
    explicit = watch(tmp_path, departure_at=SEG['scheduled_departure'], arrival_at=SEG['scheduled_arrival'],
                     airport_lead_minutes=240, check_in_lead_minutes=200, commitments=[{'title': 'Meet', 'at': '2026-11-12T12:00:00+01:00'}])
    assert watch(tmp_path)['revision'] == explicit['revision']


def test_facts_action_schema_and_observer_facts(tmp_path):
    validate({'operation': 'trip_watch_plan', 'data': {'action': 'record_facts', 'trip_id': 'synthetic',
             'segments': [SEG], 'source': 'user'}}, SCHEMA['parameters'])
    result = dispatch(tmp_path, {'operation': 'trip_watch_plan', 'data': {'action': 'record_facts',
        'trip_id': 'synthetic', 'segments': [SEG], 'source': 'user'}})
    assert result['changed']
    planned = tw.plan(Ledger(tmp_path), 'synthetic', arm=['watch'], at='2026-11-09T04:00:00+00:00', hb2_timezone='UTC')
    assert planned['arm'][0]['state'] == 'needed'
    tw.record_wake(Ledger(tmp_path), 'synthetic', 'watch', 'w_observe')
    fields = Ledger(tmp_path).get('action', 'pa:observe-watch:' + tw._watch_id('synthetic'))['fields']
    assert fields['origin'] == {'iata': 'HND', 'tz': 'Asia/Tokyo', 'label': 'HND'}
    assert fields['destination'] == {'iata': 'CDG', 'tz': 'Europe/Paris', 'label': 'CDG'}
    assert fields['planned_facts_digest'] == result['digest']


def test_facts_mode_arms_only_next_leg(tmp_path):
    second = {**SEG, 'carrier': 'AF', 'number': '123', 'origin': 'CDG', 'destination': 'LHR',
              'origin_timezone': 'Europe/Paris', 'destination_timezone': 'Europe/London',
              'scheduled_departure': '2026-11-11T12:00:00+01:00', 'scheduled_arrival': '2026-11-11T13:00:00+00:00'}
    tf.record_facts(Ledger(tmp_path), 'synthetic', [SEG, second], 'user', observed_at=T0)
    result = tw.plan(Ledger(tmp_path), 'synthetic', at='2026-11-11T08:00:00+00:00', hb2_timezone='UTC')
    assert result['inputs']['departure_at'] == second['scheduled_departure']
    assert result['inputs']['arrival_at'] == second['scheduled_arrival']
    assert result['pulse_create']['trigger']['at'] == '2026-11-11T09:00:00+01:00'


@pytest.mark.parametrize('first_source,next_source', [('observer', 'simulated'), ('simulated', 'observer')])
def test_observer_and_simulated_have_equal_scheduled_precedence(tmp_path, first_source, next_source):
    put(tmp_path, source=first_source)
    result = put(tmp_path, {**SEG, 'scheduled_departure': '2026-11-10T13:00:00+09:00'}, source=next_source, at=T1)
    assert result['segments'][0]['scheduled_departure'] == '2026-11-10T04:00:00+00:00'


def test_needs_input_on_empty_readonly_profile_creates_nothing(tmp_path):
    ledger = Ledger(tmp_path, read_only=True)
    assert not ledger.path.exists()
    assert tw.plan(ledger, 'empty') == {'status': 'needs_input', 'needs': ['departure_at', 'arrival_at'], 'candidates': []}
    assert tf.facts(ledger, 'empty') == {}
    assert list(tmp_path.iterdir()) == []


def test_facts_plan_uses_next_journey_not_the_return_flight(tmp_path):
    back = dict(SEG, number='46', origin='CDG', destination='HND', origin_timezone='Europe/Paris', destination_timezone='Asia/Tokyo',
                scheduled_departure='2026-11-17T21:00:00+01:00', scheduled_arrival='2026-11-18T17:00:00+09:00', terminal_departure='2E', terminal_arrival='3')
    tf.record_facts(Ledger(tmp_path), 'synthetic', [back, SEG], 'user', observed_at=T0)
    result = watch(tmp_path)
    assert result['inputs']['arrival_at'].startswith('2026-11-10T19:00') and result['inputs']['arrival_timezone'] == 'Europe/Paris'


def test_facts_plan_keeps_same_day_connections(tmp_path):
    hop = dict(SEG, carrier='AF', number='1080', origin='CDG', destination='LHR', destination_timezone='Europe/London',
               scheduled_departure='2026-11-10T21:00:00+01:00', scheduled_arrival='2026-11-10T21:30:00+00:00', terminal_departure='2F', terminal_arrival='4')
    tf.record_facts(Ledger(tmp_path), 'synthetic', [SEG, hop], 'user', observed_at=T0)
    result = watch(tmp_path)
    assert result['inputs']['arrival_at'].startswith('2026-11-10T21:30') and result['inputs']['arrival_timezone'] == 'Europe/London'


def test_diversion_replans_without_offset_error(tmp_path):
    put(tmp_path)
    watch(tmp_path)
    diverted = dict(SEG, destination='LHR', destination_timezone='Europe/London', status='diverted')
    put(tmp_path, diverted, at=T1)
    result = watch(tmp_path)
    assert result['inputs']['arrival_timezone'] == 'Europe/London'


def test_rebooked_alternative_keeps_arms_after_a_cancellation(tmp_path):
    cancelled = dict(SEG, status='cancelled')
    rebooked = dict(SEG, number='47', scheduled_departure='2026-11-10T15:00:00+09:00', scheduled_arrival='2026-11-10T22:00:00+01:00')
    tf.record_facts(Ledger(tmp_path), 'synthetic', [cancelled, rebooked], 'user', observed_at=T0)
    result = watch(tmp_path)
    assert result['inputs']['departure_at'].startswith('2026-11-10T15:00')
    assert all(a.get('reason') != 'cancelled' for a in result['arm'])
