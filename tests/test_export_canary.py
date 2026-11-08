import datetime as dt
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from personal_assistant import automation as auto
from personal_assistant.automation_workflow import preferences
from personal_assistant.state import Ledger
from scripts.export_canary import export, main

NOW = dt.datetime.fromisoformat('2026-11-21T12:00:00+00:00')


@pytest.fixture
def canary(tmp_path):
    ledger = Ledger(tmp_path)
    preferences(ledger, {'timezone': 'UTC'})
    auto.upsert_automation_rule(ledger, 'daily_brief', {
        'kind': 'daily_brief', 'accepted': True, 'accepted_at': '2026-11-08T12:00:00+00:00',
        'timezone': 'UTC', 'destination': 'fixture-owner', 'destination_verified': True,
    })
    day = dt.date(2026, 11, 9)
    dates = []
    while len(dates) < 10:
        if day.weekday() < 5: dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    for date in dates:
        for slot in auto.routine_slots(ledger, now=NOW, date=date):
            due = auto._value_time(slot['due_at'], 'UTC')
            auto.claim_notification(ledger, slot['occurrence_id'], now=due + dt.timedelta(minutes=1))
            auto.record_notification(ledger, slot['occurrence_id'], 'delivered',
                                     now=due + dt.timedelta(minutes=2),
                                     proof={'provider': 'synthetic', 'receipt_reference': 'fixture'})
            if slot['logical'].endswith(':eod'):
                ledger.put('action', 'pa:eod:' + date, {
                    'sections': {'Done': ['Fixture completed'], 'In progress': ['None evidenced'],
                                 'Blocked with questions': ['Can you confirm the fixture?']},
                    'occurrence_id': slot['occurrence_id'], 'evidence_refs': ['fixture-source'],
                }, action_type='note')
        ledger.put('action', 'pa:canary:' + date, {
            'routine_inventory_complete': True, 'due_occurrences': [], 'owner_rescues': 0,
            'evidence_refs': ['fixture-observation'],
        }, action_type='note')
    ledger.put('action', 'pa:routine-health:daily_brief', {
        'kind': 'daily_brief', 'reason': 'fixture-break', 'failed_at': dates[0] + 'T12:00:00+00:00',
        'detected_at': dates[0] + 'T12:05:00+00:00',
    }, action_type='routine_health')
    ledger.put('action', 'sop:fixture', {
        'version': 3, 'changelog': [{'version': version, 'at': dates[version] + 'T12:00:00+00:00',
                                   'change': 'Fixture improvement'} for version in (1, 2, 3)],
    }, action_type='sop')
    return ledger


def score(ledger):
    return export(Ledger(ledger.root, read_only=True), start='2026-11-09', now=NOW)


def test_ten_working_days_all_rows_pass_and_no_writes(canary):
    before = canary.path.read_bytes()
    with patch.object(Ledger, 'put', side_effect=AssertionError('export wrote')):
        result = score(canary)
    assert set(result['rows'].values()) == {'pass'}
    assert result['sop_version_bumps'] == 2
    assert len(result['working_days']) == 10
    assert '2026-11-14' not in result['working_days']
    assert result['working_days'][-1] == '2026-11-20'
    assert before == canary.path.read_bytes()


def test_missed_slot_fails_routine_row(canary):
    slot = auto.routine_slots(canary, now=NOW, date='2026-11-11')[0]
    with canary.connect() as conn:
        conn.execute('delete from actions where action_id=?', (auto._notification_action_id(canary, slot['occurrence_id']),))
    assert score(canary)['rows']['due_routines_on_time'] == 'fail'


def test_eod_missing_section_fails_row(canary):
    note = canary.get('action', 'pa:eod:2026-11-11')['fields']
    del note['sections']['In progress']
    canary.put('action', 'pa:eod:2026-11-11', note)
    assert score(canary)['rows']['eod_three_sections'] == 'fail'


def test_late_detection_fails_row(canary):
    canary.put('action', 'pa:routine-health:daily_brief', {'detected_at': '2026-11-09T12:06:00+00:00'})
    assert score(canary)['rows']['broken_routine_within_one_cycle'] == 'fail'


def test_owner_rescue_is_counted_and_fails_row(canary):
    canary.put('action', 'pa:canary:2026-11-11', {'owner_rescues': 1})
    result = score(canary)
    assert result['rows']['owner_rescues'] == 'fail'
    assert sum(d['rescue_count'] for d in result['daily']) == 1


def test_missing_data_is_unproven(tmp_path):
    ledger = Ledger(tmp_path)
    result = score(ledger)
    assert set(result['rows'].values()) == {'unproven'}


def test_cron_handoff_does_not_prove_delivery(canary):
    slot = auto.routine_slots(canary, now=NOW, date='2026-11-11')[0]
    row = canary.get('action', auto._notification_action_id(canary, slot['occurrence_id']))
    canary.put('action', row['action_id'], {'notification_state': 'unknown'}, status='unknown')
    assert score(canary)['rows']['due_routines_on_time'] == 'unproven'


def test_export_refuses_writable_ledger_and_output_path(canary):
    with pytest.raises(ValueError, match='read-only'):
        export(canary, start='2026-11-09')
    with pytest.raises(SystemExit) as exc:
        main([str(canary.root), '--start', '2026-11-09', '--out', str(canary.path)])
    assert exc.value.code == 2


def test_cli_json_stdout(canary, capsys):
    assert main([str(canary.root), '--start', '2026-11-09']) == 0
    assert json.loads(capsys.readouterr().out)['read_only']


def test_observations_use_owner_local_working_dates(canary):
    preferences(canary, {'timezone': 'Asia/Tokyo'})
    canary.put('action', 'pa:routine-health:daily_brief', {
        'failed_at': '2026-11-08T23:00:00+00:00', 'detected_at': '2026-11-08T23:05:00+00:00',
    })  # Monday 08:00 locally, Sunday in UTC.
    canary.put('action', 'sop:fixture', {'changelog': [
        {'version': 2, 'at': '2026-11-08T23:00:00+00:00', 'change': 'Fixture'},
        {'version': 3, 'at': '2026-11-08T23:05:00+00:00', 'change': 'Fixture'},
    ]})
    result = score(canary)
    assert result['rows']['broken_routine_within_one_cycle'] == 'pass'
    assert result['sop_version_bumps'] == 2
