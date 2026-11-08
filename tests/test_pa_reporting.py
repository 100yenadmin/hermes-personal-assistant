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


@pytest.mark.parametrize('legacy', [False, True])
def test_unreceipted_health_wake_never_recurses(ledger, legacy):
    rule(ledger, 'due_source_check')
    ledger.put('action', 'pa:routine-health:daily_brief', {
        'kind': 'daily_brief', 'reason': 'timezone_conflict',
        'failed_at': '2026-11-09T08:00:00+00:00',
    }, action_type='routine_health')
    wake = cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:00'))
    assert wake['wakeAgent'] and wake['occurrence_kind'] == 'routine_health'
    claim_id = auto._notification_action_id(ledger, wake['occurrence_id'])
    if legacy:
        ledger.put('action', claim_id, {}, remove=['routine_kind'])
        auto.claim_notification(ledger, 'legacy-health-2', rule_id='routine-health', now=at('2026-11-09T08:00'))
    else:
        assert ledger.get('action', claim_id)['fields']['routine_kind'] == 'routine-health'
    for hour in ('09', '10'):
        now = at(f'2026-11-09T{hour}:00')
        assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=now)['wakeAgent']
        assert not any(f['reason'] == 'receipt_missing' for f in auto.routine_health(ledger, now=now)['findings'])


def test_snoozed_daily_brief_has_no_false_slot_alarm_and_gets_grace(ledger):
    rule(ledger, snooze_until='2026-11-09T20:00:00+00:00')
    rule(ledger, 'due_source_check')
    now = at('2026-11-09T09:00')
    assert cron_precheck(ledger, 'daily_brief', enabled=True, moment=now)['reason'] == 'routine_snoozed'
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=now)['wakeAgent']
    for time in ('20:00', '20:05', '20:59'):
        assert auto.routine_health(ledger, now=at('2026-11-09T' + time))['findings'] == []
    assert any(f['reason'] == 'slot_unclaimed' for f in auto.routine_health(ledger, now=at('2026-11-09T21:00'))['findings'])


def test_snooze_ending_after_eod_does_not_expect_unclaimable_morning_slot(ledger):
    rule(ledger, snooze_until='2026-11-09T20:00:00+00:00')
    rule(ledger, 'due_source_check')
    wake = cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T20:00'))
    assert wake['wakeAgent'] and wake['occurrence_kind'] == 'end_of_day'
    auto.record_notification(ledger, wake['occurrence_id'], 'unknown', now=at('2026-11-09T20:01'))
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T21:00'))['wakeAgent']


@pytest.mark.parametrize('scope', ['profile', 'rule'])
def test_paused_routine_resume_gets_grace(ledger, scope):
    rule(ledger)
    if scope == 'profile':
        preferences(ledger, {'paused': True})
    else:
        rule(ledger, paused=True)
    assert auto.routine_health(ledger, now=at('2026-11-09T09:00'))['findings'] == []
    with patch.object(auto, '_now', return_value=at('2026-11-09T09:00')):
        if scope == 'profile':
            preferences(ledger, {'paused': False})
        else:
            rule(ledger, paused=False)
    assert auto.routine_health(ledger, now=at('2026-11-09T09:05'))['findings'] == []
    assert auto.routine_health(ledger, now=at('2026-11-09T10:00'))['findings']


def test_quiet_end_and_unverified_destination_slot_eligibility(ledger):
    rule(ledger, destination_verified=False)
    assert auto.routine_slots(ledger, now=at('2026-11-09T09:00')) == []
    rule(ledger)
    preferences(ledger, {'quiet_hours': {'start': '22:00', 'end': '09:00'}})
    for time in ('08:30', '09:00', '09:05', '09:59'):
        assert auto.routine_health(ledger, now=at('2026-11-09T' + time))['findings'] == []
    assert auto.routine_health(ledger, now=at('2026-11-09T10:00'))['findings']


def test_public_health_missing_ledger_is_read_only(tmp_path):
    from personal_assistant.entry import dispatch as public_dispatch
    with patch('personal_assistant.entry.Ledger', wraps=Ledger) as constructor:
        result = public_dispatch(tmp_path, {'operation': 'automations', 'data': {'action': 'health'}})
    constructor.assert_called_once_with(tmp_path, read_only=True)
    assert result['status'] == 'no ledger yet' and result['read_only']
    assert list(tmp_path.iterdir()) == []


def test_public_health_existing_ledger_uses_read_only_connection(ledger):
    from personal_assistant.entry import dispatch as public_dispatch
    before = ledger.path.read_bytes()
    original = Ledger.connect
    def readonly_connect(self):
        assert self.read_only
        return original(self)
    with patch.object(Ledger, 'connect', readonly_connect):
        assert public_dispatch(ledger.root, {'operation': 'automations', 'data': {'action': 'health'}})['read_only']
    assert ledger.path.read_bytes() == before


def test_brief_time_rejects_bad_input_and_stored_value_is_health_finding(ledger):
    with pytest.raises(ValueError, match='brief_time must be HH:MM'):
        preferences(ledger, {'brief_time': '8:00'})
    ledger.put('action', 'pa:preferences', {'brief_time': '8:00'})
    rule(ledger)
    rule(ledger, 'due_source_check')
    now = at('2026-11-09T09:00')
    health = dispatch(ledger, {'action': 'health', 'now': now})
    assert any(f['reason'] == 'invalid_brief_time' for f in health['findings'])
    assert cron_precheck(ledger, 'daily_brief', enabled=True, moment=now)['reason'] == 'invalid_brief_time'
    due = cron_precheck(ledger, 'due_source_check', enabled=True, moment=now)
    assert due['wakeAgent'] and due['health_findings'][0]['reason'] == 'invalid_brief_time'


def test_escalate_step_is_reported_without_a_separate_wake():
    text = (ROOT / 'skills/personal-assistant/r5-brief-reminders/SKILL.md').read_text()
    assert '`escalate`' in text and 'daily brief or radar' in text and 'no separate wake' in text


def test_missed_brief_is_reported_during_later_quiet_hours(ledger):
    rule(ledger)
    findings = auto.routine_health(ledger, now=at('2026-11-09T23:00'))['findings']
    assert any(f['reason'] == 'slot_unclaimed' and f['kind'] == 'daily_brief' for f in findings)


@pytest.mark.parametrize('where', ['rule', 'stored_preference'])
def test_unreadable_snooze_is_a_finding_not_a_silent_hold(ledger, where):
    if where == 'rule':
        rule(ledger, snooze_until='later')
    else:
        rule(ledger)
        ledger.put('action', 'pa:preferences', {'snooze_until': 'later'})
    health = auto.routine_health(ledger, now=at('2026-11-09T09:00'))
    assert health['status'] == 'attention'
    assert [f['reason'] for f in health['findings'] if f.get('kind') == 'daily_brief'].count('invalid_snooze') == 1
    if where == 'rule':
        wake = cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T09:00'))
        assert wake == {'wakeAgent': False, 'reason': 'invalid_snooze'}


def test_unreadable_stored_quiet_hours_is_a_finding(ledger):
    rule(ledger)
    ledger.put('action', 'pa:preferences', {'quiet_hours': {'start': '22:00', 'end': '7:00'}})
    findings = auto.routine_health(ledger, now=at('2026-11-09T09:00'))['findings']
    assert any(f['reason'] == 'invalid_quiet_hours' for f in findings)


@pytest.mark.parametrize('changes', [{'snooze_until': 'tomorrow'}, {'quiet_hours': {'start': '22:00', 'end': '7:00'}},
                                     {'quiet_hours': 'nights'}])
def test_preferences_reject_unreadable_holds(ledger, changes):
    with pytest.raises(ValueError):
        preferences(ledger, changes)


def test_clearing_a_snooze_is_allowed(ledger):
    preferences(ledger, {'snooze_until': '2026-11-09T20:00:00+00:00'})
    assert preferences(ledger, {'snooze_until': None}).get('snooze_until') is None


@pytest.mark.parametrize('scope', ['profile', 'rule'])
def test_clearing_a_running_snooze_restarts_grace(ledger, scope):
    rule(ledger, 'due_source_check')
    if scope == 'profile':
        rule(ledger)
        preferences(ledger, {'snooze_until': '2026-11-09T20:00:00+00:00'})
    else:
        rule(ledger, snooze_until='2026-11-09T20:00:00+00:00')
    with patch.object(auto, '_now', return_value=at('2026-11-09T09:30')):
        if scope == 'profile':
            preferences(ledger, {'snooze_until': None})
        else:
            rule(ledger, snooze_until=None)
    for time in ('09:30', '10:00', '10:29'):
        assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T' + time))['wakeAgent']
        assert auto.routine_health(ledger, now=at('2026-11-09T' + time))['findings'] == []
    assert any(f['reason'] == 'slot_unclaimed' for f in auto.routine_health(ledger, now=at('2026-11-09T10:30'))['findings'])


def test_moving_a_snooze_later_or_clearing_an_expired_one_stamps_no_resume(ledger):
    with patch.object(auto, '_now', return_value=at('2026-11-09T09:30')):
        preferences(ledger, {'snooze_until': '2026-11-09T20:00:00+00:00'})
        assert 'routine_resumed_at' not in preferences(ledger, {'snooze_until': '2026-11-09T21:00:00+00:00'})
    ledger.put('action', 'pa:preferences', {'snooze_until': '2026-11-09T09:00:00+00:00'})
    with patch.object(auto, '_now', return_value=at('2026-11-09T09:40')):
        assert 'routine_resumed_at' not in preferences(ledger, {'snooze_until': None})


def test_clearing_an_offsetless_snooze_restarts_grace_in_owner_zone(tmp_path):
    ledger = Ledger(tmp_path)
    preferences(ledger, {'timezone': 'America/Los_Angeles'})
    rule(ledger, timezone='America/Los_Angeles')
    rule(ledger, 'due_source_check', timezone='America/Los_Angeles')
    ledger.put('action', 'pa:preferences', {'snooze_until': '2026-11-09T10:00'})
    with patch.object(auto, '_now', return_value=at('2026-11-09T17:30')):
        assert preferences(ledger, {'snooze_until': None})['routine_resumed_at'] == '2026-11-09T17:30:00+00:00'
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T17:30'))['wakeAgent']


def _old_due_occurrence(ledger, due):
    """The due-source identity a profile claimed before chase wakes existed."""
    from personal_assistant import automation_workflow as wf
    rules = [auto._rule_data(a) for a in ledger.list('action') if a['action_type'] == 'automation_rule']
    logical = wf.stable_id([(a, ledger.get('action', a)['fields'].get('due_at')) for a in due],
                           [(r.get('source_ref'), r.get('last_checked_at')) for r in rules])
    return auto.routine_occurrence('due_source_check', logical, rules)


def test_due_identity_keeps_its_shape_when_no_chase_is_due(ledger):
    rule(ledger, 'due_source_check')
    ledger.put('action', 'rem', {'due_at': '2026-11-09T07:00:00+00:00'})
    auto.claim_notification(ledger, _old_due_occurrence(ledger, ['rem']), rule_id='due_source_check')
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:00'))['wakeAgent']


def test_a_chase_tick_also_settles_the_same_due_work(ledger):
    rule(ledger, 'due_source_check')
    loop(ledger)
    ledger.put('action', 'rem', {'due_at': '2026-11-09T07:00:00+00:00'})
    first = cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:00'))
    assert first['wakeAgent'] and first['due_action_ids'] == ['rem'] and first['chase_action_ids'] == ['loop-fixture']
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:05'))['wakeAgent']


@pytest.mark.parametrize('extra, wakes', [
    ({}, True), ({'waiting_for': 'fixture'}, False), ({'snoozed_until': '2026-11-10T08:00:00+00:00'}, False),
    ({'confirmation': {'by': 'fixture', 'at': '2026-11-09T11:00:00+00:00', 'evidence': 'reply'}}, False),
])
def test_an_open_loop_with_its_own_deadline_still_wakes(ledger, extra, wakes):
    rule(ledger, 'due_source_check')
    loop(ledger, loop_kind='our_promise', next_actor='us', opened_at='2026-11-09T08:00:00+00:00',
         due_at='2026-11-09T12:00:00+00:00', **extra)
    result = cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T12:00'))
    assert bool(result['wakeAgent']) is wakes
    if wakes:
        assert result['due_action_ids'] == ['loop-fixture']


def test_an_evening_brief_is_not_replaced_by_the_default_end_of_day(ledger):
    preferences(ledger, {'brief_time': '20:00'})
    rule(ledger)
    assert cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T18:00'))['reason'] == 'before_brief_time'
    brief = cron_precheck(ledger, 'daily_brief', enabled=True, moment=at('2026-11-09T20:00'))
    assert brief['wakeAgent'] and brief['occurrence_kind'] == 'daily_brief'
    assert [s['logical'] for s in auto.routine_slots(ledger, now=at('2026-11-09T21:30'))] == ['2026-11-09']
    preferences(ledger, {'brief_time': '08:00', 'eod_time': '18:00'})
    assert auto.eod_clock(preferences(ledger)) == '18:00'


def test_a_chase_tick_also_settles_due_sources(ledger):
    rule(ledger, 'due_source_check', source_ref='src-1', last_checked_at='2026-11-08T00:00:00+00:00')
    loop(ledger)
    first = cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:00'))
    assert first['wakeAgent'] and first['chase_action_ids'] == ['loop-fixture']
    assert not cron_precheck(ledger, 'due_source_check', enabled=True, moment=at('2026-11-09T08:05'))['wakeAgent']
