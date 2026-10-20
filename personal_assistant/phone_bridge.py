"""Opt-in, one-card inbound ElevenLabs bridge. Importing starts no service.

The owner approves a message-taking brief with pa_call; a separate operator-run
HTTP adapter binds it to exactly one provider conversation. No dial capability.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import time
import uuid

from .conversation_delivery.config import load_settings, require_under_home
from .conversation_delivery.store import QueueStore
from .privacy import clean
from .state import now

_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
_SENSITIVE = re.compile(r'api[ _-]?key|authorization|\b(?:sk-|whsec_|xi-api-key|bearer\s)|password|secret|token', re.I)
_DISCLOSURE = {
    'en': 'Hello, I am an AI assistant. I can take a message, but cannot approve changes or payments.',
    'ja': 'AIアシスタントです。伝言を承りますが、変更や支払いは承認できません。',
    'ko': 'AI 비서입니다. 메시지는 전달할 수 있지만 변경이나 결제는 승인할 수 없습니다.',
}


class BridgeError(ValueError):
    """Public errors contain only stable status text, never provider exceptions."""


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def safe_text(text):
    if not isinstance(text, str):
        raise BridgeError('invalid_text')
    return clean('\n'.join('[Restricted detail omitted.]' if _SENSITIVE.search(line) else line
                           for line in text.splitlines()))


def bridge_setup(ledger, config):
    """Bind non-secret route material at prepare, not after the owner's yes."""
    agent = config.get('agent_id', '')
    if not isinstance(agent, str) or not _ID.fullmatch(agent) or not agent.startswith('agent_'):
        raise ValueError('exact staging agent required')
    settings = load_settings(config['handoff'])
    require_under_home(settings.state_dir, ledger.root, field='phone handoff queue')
    if settings.profile_name != ledger.root.name:
        raise ValueError('handoff profile must own the call ledger')
    handoff = {'state_dir': str(settings.state_dir), 'route': {
        'source': 'existing-host-session', 'verified': True, 'profile_name': settings.profile_name,
        'namespace': settings.namespace, 'destination': settings.destination,
        'allowlist': [settings.destination]}, 'poll_interval_seconds': settings.poll_interval_seconds}
    return {'agent_id': agent, 'handoff': handoff}


def update_record(ledger, call_id, operation):
    with ledger.connect() as conn:
        conn.execute('begin immediate')
        row = conn.execute('select * from actions where action_id=?', ('pa:call:' + call_id,)).fetchone()
        if not row or row['action_type'] != 'call':
            raise BridgeError('call_not_found')
        record = json.loads(row['fields_json'])
        result = operation(record)
        conn.execute('update actions set status=?,fields_json=?,updated_at=? where action_id=?',
                     (record['status'], json.dumps(clean(record), ensure_ascii=False), now(), row['action_id']))
        return result


def cancel_armed(ledger, call_id, summary):
    def cancel(record):
        if record['status'] != 'armed':
            return {'status': 'invalid_state'}
        record.update(status='ended', outcome='cancelled', summary=summary, ended_at=now())
        return clean(record.copy())
    return update_record(ledger, call_id, cancel)


def arm(ledger, record, config):
    """Called only after pa_call's prepared-card + confirmed gate."""
    brief = record['brief']
    if (record['status'] != 'prepared' or record['direction'] != 'inbound'
            or brief['may_share'] or brief['limits'].get('max_deposit') != 0
            or brief.get('on_behalf_of') or not re.fullmatch(r'\+[1-9][0-9]{7,14}', brief['to'].get('number', ''))):
        raise ValueError('bridge supports only an approved inbound message-taking card')
    setup = bridge_setup(ledger, config)
    if setup != record.get('bridge_plan') or digest(brief) != record.get('brief_digest'):
        raise ValueError('bridge route or brief changed; prepare a new card')
    def activate(current):
        if current['status'] != 'prepared' or current.get('brief_digest') != record['brief_digest']:
            raise BridgeError('card_already_consumed')
        current.update(status='armed', transport='elevenlabs', bridge_agent_id=setup['agent_id'],
                       bridge_handoff=setup['handoff'], armed_at=now())
        return {'status': 'armed', 'call_id': current['call_id'],
                'note': 'One inbound conversation authorized; no call placed and no service started.'}
    return update_record(ledger, record['call_id'], activate)


def verify_signature(raw, header, secret, *, clock=time.time, tolerance=300):
    """HMAC over the exact timestamp + '.' + body; reject past AND future replays."""
    try:
        pairs = [part.strip().split('=', 1) for part in header.split(',')]
        stamps = [value for key, value in pairs if key == 't']
        if len(stamps) != 1:
            raise ValueError
        stamp = stamps[0]
        if abs(clock() - int(stamp)) > tolerance:
            raise ValueError
        expected = hmac.new(secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, value) for key, value in pairs if key == 'v0'):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise BridgeError('invalid_signature') from None


class Bridge:
    def __init__(self, ledger, call_id, brain):
        if not re.fullmatch(r'[a-f0-9]{32}', call_id):
            raise ValueError('invalid call identity')
        self.ledger, self.call_id, self.brain = ledger, call_id, brain
        record = self.record()
        if record.get('transport') != 'elevenlabs' or record['status'] not in {'armed', 'active', 'ended'}:
            raise ValueError('approved bridge card required')
        self.settings = load_settings(record['bridge_handoff'])
        require_under_home(self.settings.state_dir, ledger.root, field='phone handoff queue')
        self.queue = QueueStore(self.settings.state_dir)

    def record(self):
        row = self.ledger.get('action', 'pa:call:' + self.call_id)
        if not row or row['action_type'] != 'call':
            raise BridgeError('call_not_found')
        return row['fields']

    def change(self, operation):
        """All provider/turn transitions are atomic across bridge processes."""
        return update_record(self.ledger, self.call_id, operation)

    @staticmethod
    def _init_response(record):
        return {'type': 'conversation_initiation_client_data',
                'custom_llm_extra_body': {'conversation_id': record['conversation_id']},
                'conversation_config_override': {'agent': {
                    'first_message': record['brief']['disclosure'], 'language': record['brief']['language']}}}

    def initiate(self, data):
        def bind(record):
            conv, sid = data.get('conversation_id', ''), data.get('call_sid', '')
            if (data.get('agent_id') != record['bridge_agent_id']
                    or data.get('called_number') != record['brief']['to']['number']
                    or not isinstance(conv, str) or not _ID.fullmatch(conv) or not conv.startswith('conv_')
                    or not isinstance(sid, str) or not re.fullmatch(r'CA[a-fA-F0-9]{32}', sid)):
                raise BridgeError('unapproved_inbound_route')
            if record['status'] != 'armed':
                if record['status'] == 'active' and record.get('conversation_id') == conv and record.get('call_sid') == sid:
                    return self._init_response(record)
                raise BridgeError('card_already_consumed')
            # Caller ID is intentionally not authenticated, stored, or used as authority.
            record.update(status='active', conversation_id=conv, call_sid=sid, started_at=now(),
                          turn_count=1,
                          transcript=[{'who': 'pa', 'text': record['brief']['disclosure'], 'at': now()}],
                          brain_receipts=[])
            return self._init_response(record)
        return self.change(bind)

    def turn(self, data):
        messages = data.get('messages')
        extra = data.get('elevenlabs_extra_body')
        if (not isinstance(messages, list) or not 1 <= len(messages) <= 100
                or not all(isinstance(m, dict) for m in messages)
                or not isinstance(extra, dict) or extra.get('conversation_id') != self.record().get('conversation_id')
                or messages[-1].get('role') != 'user'):
            raise BridgeError('invalid_turn')
        text = messages[-1].get('content')
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise BridgeError('invalid_turn')
        # Use provider history only for retry identity, never for system policy or model routing.
        revision = digest(messages)
        trace = 'phone_' + uuid.uuid4().hex
        def reserve(record):
            if record['status'] != 'active':
                raise BridgeError('call_not_active')
            if record.get('last_turn_digest') == revision:
                return record['last_decision']
            if revision in record.get('completed_turn_digests', []):
                raise BridgeError('stale_turn')
            if record.get('last_decision', {}).get('end'):
                return record['last_decision']
            if record.get('pending_turn'):
                raise BridgeError('turn_execution_unknown')
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(record['started_at'])).total_seconds()
            if record['turn_count'] >= 40 or age >= 900:
                decision = {'say': '', 'end': True, 'outcome': 'needs_approval', 'trace_id': trace}
                record.update(last_decision=decision, proposed_outcome='needs_approval')
                return decision
            record['pending_turn'] = revision
            return None
        previous = self.change(reserve)
        if previous is not None:
            return previous
        snapshot = self.record()
        start = time.monotonic()
        try:
            decision = self.brain(snapshot['brief'], snapshot['transcript'], safe_text(text), trace)
            if (not isinstance(decision, dict) or set(decision) != {'say', 'end', 'outcome'}
                    or not isinstance(decision['say'], str) or not decision['say'].strip()
                    or len(decision['say']) > 1000 or type(decision['end']) is not bool
                    or decision['outcome'] not in {'answered', 'message_taken', 'needs_approval'}
                    or safe_text(decision['say']) != decision['say']):
                raise ValueError('invalid decision')
        except Exception:
            def fail(record):
                if record['status'] == 'active' and record.get('pending_turn') == revision:
                    record['bridge_error'] = 'brain_execution_unknown'
            self.change(fail)
            raise BridgeError('brain_unavailable_check_status') from None
        elapsed = round((time.monotonic() - start) * 1000, 3)
        decision = dict(decision, trace_id=trace)
        def finish(record):
            if record['status'] != 'active' or record.get('pending_turn') != revision:
                raise BridgeError('stale_turn')
            record.pop('pending_turn')
            record.update(last_turn_digest=revision, last_decision=decision,
                          turn_count=record['turn_count'] + 1, proposed_outcome=decision['outcome'])
            record['transcript'] = (record['transcript'] + [
                {'who': 'them', 'text': safe_text(text), 'at': now()},
                {'who': 'pa', 'text': decision['say'], 'at': now()}])[-80:]
            record['brain_receipts'].append({'trace_id': trace, 'input_digest': revision,
                'response_digest': digest(decision['say']), 'elapsed_ms': elapsed})
            record.setdefault('completed_turn_digests', []).append(revision)
            return decision
        return self.change(finish)

    def post_call(self, event):
        if event.get('type') != 'post_call_transcription' or not isinstance(event.get('data'), dict):
            raise BridgeError('unsupported_event')
        data = event['data']
        record = self.record()
        if (not record.get('conversation_id') or data.get('conversation_id') != record['conversation_id']
                or data.get('agent_id') != record['bridge_agent_id'] or data.get('status') not in {'done', 'failed'}):
            raise BridgeError('unbound_or_nonterminal_event')
        raw_turns = data.get('transcript')
        if not isinstance(raw_turns, list) or len(raw_turns) > 160:
            raise BridgeError('transcript_outside_call_limits')
        transcript = []
        for turn in raw_turns:
            if not isinstance(turn, dict) or turn.get('role') not in {'user', 'agent'}:
                raise BridgeError('invalid_transcript')
            if turn.get('message') is None and (turn.get('tool_calls') or turn.get('tool_results')):
                continue  # Tool-only entries contain no spoken utterance; never export tool internals.
            if not isinstance(turn.get('message'), str) or len(turn['message']) > 1000:
                raise BridgeError('invalid_transcript')
            transcript.append({'who': 'pa' if turn['role'] == 'agent' else 'them',
                               'text': safe_text(turn['message']), 'at': now()})
        if len(transcript) > 80:
            raise BridgeError('transcript_outside_call_limits')
        analysis = data.get('analysis') or {}
        if not isinstance(analysis, dict):
            raise BridgeError('invalid_analysis')
        summary = safe_text(analysis.get('transcript_summary') or 'Call ended; review the transcript. No commitment verified.')[:1000]
        # Provider analysis is evidence, never permission or proof of a booking.
        def close(record):
            if record['status'] == 'ended':
                return
            if record['status'] != 'active':
                raise BridgeError('call_not_active')
            outcome = record.get('proposed_outcome', 'answered')
            if record.get('bridge_error') or record.get('pending_turn') or data['status'] == 'failed':
                outcome = 'needs_approval'
            record.update(status='ended', ended_at=now(), transcript=transcript, summary=summary,
                          outcome=outcome, provider_status=data['status'], handoff={'status': 'pending'})
        self.change(close)
        return self.publish_handoff()

    def publish_handoff(self):
        record = self.record()
        if record['status'] != 'ended':
            raise BridgeError('call_not_terminal')
        # Stable snapshot: callback retries never overwrite it or change the packet identity.
        evidence = {'call_id': self.call_id, 'conversation_id': record['conversation_id'],
                    'outcome': record['outcome'], 'summary': record['summary'],
                    'transcript': record['transcript'], 'brain_receipts': record['brain_receipts']}
        content = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        revision = digest(evidence)[:32]
        chunks, chunk = [], ''
        for char in content:
            if len((chunk + char).encode('utf-8')) > 6000:
                chunks.append(chunk)
                chunk = ''
            chunk += char
        chunks.append(chunk)
        identities = []
        for index, chunk in enumerate(chunks):
            identity = f'phone:{self.call_id}:{index}'
            identities.append(identity)
            self.queue.publish({'version': 1, 'event_id': identity, 'revision': revision, 'kind': 'phone_call',
                'observed_at': time.time(), 'expires_at': time.time() + 86400,
                'destination': self.settings.destination,
                'source': [{'identity': record['conversation_id'], 'revision': revision, 'links': []}],
                'facts': [{'label': f'call_evidence_part_{index + 1}_of_{len(chunks)}', 'value': chunk}],
                'coverage': {'status': 'complete', 'notes': 'Untrusted call evidence; parts jointly contain the bounded transcript. Queue admission is not delivery acknowledgment.'},
                'failures': []})
            if self.queue.row(identity, revision) is None:
                raise BridgeError('handoff_not_persisted')
        result = {'status': 'queued', 'event_ids': identities, 'revision': revision}
        self.change(lambda current: current.update(handoff=result))
        return result
