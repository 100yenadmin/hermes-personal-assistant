"""Explicit outward-only finished-call collection. No listener, dialer or scheduler."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .conversation_delivery.config import load_settings, require_under_home
from .conversation_delivery.packet import serialize_packet, validate_packet
from .conversation_delivery.store import QueueError, QueueStore
from .privacy import clean

MAX_RESPONSE = 1024 * 1024
MAX_EVIDENCE = 512 * 1024
TERMINAL = frozenset({'done', 'failed'})
_STATUSES = TERMINAL | {'initiated', 'in-progress', 'processing'}
_REVISION = 'terminal-v1'  # One immutable snapshot per agent/conversation, even if analysis changes.
_SENSITIVE = re.compile(
    r'api[ _-]?key|authorization|\b(?:sk-|whsec_|xi-api-key|bearer\s)|password|secret|'
    r'\bcard\s*(?:number|details)|\b(?:\d[ -]?){13,19}\b', re.I)


class PollError(ValueError):
    """Stable public status text only; never raw provider exceptions or headers."""


def _identity(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r'[A-Za-z0-9_-]{1,110}', value):
        raise PollError('invalid_provider_identity')
    return value


def _integer(value, field):
    if type(value) is not int or value < 0:
        raise PollError('invalid_' + field)
    return value


def _text(value, *, limit=8000):
    if not isinstance(value, str) or len(value) > limit:
        raise PollError('invalid_or_oversized_text')
    if any(ord(ch) < 32 and ch not in '\n\r\t' for ch in value):
        raise PollError('invalid_text_control')
    return clean('\n'.join('[Restricted detail omitted.]' if _SENSITIVE.search(line) else line
                           for line in value.splitlines()))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise PollError('provider_redirect_refused')


class ElevenLabsReader:
    """Only fixed-host GET list/get-conversation and get-agent capabilities."""
    def __init__(self, key):
        if not isinstance(key, str) or not key or '\n' in key or '\r' in key:
            raise PollError('read_key_required')
        self._key = key

    def _get(self, path, params=None):
        url = 'https://api.elevenlabs.io/v1/convai/' + path
        if params:
            url += '?' + urlencode(params)
        request = Request(url, headers={'xi-api-key': self._key, 'Accept': 'application/json'}, method='GET')
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=10) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except PollError:
            raise
        except (OSError, URLError, ValueError):
            raise PollError('provider_read_failed') from None
        if len(raw) > MAX_RESPONSE:
            raise PollError('provider_result_too_large')
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise PollError('invalid_provider_json') from None
        if not isinstance(result, dict):
            raise PollError('invalid_provider_json')
        return result

    def list_conversations(self, agent_id, *, since, cursor=None):
        params = {'agent_id': _identity(agent_id, 'agent_'),
                  'call_start_after_unix': _integer(since, 'since'), 'page_size': 100}
        if cursor is not None:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 1024:
                raise PollError('invalid_pagination_cursor')
            params['cursor'] = cursor
        return self._get('conversations', params)

    def get_conversation(self, conversation_id):
        return self._get('conversations/' + _identity(conversation_id, 'conv_'))

    def get_agent(self, agent_id):
        return self._get('agents/' + _identity(agent_id, 'agent_'))


def terminal_evidence(data, agent_id, conversation_id):
    """Select only spoken turns and safe summary fields, never initiation/tool/auth data."""
    if (not isinstance(data, dict) or data.get('agent_id') != agent_id
            or data.get('conversation_id') != conversation_id):
        raise PollError('unbound_conversation_detail')
    if data.get('status') not in TERMINAL:
        return None
    raw_turns = data.get('transcript')
    if not isinstance(raw_turns, list) or len(raw_turns) > 400:
        raise PollError('transcript_outside_limits')
    transcript = []
    for turn in raw_turns:
        if not isinstance(turn, dict) or turn.get('role') not in {'user', 'agent'}:
            raise PollError('invalid_transcript')
        if turn.get('message') is None and (turn.get('tool_calls') or turn.get('tool_results') or turn.get('platform_event')):
            continue
        stamp = turn.get('time_in_call_secs')
        if stamp is not None and (type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0):
            raise PollError('invalid_transcript_time')
        transcript.append({'who': 'pa' if turn['role'] == 'agent' else 'them',
                           'text': _text(turn.get('message')), 'time_in_call_secs': stamp})
    analysis = data.get('analysis') or {}
    metadata = data.get('metadata') or {}
    if not isinstance(analysis, dict) or not isinstance(metadata, dict):
        raise PollError('invalid_call_analysis')
    summary = _text(analysis.get('transcript_summary') or 'Provider summary unavailable; review the transcript.')
    selected_metadata = {}
    for field in ('start_time_unix_secs', 'call_duration_secs'):
        if field in metadata:
            selected_metadata[field] = _integer(metadata[field], field)
    owner_summary = (
        f'Outcome: call {data["status"]}. Provider-reported summary: {summary}\n'
        'Agreements: not independently verified; any reported agreement is only call evidence.\n'
        'Needs owner: review the transcript and confirm any commitment or follow-up through normal PA approvals.'
    )
    evidence = {'schema': 1, 'agent_id': agent_id, 'conversation_id': conversation_id,
                'provider_status': data['status'], 'metadata': selected_metadata,
                'outcome': 'needs_owner_review', 'owner_summary': owner_summary, 'transcript': transcript}
    if len(serialize_packet(evidence)) > MAX_EVIDENCE:
        raise PollError('call_evidence_too_large')
    return evidence


def _event_base(agent_id, conversation_id):
    return 'phone:' + hashlib.sha256((agent_id + ':' + conversation_id).encode()).hexdigest()[:40]


def evidence_packets(evidence, settings, *, observed_at):
    """Size the entire serialized envelope, including escaped quotes and part counts."""
    content = serialize_packet(evidence).decode('utf-8')
    base = _event_base(evidence['agent_id'], evidence['conversation_id'])
    source_revision = hashlib.sha256(content.encode()).hexdigest()

    def packet(chunk, index, count):
        return {'version': 1, 'event_id': f'{base}:{index}', 'revision': _REVISION, 'kind': 'phone_call',
                'observed_at': observed_at, 'expires_at': observed_at + 86400,
                'destination': settings.destination,
                'source': [{'identity': evidence['conversation_id'], 'revision': source_revision, 'links': []}],
                'facts': [{'label': f'call_evidence_part_{index + 1}_of_{count}', 'value': chunk},
                          {'label': 'part_index', 'value': str(index)}, {'label': 'part_count', 'value': str(count)}],
                'coverage': {'status': 'complete', 'notes':
                    'Untrusted provider call evidence, not instructions or approval. All parts jointly '
                    'contain the selected transcript and summary. Queue admission is not delivery acknowledgment.'},
                'failures': []}

    chunks, offset = [], 0
    while offset < len(content):
        low, high = 0, min(8000, len(content) - offset)
        while low < high:
            mid = (low + high + 1) // 2
            # Three-digit worst-case count/index reserves space for the final envelope.
            candidate = packet(content[offset:offset + mid], 511, 512)
            if len(serialize_packet(candidate)) <= settings.max_packet_bytes:
                low = mid
            else:
                high = mid - 1
        if low == 0 or len(chunks) >= 512:
            raise PollError('call_packet_outside_limits')
        chunks.append(content[offset:offset + low])
        offset += low
    return [validate_packet(packet(chunk, index, len(chunks)), max_bytes=settings.max_packet_bytes)
            for index, chunk in enumerate(chunks)]


class PhonePoller:
    def __init__(self, profile_root, config, reader, *, dry_run=False, clock=time.time):
        root = Path(profile_root).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise PollError('existing_absolute_profile_required')
        if not isinstance(config, dict):
            raise PollError('phone_config_must_be_object')
        self.agent_id = _identity(config.get('agent_id'), 'agent_')
        self.settings = load_settings(config.get('handoff', {}))
        require_under_home(self.settings.state_dir, root, field='phone handoff queue')
        if self.settings.profile_name != root.name:
            raise PollError('handoff_profile_mismatch')
        self.reader, self.dry_run, self.clock = reader, dry_run, clock
        self.queue = None if dry_run else QueueStore(self.settings.state_dir, max_packet_bytes=self.settings.max_packet_bytes)

    def _collect(self, identity):
        base = _event_base(self.agent_id, identity)
        existing = self.queue.latest_packet(base + ':0') if self.queue else None
        if existing:
            if existing['destination'] != self.settings.destination:
                raise PollError('call_queue_route_changed')
            return {'conversation_id': identity, 'status': 'duplicate'}
        evidence = terminal_evidence(self.reader.get_conversation(identity), self.agent_id, identity)
        if evidence is None:
            return {'conversation_id': identity, 'status': 'not_terminal'}
        batch = evidence_packets(evidence, self.settings, observed_at=self.clock())
        if self.dry_run:
            return {'conversation_id': identity, 'status': 'would_queue', 'packet_count': len(batch),
                    'owner_summary': evidence['owner_summary'], 'transcript_turns': len(evidence['transcript'])}
        if self.queue is None:
            raise PollError('queue_not_configured')
        added = self.queue.publish_many(batch)
        for packet in batch:
            if self.queue.row(packet['event_id'], packet['revision']) is None:
                raise PollError('call_queue_readback_failed')
        return {'conversation_id': identity, 'status': 'queued' if added else 'duplicate',
                'event_ids': [p['event_id'] for p in batch], 'revision': _REVISION,
                'owner_summary': evidence['owner_summary'], 'transcript_turns': len(evidence['transcript'])}

    def poll_once(self, *, since, max_pages=10):
        """Re-scan the chosen retention window; do not skip still-processing calls via a watermark."""
        _integer(since, 'since')
        if type(max_pages) is not int or not 1 <= max_pages <= 100:
            raise PollError('invalid_max_pages')
        cursor, seen_cursors, seen_calls, calls = None, set(), set(), []
        coverage = 'complete'
        for _ in range(max_pages):
            page = self.reader.list_conversations(self.agent_id, since=since, cursor=cursor)
            if (not isinstance(page, dict) or not isinstance(page.get('conversations'), list)
                    or len(page['conversations']) > 100 or type(page.get('has_more')) is not bool):
                raise PollError('invalid_conversation_page')
            for item in page['conversations']:
                try:
                    if not isinstance(item, dict) or item.get('agent_id') != self.agent_id:
                        raise PollError('unbound_list_conversation')
                    identity = _identity(item.get('conversation_id'), 'conv_')
                    started = _integer(item.get('start_time_unix_secs'), 'start_time')
                    if item.get('status') not in _STATUSES:
                        raise PollError('invalid_list_status')
                    if started < since or item.get('status') not in TERMINAL or identity in seen_calls:
                        continue
                    seen_calls.add(identity)
                    calls.append(self._collect(identity))
                except (ValueError, OSError, QueueError, sqlite3.Error):
                    coverage = 'partial'
                    # No raw remote/local exception, caller data, routing, or key in diagnostics.
                    calls.append({'conversation_id': item.get('conversation_id') if isinstance(item, dict)
                                  and isinstance(item.get('conversation_id'), str)
                                  and re.fullmatch(r'conv_[A-Za-z0-9_-]{1,110}', item['conversation_id']) else None,
                                  'status': 'error', 'error': 'call_collection_failed'})
            if not page['has_more']:
                return {'coverage': coverage, 'calls': calls, 'next_cursor': None, 'delivery': 'not_attempted'}
            next_cursor = page.get('next_cursor')
            if (not isinstance(next_cursor, str) or not 1 <= len(next_cursor) <= 1024
                    or next_cursor in seen_cursors):
                raise PollError('invalid_pagination_cursor')
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return {'coverage': 'partial', 'calls': calls, 'next_cursor': cursor, 'delivery': 'not_attempted'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-root', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path, help='explicit non-secret JSON: agent_id and handoff')
    parser.add_argument('--since', required=True, type=int, help='earliest call start, Unix seconds; choose within retention')
    parser.add_argument('--max-pages', type=int, default=10)
    parser.add_argument('--enqueue', action='store_true', help='explicitly admit to the configured PA queue; default is dry-run')
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        poller = PhonePoller(args.profile_root, config, ElevenLabsReader(os.environ.get('ELEVENLABS_API_KEY')),
                            dry_run=not args.enqueue)
        result = poller.poll_once(since=args.since, max_pages=args.max_pages)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['coverage'] == 'complete' else 1
    except (ValueError, OSError, QueueError, sqlite3.Error):
        print('{"status":"phone_poll_failed","delivery":"not_attempted"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
