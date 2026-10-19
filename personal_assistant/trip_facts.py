"""Validated local flight observations; no provider or calendar dependencies."""
import datetime as dt
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from .privacy import clean
from .state import now

SOURCES = ['user', 'inbox', 'calendar', 'observer', 'simulated']
SOURCE_RANK = {'user': 3, 'inbox': 2, 'calendar': 1, 'observer': 0, 'simulated': 0}
STATUSES = ['scheduled', 'delayed', 'cancelled', 'departed', 'landed', 'diverted', 'unknown']
SCHEDULE = ('carrier', 'number', 'origin', 'destination', 'origin_timezone', 'destination_timezone',
            'scheduled_departure', 'scheduled_arrival')
OPTIONAL = ('estimated_departure', 'estimated_arrival', 'terminal_departure', 'terminal_arrival')
SEG_SCHEMA = {'type': 'object', 'additionalProperties': False, 'properties': {
    **{k: {'type': 'string', 'pattern': pattern} for k, pattern in {
        'carrier': '^[A-Z0-9]{2,3}$', 'number': r'^\d{1,4}[A-Z]?$',
        'origin': '^[A-Z]{3}$', 'destination': '^[A-Z]{3}$',
        'terminal_departure': '^[A-Za-z0-9 -]{1,8}$', 'terminal_arrival': '^[A-Za-z0-9 -]{1,8}$'}.items()},
    **{k: {'type': 'string'} for k in ('segment_id', 'observed_at', 'origin_timezone', 'destination_timezone',
        'scheduled_departure', 'scheduled_arrival', 'estimated_departure', 'estimated_arrival')},
    'status': {'type': 'string', 'enum': STATUSES}, 'source': {'type': 'string', 'enum': SOURCES}},
    'required': list(SCHEDULE)}


def _time(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('flight times must include a timezone')
    return parsed.astimezone(dt.timezone.utc)


def facts(ledger, trip_id):
    return (ledger.get('action', 'pa:trip-facts:' + trip_id) or {}).get('fields', {})


def record_facts(ledger, trip_id, segments, source, *, observed_at=None, expected_digest=None):
    if source not in SOURCES or not isinstance(segments, list) or not 1 <= len(segments) <= 8:
        raise ValueError('invalid flight source or segments (1-8 required)')
    stamp, incoming = _time(observed_at or now()).isoformat(), []
    for raw in segments:
        if not isinstance(raw, dict) or set(raw) - set(SEG_SCHEMA['properties']) or any(k not in raw for k in SCHEDULE):
            raise ValueError('invalid segment fields')
        seg = {k: v for k, v in raw.items() if k not in {'segment_id', 'source', 'observed_at'}}
        for k, spec in SEG_SCHEMA['properties'].items():
            if k in seg and (not isinstance(seg[k], str) or ('pattern' in spec and not re.fullmatch(spec['pattern'], seg[k]))):
                raise ValueError('invalid segment ' + k)
        for k in ('origin_timezone', 'destination_timezone'):
            ZoneInfo(seg[k])
        for k in ('scheduled_departure', 'scheduled_arrival', 'estimated_departure', 'estimated_arrival'):
            if k in seg:
                seg[k] = _time(seg[k]).isoformat()
        if _time(seg['scheduled_arrival']) < _time(seg['scheduled_departure']):
            raise ValueError('arrival precedes departure')
        seg['status'] = seg.get('status', 'scheduled')
        if seg['status'] not in STATUSES:
            raise ValueError('invalid flight status')
        seg.update(segment_id=seg['carrier'] + seg['number'] + ':' + _time(seg['scheduled_departure']).date().isoformat(),
                   source=source, observed_at=_time(raw.get('observed_at', stamp)).isoformat())
        incoming.append(clean(seg))
    from .trip_watch import _mutate
    changed_fields = set()

    def update(data):
        if expected_digest is not None and data.get('digest') != expected_digest:
            raise ValueError('flight facts digest changed')
        saved = {s['segment_id']: s for s in data.get('segments', [])}
        for seg in incoming:
            old = saved.get(seg['segment_id'])
            if old and _time(seg['observed_at']) < _time(old['observed_at']):
                continue
            merged = {**(old or {}), **seg}
            if old and SOURCE_RANK[old['source']] > SOURCE_RANK[source]:
                merged.update({k: old[k] for k in SCHEDULE})
                merged['source'] = old['source']
            changed_fields.update(k for k in (*SCHEDULE, *OPTIONAL, 'status') if merged.get(k) != (old or {}).get(k))
            saved[seg['segment_id']] = merged
        if len(saved) > 8:
            raise ValueError('at most 8 flight segments')
        ordered = sorted(saved.values(), key=lambda s: s['scheduled_departure'])
        material = [{k: v for k, v in s.items() if k not in {'observed_at', 'source'}} for s in ordered]
        digest = hashlib.sha256(json.dumps(clean(material), sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        changed = digest != data.get('digest')
        data.update(schema=1, segments=ordered, digest=digest, revision=data.get('revision', 0) + int(changed),
                    history=(data.get('history', []) + [{'digest': digest, 'source': source, 'observed_at': stamp}])[-20:])
    data = _mutate(ledger, 'pa:trip-facts:' + trip_id, update)
    return {'trip_id': trip_id, 'digest': data['digest'], 'revision': data['revision'],
            'changed': bool(changed_fields), 'material': sorted(changed_fields), 'segments': data['segments']}
