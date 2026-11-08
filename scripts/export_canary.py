#!/usr/bin/env python3
"""Read-only M3 scorecard export; JSON goes to stdout, never to the profile."""
import argparse
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from personal_assistant import automation as auto
from personal_assistant.state import Ledger

SECTIONS = ('Done', 'In progress', 'Blocked with questions')


def _status(values):
    return 'fail' if 'fail' in values else 'unproven' if not values or 'unproven' in values else 'pass'


def export(ledger, *, start, days=10, now=None):
    if not ledger.read_only:
        raise ValueError('export requires a read-only Ledger')
    if type(days) is not int or not 1 <= days <= 260:
        raise ValueError('days must be between 1 and 260')
    current = auto._now(now, 'UTC')
    prefs = (ledger.get('action', 'pa:preferences') or {}).get('fields', {})
    try:
        zone = ZoneInfo(prefs.get('timezone', 'UTC'))
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError(f"invalid timezone: {prefs.get('timezone')}") from None
    changed = auto._value_time(prefs.get('schedule_changed_at'), 'UTC')

    def local_date(value):
        moment = auto._value_time(value, 'UTC')
        return moment.astimezone(zone).date().isoformat() if moment else None

    day = dt.date.fromisoformat(start)
    dates = []
    while len(dates) < days:
        if day.weekday() < 5: dates.append(day.isoformat())
        day += dt.timedelta(days=1)
    rows = ledger.list('action')
    fields = {r['action_id']: r['fields'] for r in rows}
    daily = []
    for date in dates:
        note = fields.get('pa:canary:' + date, {})
        slots = auto.routine_slots(ledger, now=current, date=date)
        # The observer's inventory preserves dynamic due/chase occurrences and
        # historical rule state that current preferences cannot reconstruct.
        inventory = note.get('due_occurrences')
        if isinstance(inventory, list):
            slots = list({s['occurrence_id']: s for s in [*slots, *inventory]}.values())
        results = []
        for slot in slots:
            receipt = auto.notification_receipt(ledger, slot['occurrence_id'])
            due = auto._value_time(slot.get('due_at'), 'UTC')
            claimed = auto._value_time((receipt or {}).get('claimed_at'), 'UTC')
            terminal = auto._value_time((receipt or {}).get('receipt_at'), 'UTC')
            historical = isinstance(inventory, list) and any(s['occurrence_id'] == slot['occurrence_id'] for s in inventory)
            if changed and due and due <= changed and not historical:
                status = 'unproven'  # Current clock preferences cannot reconstruct a changed schedule.
            elif not due or not claimed or not terminal:
                status = 'fail' if due and current >= due + dt.timedelta(minutes=60) else 'unproven'
            elif claimed < due or terminal < claimed or claimed > due + dt.timedelta(minutes=5) or terminal > due + dt.timedelta(minutes=60):
                status = 'fail'
            elif receipt.get('state') != 'delivered' or not receipt.get('provider_proof'):
                status = 'unproven'  # unknown is a cron hand-off, not observed delivery.
            else:
                status = 'pass'
            results.append({'occurrence_id': slot['occurrence_id'], 'status': status})
        complete = (note.get('routine_inventory_complete') is True and isinstance(inventory, list)
                    and bool(note.get('evidence_refs')) and date <= local_date(current))
        routine = _status([r['status'] for r in results] + ([] if complete else ['unproven']))
        eod = fields.get('pa:eod:' + date)
        sections = (eod or {}).get('sections', {})
        if not eod:
            eod_status = 'unproven'
        elif not isinstance(sections, dict) or not all(isinstance(sections.get(s), list) and sections[s] for s in SECTIONS):
            eod_status = 'fail'
        elif not all(isinstance(item, str) and item.rstrip().endswith('?')
                     for item in sections['Blocked with questions'] if item != 'None evidenced'):
            eod_status = 'fail'
        elif not eod.get('evidence_refs') or not auto.notification_receipt(ledger, eod.get('occurrence_id', 'missing')):
            eod_status = 'unproven'
        else:
            eod_status = 'pass'
        rescues = note.get('owner_rescues')
        rescue_status = 'unproven' if type(rescues) is not int or rescues < 0 or not note.get('evidence_refs') else 'pass' if rescues == 0 else 'fail'
        daily.append({'date': date, 'routines': routine, 'occurrences': results,
                      'eod': eod_status, 'owner_rescues': rescue_status, 'rescue_count': rescues})
    detections = []
    for identity, value in fields.items():
        if not identity.startswith('pa:routine-health:'): continue
        failed = auto._value_time(value.get('failed_at'), 'UTC')
        detected = auto._value_time(value.get('detected_at'), 'UTC')
        if not failed or local_date(failed) not in dates: continue
        detections.append('unproven' if not detected else
                          'pass' if failed <= detected <= failed + dt.timedelta(minutes=5) else 'fail')
    bumps = {(r['action_id'], c.get('version')) for r in rows if r['action_type'] == 'sop'
             for c in r['fields'].get('changelog', []) if type(c.get('version')) is int and c['version'] > 1
             and local_date(c.get('at')) in dates}
    return {'working_days': dates, 'daily': daily, 'rows': {
        'due_routines_on_time': _status([d['routines'] for d in daily]),
        'eod_three_sections': _status([d['eod'] for d in daily]),
        'broken_routine_within_one_cycle': _status(detections),
        'sop_version_bumps': 'pass' if len(bumps) >= 2 else 'unproven' if not bumps else 'fail',
        'owner_rescues': _status([d['owner_rescues'] for d in daily]),
    }, 'sop_version_bumps': len(bumps), 'read_only': True,
        'not_proven': 'No activation, provider action, rollout approval or customer readiness is established by this export.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--start', required=True, help='first owner-local date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=10)
    args = parser.parse_args(argv)
    try:
        result = export(Ledger(args.root.absolute(), read_only=True), start=args.start, days=args.days)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
