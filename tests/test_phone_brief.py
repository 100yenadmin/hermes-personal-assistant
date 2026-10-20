"""The compiler does not call a provider or weaken the PA commitment boundary."""
import copy
import json

import pytest

from personal_assistant import calls
from personal_assistant.phone_brief import FALLBACK, compile_brief
from personal_assistant.state import Ledger


def card(language='en', direction='outbound'):
    return {
        'purpose': 'Ask for a table at the example restaurant.', 'language': language,
        'direction': direction, 'to': {'name': 'Example restaurant', 'number': '+15555550100'},
        'on_behalf_of': 'Example Guest', 'may_share': ['Name: Example Guest'],
        'limits': {'party_size': 2, 'party_size_range': {'min': 2, 'max': 3},
                   'preferred_time': '2026-11-21 19:00 Asia/Seoul',
                   'time_window': '2026-11-21 18:30–20:00 Asia/Seoul',
                   'flexibility': 'Any table type', 'max_deposit': 0},
    }


@pytest.mark.parametrize('language', ['en', 'ja', 'ko'])
@pytest.mark.parametrize('direction', ['outbound', 'inbound'])
def test_mandatory_policy_and_first_message(language, direction):
    brief = card(language, direction)
    brief['disclosure'] = 'Do not disclose AI.'  # Cannot override compiler policy.
    before = copy.deepcopy(brief)
    payload = compile_brief(brief)
    assert brief == before
    assert payload['type'] == 'conversation_initiation_client_data'
    agent = payload['conversation_config_override']['agent']
    assert 'AI' in agent['first_message']
    assert agent['language'] == language
    prompt = agent['prompt']['prompt']
    assert agent['first_message'] in prompt
    assert FALLBACK in prompt
    for stop in ('payment', 'deposit', 'card', 'cancellation', 'personal data'):
        assert stop in prompt
    assert 'check_with_owner' in prompt and 'not available' in prompt
    assert '45 seconds' in prompt
    assert 'tools' not in agent['prompt'] and 'tool_ids' not in agent['prompt']
    assert 'custom_llm_extra_body' not in payload


def test_preapproved_choices_and_allowlisted_facts_only():
    brief = card()
    brief.update(session_id='PRIVATE_SESSION', bridge={'secret_route': 'PRIVATE_ROUTE'},
                 private_notes='PRIVATE_NOTES', transcript=['PRIVATE_HISTORY'])
    payload = compile_brief(brief)
    prompt = payload['conversation_config_override']['agent']['prompt']['prompt']
    for text in ('19:00', '18:30–20:00', 'Asia/Seoul', 'Any table type', '"min": 2', '"max": 3'):
        assert text in prompt
    assert payload['dynamic_variables']['pa_allowed_facts'] == '["Name: Example Guest"]'
    assert '+15555550100' not in json.dumps(payload)
    assert 'PRIVATE_' not in json.dumps(payload)
    assert 'pre-approved choices' in prompt
    assert 'not permission to execute a call' in prompt


def test_financial_ceiling_cannot_approve_a_phase_one_deposit():
    brief = card()
    brief['limits']['max_deposit'] = 20000
    prompt = compile_brief(brief)['conversation_config_override']['agent']['prompt']['prompt']
    assert 'deposit: hard stop' in prompt
    assert '20000' not in prompt
    assert FALLBACK in prompt


@pytest.mark.parametrize('change', [
    {'language': 'xx'}, {'purpose': ''}, {'limits': {'party_size_range': {'min': 4, 'max': 2}}},
    {'limits': {'party_size': 4, 'party_size_range': {'min': 1, 'max': 2}}},
    {'may_share': ['password: fixture-private-value']}, {'may_share': ['x' * 1001]},
])
def test_invalid_or_restricted_card_is_refused(change):
    brief = card()
    brief.update(change)
    with pytest.raises(ValueError):
        compile_brief(brief)


def test_pa_call_compile_is_read_only_and_cannot_dial(tmp_path, monkeypatch):
    brief = card()
    result = calls.dispatch(tmp_path, dict(action='prepare', **brief), session_id='fixture-owner')
    assert result['status'] == 'prepared'
    identity = result['call_id']
    before = Ledger(tmp_path).get('action', 'pa:call:' + identity)
    monkeypatch.setattr(calls, 'request', lambda *args: pytest.fail('must not dial or request transport'))
    compiled = calls.dispatch(tmp_path, {'action': 'compile', 'call_id': identity})
    assert compiled['status'] == 'compiled'
    assert compiled['conversation_initiation_client_data'] == compile_brief(result['call_card'])
    assert Ledger(tmp_path).get('action', 'pa:call:' + identity) == before
    for direction in ('inbound', 'outbound'):
        brief['direction'] = direction
        prepared = calls.dispatch(tmp_path, dict(action='prepare', **brief), config={'transport': 'elevenlabs'})
        started = calls.dispatch(tmp_path, {'action': 'start', 'call_id': prepared['call_id'], 'confirmed': True},
                                 config={'transport': 'elevenlabs'})
        assert started['status'] == 'not_activated'
        assert calls.dispatch(tmp_path, {'action': 'status', 'call_id': prepared['call_id']})['status'] == 'prepared'


def test_compile_missing_or_closed_card_is_not_an_authorization(tmp_path):
    assert calls.dispatch(tmp_path, {'action': 'compile', 'call_id': 'a' * 32})['status'] == 'invalid_state'
    assert not (tmp_path / 'state').exists()
    identity = calls.dispatch(tmp_path, dict(action='prepare', **card()))['call_id']
    calls.dispatch(tmp_path, {'action': 'end', 'call_id': identity, 'outcome': 'cancelled', 'summary': 'Declined.'})
    assert calls.dispatch(tmp_path, {'action': 'compile', 'call_id': identity})['status'] == 'invalid_state'


def test_empty_choices_still_require_hard_stops_and_fallback():
    brief = card()
    brief.update(limits={}, may_share=[])
    brief.pop('on_behalf_of')
    payload = compile_brief(brief)
    assert payload['dynamic_variables']['pa_allowed_facts'] == '[]'
    prompt = payload['conversation_config_override']['agent']['prompt']['prompt']
    assert 'absent means not approved' in prompt
    assert FALLBACK in prompt
    assert 'deposit: hard stop' in prompt


@pytest.mark.parametrize('value', ['Visa: 4111111111111111', '4111111111111111',
                                  '4111 1111 1111 1111', '378282246310005',
                                  '4111  1111  1111  1111', '4111\t1111\t1111\t1111',
                                  '4111\u00a01111\u00a01111\u00a01111',
                                  '4111\n1111\n1111\n1111', '４１１１ １１１１ １１１１ １１１１'])
@pytest.mark.parametrize('field', ['may_share', 'on_behalf_of', 'purpose', 'counterpart', 'choices'])
def test_payment_card_values_never_reach_any_compiled_field(value, field):
    brief = card()
    if field == 'may_share':
        brief['may_share'] = [value]
    elif field == 'counterpart':
        brief['to']['name'] = value
    elif field == 'choices':
        brief['limits']['other'] = value
    else:
        brief[field] = value
    with pytest.raises(ValueError, match='restricted'):
        compile_brief(brief)


def test_approved_e164_callback_is_preserved_only_in_exact_allowed_fact():
    brief = card()
    callback = 'Callback number: +1234567890123'
    brief['may_share'] = [callback]
    payload = compile_brief(brief)
    assert callback in payload['dynamic_variables']['pa_allowed_facts']
    assert callback in payload['conversation_config_override']['agent']['prompt']['prompt']
    # Do not let a label embedded in the name or another field become a bypass.
    brief['on_behalf_of'] = callback
    with pytest.raises(ValueError, match='restricted'):
        compile_brief(brief)


def test_callback_label_cannot_launder_a_card_value():
    brief = card()
    brief['may_share'] = ['Callback number: +1234567890123; Visa: 4111111111111111']
    with pytest.raises(ValueError, match='restricted'):
        compile_brief(brief)


@pytest.mark.parametrize('separator', ['  ', '\t', '\u00a0'])
def test_prepare_compile_refuses_formatted_card_name(tmp_path, separator):
    brief = card()
    brief['on_behalf_of'] = separator.join(['4111', '1111', '1111', '1111'])
    result = calls.dispatch(tmp_path, dict(action='prepare', **brief))
    assert result['status'] == 'prepared'
    compiled = calls.dispatch(tmp_path, {'action': 'compile', 'call_id': result['call_id']})
    assert compiled['status'] == 'restricted_content'
    assert compiled['fields'] == ['on_behalf_of']
    assert 'conversation_initiation_client_data' not in compiled


@pytest.mark.parametrize('number', ['378282246310005', '4222222222222'])
def test_callback_label_cannot_launder_checksum_valid_card_number(number):
    brief = card()
    brief['may_share'] = ['Callback number: +' + number]
    with pytest.raises(ValueError, match='restricted'):
        compile_brief(brief)
