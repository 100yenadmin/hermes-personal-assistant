import datetime as dt
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from personal_assistant import automation as auto
from personal_assistant.automation_workflow import (
    _install_precheck, cron_precheck, dispatch, preferences, prepare_suggestions, script_main,
)
from personal_assistant.state import Ledger

ROOT = Path(__file__).resolve().parents[1]


def at(value):
    return dt.datetime.fromisoformat(value + '+00:00')


def rule(ledger, kind='daily_brief', identity=None, **changes):
    return auto.upsert_automation_rule(ledger, identity or kind, {
        'kind': kind, 'accepted': True, 'timezone': 'UTC',
        'destination': 'fixture-owner', 'destination_verified': True, **changes,
    })


@pytest.fixture
def ledger(tmp_path):
    result = Ledger(tmp_path)
    preferences(result, {'timezone': 'UTC'})
    return result


def test_reporting_contract_and_domain_pointers():
    text = (ROOT / 'skills/personal-assistant/references/reporting.md').read_text()
    for fragment in ('NOT invoked', 'at most one corrected resend', 'never repeat an identical failed call',
                     'After two failures stop', 'current turn', 'scheduled final response',
                     '`problem`', '`options`: 2–3', '`recommendation`', '`decision_deadline`',
                     'plan and ETA first', '8 tool calls or 3 minutes', "owner's yes", 'recipient/channel'):
        assert fragment in text
    for name in ('trip-concierge', 'research', 'restaurant-reservations'):
        pointer = (ROOT / 'skills' / name / 'SKILL.md').read_text()
        assert '`reporting.md` in `../personal-assistant/references/`' in pointer
        assert (ROOT / 'skills' / name / '../personal-assistant/references/reporting.md').is_file()


def test_scheduled_receipt_is_unknown_and_eod_is_evidenced():
    text = (ROOT / 'skills/personal-assistant/r5-brief-reminders/SKILL.md').read_text()
    assert '"receipt":"unknown"' in text and '"receipt":"delivered"' not in text
    for fragment in ('never use a message tool', 'Done / In progress / Blocked with questions',
                     'Every blocked\nitem ends in a question', 'nothing is invented', 'meetings_to_confirm',
                     'attendees_known: false', 'attendees_omitted', 'twice-daily R6', 'pa:eod:', 'gog'):
        assert fragment in text
    cos = (ROOT / 'skills/cos-daily/SKILL.md').read_text()
    assert 'Done / In progress / Blocked with questions' in cos and 'meetings_to_confirm' in cos


def test_separate_brief_and_eod_claims_without_resuggestion(ledger):
    rule(ledger)
    installed = Path(_install_precheck(ledger, 'daily_brief')).read_bytes()
    morning = cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T08:00'))
    assert morning['wakeAgent'] and morning['occurrence_kind'] == 'daily_brief'
    auto.record_notification(ledger, morning['occurrence_id'], 'unknown')
    assert not cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T17:59'))['wakeAgent']
    evening = cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T18:00'))
    assert evening['wakeAgent'] and evening['occurrence_kind'] == 'end_of_day'
    assert evening['occurrence_id'] != morning['occurrence_id']
    assert not cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T18:05'))['wakeAgent']
    with patch('personal_assistant.automation_workflow.cos_enabled', return_value=True):
        assert Path(_install_precheck(ledger, 'daily_brief')).read_bytes() == installed
    prompt = prepare_suggestions(ledger)['jobs'][0]['job_spec']['prompt']
    assert 'end_of_day' in prompt and 'do not invoke the gog collector' in prompt


def test_eod_preference_and_quiet_hours(ledger):
    rule(ledger)
    preferences(ledger, {'eod_time': '23:00'})
    assert auto.DEFAULTS['eod_time'] == '18:00'
    assert not cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T23:00'))['wakeAgent']


@pytest.mark.parametrize('fault,reason', [('zone', 'timezone_conflict'), ('destination', 'destination_conflict')])
def test_broken_rule_health_and_other_routine_wakes_once(ledger, fault, reason):
    rule(ledger)
    rule(ledger, 'due_source_check')
    if fault == 'zone':
        rule(ledger, timezone='broken/zone')
    else:
        rule(ledger, identity='conflict', destination='other-fixture')
    now = at('2026-11-09T08:00')
    assert cron_precheck(ledger, 'daily_brief', enabled=True, moment=now)['reason'] == reason
    health = auto.routine_health(ledger, now=now)
    assert health['findings'][0]['reason'] == reason
    wake = cron_precheck(ledger, 'due_source_check', enabled=True, moment=now + dt.timedelta(minutes=5))
    assert wake['wakeAgent'] and wake['occurrence_kind'] == 'routine_health'
    assert wake['health_findings'][0]['reason'] == reason
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=now + dt.timedelta(minutes=10))['wakeAgent']
    assert ledger.get('action', 'pa:routine-health:daily_brief')['fields']['detected_at']


def test_invalid_profile_timezone_recorded(ledger):
    ledger.put('action', 'pa:preferences', {'timezone': 'broken/zone'})
    rule(ledger, timezone='broken/zone')
    assert cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T08:00'))['reason'] == 'invalid_timezone'
    assert auto.routine_health(ledger)['status'] == 'attention'


@pytest.mark.parametrize('exceptions', [False, True])
def test_health_quiet_hours_need_explicit_exception(ledger, exceptions):
    rule(ledger)
    rule(ledger, identity='conflict', destination='other-fixture')
    rule(ledger, 'due_source_check', quiet_hours_exceptions=exceptions)
    now = at('2026-11-09T23:00')
    cron_precheck(ledger, 'daily_brief', enabled=True, moment=now)
    wake = cron_precheck(ledger, 'due_source_check', enabled=True, moment=now)
    assert wake['wakeAgent'] is exceptions
    if not exceptions: assert wake['reason'] == 'quiet_hours'


def test_missing_receipt_and_slot_health_is_read_only(ledger):
    rule(ledger)
    now = at('2026-11-09T09:00')
    auto.claim_notification(ledger, 'orphan', rule_id='other', now=now - dt.timedelta(hours=1))
    before = ledger.path.read_bytes()
    with patch.object(ledger, 'put', side_effect=AssertionError('health wrote')):
        health = dispatch(ledger, {'action': 'health', 'now': now})
    assert {f['reason'] for f in health['findings']} == {'receipt_missing', 'slot_unclaimed'}
    assert before == ledger.path.read_bytes()
    readonly = Ledger(ledger.root, read_only=True)
    assert auto.routine_health(readonly, now=now) == health
    auto.record_notification(ledger, 'orphan', 'unknown')
    assert 'receipt_missing' not in {f['reason'] for f in auto.routine_health(ledger, now=now)['findings']}


def test_script_exception_retains_health_when_ledger_opens(ledger, monkeypatch, capsys):
    monkeypatch.setenv('HERMES_HOME', str(ledger.root))
    (ledger.root / 'config.yaml').write_text('plugins: [invalid-shape]')
    script_main('daily_brief')
    assert json.loads(capsys.readouterr().out)['reason'] == 'precheck_requires_attention'
    assert ledger.get('action', 'pa:routine-health:daily_brief')['fields']['failed_at']


@pytest.mark.parametrize('key', ['prompt', 'deliver', 'skills'])
def test_job_drift_reports_owner_replacement_without_rewrite(ledger, monkeypatch, key):
    rule(ledger)
    spec = prepare_suggestions(ledger)['jobs'][0]['job_spec']
    old = {**spec, key: [] if key == 'skills' else 'old'}
    monkeypatch.setitem(sys.modules, 'cron.jobs', SimpleNamespace(list_jobs=lambda **_: [old]))
    monkeypatch.setitem(sys.modules, 'cron.suggestions', SimpleNamespace(add_suggestion=lambda **_: pytest.fail('rewrote job')))
    with patch('personal_assistant.automation_workflow.native_profile_guard'):
        job = prepare_suggestions(ledger, native=True)['jobs'][0]
    assert job['suggestion'] == 'job_outdated' and job['drift'] == [key]
    assert 'owner to remove' in job['next_step'] and 'reoffer true' in job['next_step']
    assert old[key] != spec[key]


def loop(ledger, **changes):
    ledger.put('action', 'loop-fixture', {
        'loop_kind': 'waiting_on_them', 'counterparty': 'fixture', 'next_actor': 'them',
        'opened_at': '2026-11-07T08:00:00+00:00', 'next_step': 'Wait for response', **changes,
    }, action_type='commitment')


def test_chase_wakes_once_per_step_and_survives_other_work(ledger):
    rule(ledger, 'due_source_check')
    loop(ledger)
    now = at('2026-11-09T08:00')
    first = cron_precheck(ledger, 'due_source_check', enabled=True, moment=now)
    assert first['wakeAgent'] and first['chase_action_ids'] == ['loop-fixture']
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=now)['wakeAgent']
    ledger.put('action', 'other-work', {'due': True})
    other = cron_precheck(ledger, 'due_source_check', enabled=True, moment=now)
    assert other['wakeAgent'] and other['chase_action_ids'] == []
    second = cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-12T08:00'))
    assert second['wakeAgent'] and second['chase_action_ids'] == ['loop-fixture']
    assert second['occurrence_id'] != first['occurrence_id']


@pytest.mark.parametrize('hold', [
    {'snoozed_until': '2026-11-10T08:00:00+00:00'}, {'waiting_for': 'fixture'},
    {'stale': True},
])
def test_chase_holds_stay_quiet(ledger, hold):
    rule(ledger, 'due_source_check')
    loop(ledger, **hold)
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:00'))['wakeAgent']


def test_chase_requires_accepted_rule_and_obeys_quiet_and_snooze(ledger):
    loop(ledger)
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:00'))['wakeAgent']
    rule(ledger, 'due_source_check')
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T02:00'))['wakeAgent']
    preferences(ledger, {'snooze_until': '2026-11-10T08:00:00+00:00'})
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:00'))['wakeAgent']
    preferences(ledger, {'snooze_until': '2026-11-09T07:00:00+00:00'})
    assert cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:00'))['wakeAgent']


def test_same_failure_after_recovery_is_a_new_health_finding(ledger):
    rule(ledger)
    rule(ledger, 'due_source_check')
    rule(ledger, identity='conflict', destination='other-fixture')
    cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T08:00'))
    first = cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:05'))
    assert first['wakeAgent']
    rule(ledger, identity='conflict')
    assert cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T08:10'))['wakeAgent']
    rule(ledger, identity='conflict', destination='other-fixture')
    cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T08:15'))
    second = cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:20'))
    assert second['wakeAgent']
    assert second['occurrence_id'] != first['occurrence_id']
