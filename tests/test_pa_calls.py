"""Synthetic unit and real-loopback transport checks; no live model or phone."""
import datetime as dt
import json
from pathlib import Path
import threading

import pytest

from evals.call_sim.server import make_server
from personal_assistant import calls
from personal_assistant.state import Ledger

PERSONAS = Path(__file__).resolve().parents[1] / 'evals/call_sim/personas'


@pytest.fixture
def sim():
    server = make_server(PERSONAS)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {'transport': 'sim', 'sim_url': f'http://127.0.0.1:{server.server_port}'}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def prepare(root, language='ko', **changes):
    return calls.dispatch(root, dict(action='prepare', purpose='예약 문의', language=language,
        to={'name': '가상 식당', 'number': 'sim-ko-restaurant'}, may_share=['name'],
        limits={'party_size': 2, 'time_window': '2026-11-21 18:00'}, **changes), session_id='fixture-session')


def invoke(root, config, identity, action, **data):
    return calls.dispatch(root, dict(action=action, call_id=identity, **data), config=config)


@pytest.mark.parametrize('language', ['ja', 'ko', 'en'])
def test_card_and_no_transport(tmp_path, language):
    card = prepare(tmp_path, language)
    assert card['call_card']['disclosure'] == calls.disclosure(language)
    assert card['call_card']['limits']['max_deposit'] == 0
    identity = card['call_id']
    for confirmation in ({}, {'confirmed': False}):
        assert invoke(tmp_path, {}, identity, 'start', **confirmation)['status'] == 'confirmation_required'
    result = invoke(tmp_path, {}, identity, 'start', confirmed=True)
    assert result['status'] == 'no_transport'
    assert 'AI' not in result['script'][0] and 'AI' not in ''.join(result['script'][:1])  # The user makes this call.
    assert '#98' in result['note']
    record = invoke(tmp_path, {}, identity, 'status')
    assert record['status'] == 'handoff' and record['outcome'] == 'handoff'
    assert record['session_id'] == 'fixture-session'
    assert calls.dispatch(tmp_path, {'action': 'status'}) == [record]


@pytest.mark.parametrize('extra', [{'unknown': 'x'}, {'to': {'name': 'X', 'secret_extra': 'x'}},
                                   {'limits': {'unknown': 1}}])
def test_unknown_keys_rejected_before_ledger(tmp_path, extra):
    data = dict(action='prepare', purpose='Ask', language='en', to={'name': 'X'}, may_share=[], limits={})
    data.update(extra)
    assert calls.dispatch(tmp_path, data)['status'] == 'invalid_request'
    assert not (tmp_path / 'state').exists()


@pytest.mark.parametrize('url', ['http://example.com', 'http://192.0.2.1:8000',
    'https://127.0.0.1:8000', 'http://127.0.0.1:8000/path',
    'http://user:pass@127.0.0.1:8000', 'http://127.0.0.1:8000?x=1'])
def test_non_loopback_or_non_origin_refused(tmp_path, monkeypatch, url):
    def never(*args):
        pytest.fail('must not make a request')
    monkeypatch.setattr(calls, 'request', never)
    identity = prepare(tmp_path)['call_id']
    result = invoke(tmp_path, {'transport': 'sim', 'sim_url': url}, identity, 'start', confirmed=True)
    assert result['status'] == 'transport_error'
    assert 'loopback' in result['note']
    assert invoke(tmp_path, {}, identity, 'status')['status'] == 'prepared'


def test_booking_round_trip(tmp_path, sim):
    identity = prepare(tmp_path, trip_id='synthetic-trip')['call_id']
    assert invoke(tmp_path, sim, identity, 'start', confirmed=True)['status'] == 'active'
    for text in ['AI 비서입니다. 11월 21일 오후 6시 2명 예약 부탁드립니다.',
                 '예약자는 가상입니다.', '전화번호는 제공할 수 없습니다.']:
        result = invoke(tmp_path, sim, identity, 'say', text=text)
        assert result['status'] in {'active', 'ended'}
    assert result['status'] == 'ended' and result['ended'] and '예약되었습니다' in result['text']
    assert invoke(tmp_path, sim, identity, 'say', text='더 문의합니다')['status'] == 'invalid_state'
    record = invoke(tmp_path, sim, identity, 'end', outcome='booked', summary='Booked two at 18:00.')
    assert record['status'] == 'ended' and record['outcome'] == 'booked'
    assert len(record['transcript']) == 8 and record['ended_at']
    row = Ledger(tmp_path).get('action', 'pa:call:' + identity)
    assert row['action_type'] == 'call' and row['trip_id'] == 'synthetic-trip'
    assert all(t['at'] for t in row['fields']['transcript'])
    assert record['transcript'][0]['text'] == calls.disclosure('ko')
    remote = calls.request(sim['sim_url'], '/transcripts')[identity]
    assert remote['outcome'] == 'booked' and remote['status'] == 'ended'
    assert 'AI 비서' in remote['transcript'][0]['text']


def test_deposit_outcome_is_agent_owned(tmp_path, sim):
    identity = prepare(tmp_path)['call_id']
    invoke(tmp_path, sim, identity, 'start', confirmed=True)
    reply = invoke(tmp_path, sim, identity, 'say', text='8명 예약 부탁드립니다.')
    assert '70000' in reply['text']
    invoke(tmp_path, sim, identity, 'say', text='본인에게 확인하겠습니다.')
    record = invoke(tmp_path, sim, identity, 'end', outcome='needs_approval', summary='Deposit exceeds zero ceiling.')
    assert record['outcome'] == 'needs_approval'
    skill = (PERSONAS.parents[2] / 'skills/phone-calls/SKILL.md').read_text()
    assert 'above `max_deposit`' in skill and '`needs_approval`' in skill


@pytest.mark.parametrize('persona', ['ja_hotel_inbound_confirm', 'ko_restaurant_inbound_change'])
def test_inbound_ring_answer_message(tmp_path, sim, persona):
    import yaml
    sheet = yaml.safe_load((PERSONAS / (persona + '.yaml')).read_text())
    ring = calls.request(sim['sim_url'], '/ring', {'persona': persona, 'reason': sheet['inbound'][0]})
    identity = ring['call_id']
    result = invoke(tmp_path, sim, identity, 'answer')
    assert result['status'] == 'active' and result['context'] == sheet['inbound'][0]
    assert invoke(tmp_path, sim, identity, 'answer')['status'] == 'invalid_state'
    invoke(tmp_path, sim, identity, 'say', text=calls.disclosure(sheet['language']))
    record = invoke(tmp_path, sim, identity, 'end', outcome='message_taken', summary='Message for user; no change approved.')
    assert record['direction'] == 'inbound' and record['outcome'] == 'message_taken'
    assert record['brief']['may_share'] == []
    assert len(record['transcript']) == 3


def test_caps_and_privacy(tmp_path, sim):
    identity = prepare(tmp_path)['call_id']
    invoke(tmp_path, sim, identity, 'start', confirmed=True)
    # Repeated deposit questions keep this scripted counterpart on the line.
    for _ in range(40):
        assert invoke(tmp_path, sim, identity, 'say', text='8명 문의입니다.')['status'] == 'active'
    assert invoke(tmp_path, sim, identity, 'say', text='8명 문의입니다.')['status'] == 'call_limit'
    record = invoke(tmp_path, sim, identity, 'status')
    assert len(record['transcript']) == 80
    assert sum(t['who'] == 'pa' for t in record['transcript']) == 40
    assert all(len(t['text']) <= 1000 for t in record['transcript'])
    result = invoke(tmp_path, sim, identity, 'end', outcome='needs_approval', summary='password: synthetic-do-not-save')
    assert 'synthetic-do-not-save' not in json.dumps(result)


def test_time_cap_and_errors(tmp_path, sim, monkeypatch):
    identity = prepare(tmp_path)['call_id']
    invoke(tmp_path, sim, identity, 'start', confirmed=True)
    row = Ledger(tmp_path).get('action', 'pa:call:' + identity)
    row['fields']['started_at'] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=16)).isoformat()
    Ledger(tmp_path).put('action', row['action_id'], row['fields'])
    assert invoke(tmp_path, sim, identity, 'say', text='안녕하세요')['status'] == 'call_limit'
    def fail(*args):
        raise RuntimeError('private transport detail must not escape')
    monkeypatch.setattr(calls, 'request', fail)
    identity = prepare(tmp_path)['call_id']
    result = invoke(tmp_path, sim, identity, 'start', confirmed=True)
    assert result['status'] == 'transport_error' and 'private' not in json.dumps(result)
    assert invoke(tmp_path, sim, identity, 'status')['status'] == 'confirmed'
    assert invoke(tmp_path, sim, identity, 'start', confirmed=True)['status'] == 'confirmation_required'
    assert invoke(tmp_path, sim, identity, 'say', text='x' * 1001)['status'] == 'invalid_request'


def test_status_last_ten(tmp_path):
    identities = [prepare(tmp_path)['call_id'] for _ in range(12)]
    assert [r['call_id'] for r in calls.dispatch(tmp_path, {'action': 'status'})] == identities[-10:][::-1]


def test_invalid_end_ack_does_not_record_success(tmp_path, sim, monkeypatch):
    identity = prepare(tmp_path)['call_id']
    invoke(tmp_path, sim, identity, 'start', confirmed=True)
    monkeypatch.setattr(calls, 'request', lambda *args: {})
    assert invoke(tmp_path, sim, identity, 'end', outcome='booked', summary='Attempt')['status'] == 'transport_error'
    assert invoke(tmp_path, sim, identity, 'status')['outcome'] is None


def test_transcript_privacy_filter_preserves_length_bound():
    record = {'transcript': []}
    calls._turn(record, 'them', 'password: synthetic\n' * 40)
    assert len(record['transcript'][0]['text']) <= 1000
    assert 'synthetic' not in record['transcript'][0]['text']


def test_named_disclosure_and_original_text_reaches_call(tmp_path):
    card = prepare(tmp_path, 'ja', on_behalf_of='サトウ')
    assert card['call_card']['disclosure'] == 'AIアシスタントです。サトウ様の代理でお電話しております。'
    assert '〇' not in ''.join(calls.disclosure(lang) for lang in ('ja', 'ko', 'en'))
    sent = []
    def fake_request(url, path, data=None):
        sent.append((path, data))
        return {'text': 'はい、承知しました。'} if path != '/calls' else {'text': 'お電話ありがとうございます。'}
    original = calls.request
    calls.request = fake_request
    try:
        sim = {'transport': 'sim', 'sim_url': 'http://127.0.0.1:9'}
        identity = card['call_id']
        assert invoke(tmp_path, sim, identity, 'start', confirmed=True)['status'] == 'active'
        line = 'Confirmation number: AB12345 です。'
        invoke(tmp_path, sim, identity, 'say', text=line)
    finally:
        calls.request = original
    assert sent[-1] == ('/calls/' + identity + '/say', {'text': line})
    stored = invoke(tmp_path, sim, identity, 'status')['transcript']
    assert all('AB12345' not in turn['text'] for turn in stored)


def test_end_closes_a_start_that_never_connected(tmp_path):
    card = prepare(tmp_path)
    def failing(url, path, data=None):
        raise OSError('simulator down')
    original = calls.request
    calls.request = failing
    try:
        sim = {'transport': 'sim', 'sim_url': 'http://127.0.0.1:9'}
        assert invoke(tmp_path, sim, card['call_id'], 'start', confirmed=True)['status'] == 'transport_error'
        assert invoke(tmp_path, sim, card['call_id'], 'start', confirmed=True)['status'] == 'confirmation_required'
        ended = invoke(tmp_path, sim, card['call_id'], 'end', outcome='no_answer', summary='The call did not connect.')
    finally:
        calls.request = original
    assert ended['status'] == 'ended' and ended['outcome'] == 'no_answer'


def test_declined_card_cancels_and_handoff_records_reported_outcome(tmp_path):
    declined = prepare(tmp_path)['call_id']
    assert invoke(tmp_path, {}, declined, 'end', outcome='booked', summary='x')['status'] == 'invalid_request'
    closed = invoke(tmp_path, {}, declined, 'end', outcome='cancelled', summary='The user declined the card.')
    assert closed['status'] == 'ended' and closed['outcome'] == 'cancelled'
    assert invoke(tmp_path, {}, declined, 'start', confirmed=True)['status'] == 'confirmation_required'
    placed = prepare(tmp_path)['call_id']
    assert invoke(tmp_path, {}, placed, 'start', confirmed=True)['status'] == 'no_transport'
    assert invoke(tmp_path, {}, placed, 'end', outcome='cancelled', summary='x')['status'] == 'invalid_request'
    reported = invoke(tmp_path, {}, placed, 'end', outcome='booked', summary='The user booked 19:00 for two.')
    assert reported['status'] == 'ended' and reported['outcome'] == 'booked'
    assert invoke(tmp_path, {}, placed, 'end', outcome='refused', summary='x')['status'] == 'invalid_state'
