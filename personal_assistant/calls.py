"""Approval-gated simulator calls and side-effect-free real-call brief compilation."""
import datetime as dt
import ipaddress
import json
import threading
import uuid
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .privacy import clean
from .phone_safety import COMPILE_REDACTION_FIELDS, RestrictedContent, display_name
from .state import Ledger, now

OUTCOMES = ['booked', 'needs_approval', 'no_answer', 'refused', 'answered', 'message_taken', 'handoff', 'cancelled']
DISCLOSURES = {  # (named, generic): spoken first, so no unfilled placeholders.
    'ja': ('AIアシスタントです。{name}様の代理でお電話しております。', 'AIアシスタントです。お客様の代理でお電話しております。'),
    'ko': ('{name}님을 대신해 전화드리는 AI 비서입니다.', '고객님을 대신해 전화드리는 AI 비서입니다.'),
    'en': ('Hello, this is an AI assistant calling on behalf of {name}.', 'Hello, this is an AI assistant calling on behalf of my client.'),
}


def disclosure(language, name=None):
    named, generic = DISCLOSURES[language]
    safe_name = display_name(name)
    return named.format(name=safe_name) if safe_name else generic


_PARTY = {'type': 'integer', 'minimum': 1, 'maximum': 1000}
_DATE = {'type': 'string', 'pattern': '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'}
_TIME = {'type': 'string', 'pattern': '^[0-9]{2}:[0-9]{2}$'}
_FACT = {'oneOf': [
    {'type': 'object', 'properties': {'type': {'const': kind}, 'value': schema},
     'required': ['type', 'value'], 'additionalProperties': False}
    for kind, schema in {
        'name': {'type': 'string', 'minLength': 1, 'maxLength': 40},
        'callback': {'type': 'string', 'pattern': '^\\+[1-9][0-9]{7,14}$'},
        'date': _DATE, 'time': _TIME, 'party_size': _PARTY}.items()]}

PARAMS = {
    'action': {'type': 'string', 'enum': ['prepare', 'compile', 'start', 'say', 'end', 'answer', 'status']},
    'call_id': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'},
    'purpose': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
    'language': {'type': 'string', 'enum': list(DISCLOSURES)},
    'direction': {'type': 'string', 'enum': ['outbound', 'inbound']},
    'to': {'type': 'object', 'properties': {'name': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                                         'number': {'type': 'string', 'maxLength': 64}},
           'required': ['name'], 'additionalProperties': False},
    'may_share': {'type': 'array', 'maxItems': 20, 'items': {'anyOf': [
        {'type': 'string', 'minLength': 1, 'maxLength': 1000}, _FACT]}},
    'limits': {'type': 'object', 'properties': {
        'party_size': _PARTY,
        'party_size_range': {'type': 'object', 'properties': {
            'min': _PARTY, 'max': _PARTY},
            'required': ['min', 'max'], 'additionalProperties': False},
        'date': _DATE, 'time': _TIME,
        'date_range': {'type': 'object', 'properties': {'start': _DATE, 'end': _DATE},
                       'required': ['start', 'end'], 'additionalProperties': False},
        'time_range': {'type': 'object', 'properties': {'start': _TIME, 'end': _TIME},
                       'required': ['start', 'end'], 'additionalProperties': False},
        'timezone': {'type': 'string', 'minLength': 1, 'maxLength': 64},
        'preferred_time': {'type': 'string', 'minLength': 1, 'maxLength': 500},
        'time_window': {'type': 'string', 'maxLength': 500},
        'flexibility': {'type': 'string', 'maxLength': 500},
        'max_deposit': {'type': 'number', 'minimum': 0, 'default': 0},
        'other': {'type': 'string', 'maxLength': 1000}}, 'additionalProperties': False},
    'on_behalf_of': {'type': 'string', 'maxLength': 100,
                     'description': 'Name to say in the disclosure, only if sharing it is allowed.'},
    'trip_id': {'type': 'string'}, 'confirmed': {'type': 'boolean'},
    'text': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
    'outcome': {'type': 'string', 'enum': OUTCOMES},
    'summary': {'type': 'string', 'maxLength': 1000},
}
SCHEMA = {'name': 'pa_call', 'description': 'Prepare a call card, compile an ElevenLabs per-conversation brief, or use the simulator. Load phone-calls or answering-calls. compile never starts a call; real phone activation is not implemented; none returns a script.',
          'parameters': {'type': 'object', 'properties': PARAMS, 'required': ['action'],
                         'additionalProperties': False, 'allOf': [
              {'if': {'properties': {'action': {'const': action}}},
               'then': {'required': required}}
              for action, required in {
                  'prepare': ['purpose', 'language', 'to', 'may_share', 'limits'],
                  'compile': ['call_id'], 'start': ['call_id'], 'say': ['call_id', 'text'],
                  'end': ['call_id', 'outcome', 'summary'], 'answer': ['call_id']}.items()]}}
_LOCK = threading.RLock()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('sim redirects are refused')


def sim_url(value):
    p = urlsplit(value)
    host = p.hostname
    if host == 'localhost':
        host = '127.0.0.1'
    if (p.scheme != 'http' or not host or not ipaddress.ip_address(host).is_loopback
            or p.username or p.password or p.path not in ('', '/') or p.query or p.fragment):
        raise ValueError('sim_url must be a plain loopback HTTP origin')
    host = f'[{host}]' if ':' in host else host
    return f'http://{host}:{p.port or 80}'


def request(url, path, data=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    req = Request(url + path, data=body, headers={'Content-Type': 'application/json'})
    with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=60) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise ValueError('oversized sim reply')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('invalid sim reply')
    return result


def _turn(record, who, text):
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        raise ValueError('invalid counterpart text')
    record['transcript'] = (record['transcript'] + [{'who': who, 'text': clean(text)[:1000], 'at': now()}])[-80:]


def _save(ledger, record, trip_id=None):
    return ledger.put('action', 'pa:call:' + record['call_id'], record,
                      action_type='call', trip_id=trip_id, status=record['status'])['fields']


def _script(brief):
    phrases = {
        'ja': ['予約・お問い合わせをお願いできますか。 / May I make a reservation or enquiry?',
               '条件に合わない場合は、本人に確認します。 / I will ask the user if outside the limits.',
               '詳細を確認させてください。ありがとうございます。 / Let me confirm the details. Thank you.'],
        'ko': ['예약이나 문의를 부탁드려도 될까요? / May I make a reservation or enquiry?',
               '조건을 벗어나면 본인에게 확인하겠습니다. / I will ask the user if outside the limits.',
               '내용을 확인하겠습니다. 감사합니다. / Let me confirm the details. Thank you.'],
        'en': ['May I make a reservation or enquiry?', 'I will ask the user if outside the limits.',
               'Let me confirm the details. Thank you.'],
    }
    language, limits = brief['language'], brief['limits']
    details = {
        'ja': f'「{brief["purpose"]}」についてお伺いしたいのですが。',
        'ko': f'「{brief["purpose"]}」에 관해 문의드리고 싶습니다.',
        'en': f'I would like to ask about: {brief["purpose"]}.',
    }
    constraints = {
        'ja': f'人数は{limits.get("party_size", "未指定")}名、希望日時は{limits.get("time_window", "未指定")}です。',
        'ko': f'인원은 {limits.get("party_size", "미정")}명이고 희망 시간은 {limits.get("time_window", "미정")}입니다.',
        'en': f'Party size: {limits.get("party_size", "unspecified")}; time: {limits.get("time_window", "unspecified")}.',
    }
    name = (brief.get('on_behalf_of') or '').strip()
    opener = {  # The user places this call themselves, so the script never claims to be an AI.
        'ja': (f'お電話失礼いたします。{name}と申します。' if name else 'お電話失礼いたします。') + ' / Hello, this is ' + (name or 'the caller') + '.',
        'ko': (f'안녕하세요, {name}입니다.' if name else '안녕하세요.') + ' / Hello, this is ' + (name or 'the caller') + '.',
        'en': f'Hello, this is {name}.' if name else 'Hello.',
    }[brief['language']]
    return [opener,
            details[language] + ' / Purpose: ' + brief['purpose'],
            constraints[language] + ' / Party size and requested time.', *phrases[language]]


def dispatch(profile_root, args, *, config=None, session_id=None):
    """Reject unknown keys, validate before state, and never expose transport exceptions."""
    from jsonschema import validate, ValidationError
    try:
        validate(args, SCHEMA['parameters'])
    except ValidationError:
        return {'status': 'invalid_request', 'note': 'Arguments do not match pa_call schema.'}
    with _LOCK:
        try:
            if config is not None and not isinstance(config, dict):
                return {'status': 'transport_error', 'note': 'calls config must be an object.'}
            return _dispatch(Ledger(profile_root, read_only=args['action'] == 'compile'), args, config or {}, session_id)
        except RestrictedContent as error:
            return {'status': 'restricted_content', 'fields': error.fields,
                    'note': 'Redact the listed fields and prepare a new call card.'}
        except (ValueError, KeyError, TypeError):
            return {'status': 'invalid_request', 'note': 'Check the required fields and call state.'}


def _dispatch(ledger, args, config, session_id):
    action = args['action']
    if action == 'prepare':
        brief = clean({k: args[k] for k in ('purpose', 'language', 'to', 'may_share', 'limits')})
        original_public = {key: args[key] for key in ('purpose', 'may_share', 'limits')}
        original_public['to.name'] = args['to']['name']
        cleaned_public = {key: brief[key] for key in ('purpose', 'may_share', 'limits')}
        cleaned_public['to.name'] = brief['to']['name']
        redacted = [key for key in COMPILE_REDACTION_FIELDS if original_public[key] != cleaned_public[key]]
        if redacted:
            # Store only safe paths, never a second/raw copy of sensitive facts.
            # A compiler must refuse rewritten facts, not promote cleaned input.
            brief['compile_redacted_fields'] = redacted
        if args.get('on_behalf_of'):
            brief['on_behalf_of'] = clean(args['on_behalf_of'])
            if display_name(args['on_behalf_of']) is None:
                # Preserve the ORIGINAL validation decision across privacy.clean
                # (splitlines may remove a trailing newline from an invalid name).
                brief['display_name_valid'] = False
        brief['limits'].setdefault('max_deposit', 0)
        brief['disclosure'] = disclosure(brief['language'], args.get('on_behalf_of'))
        direction = args.get('direction', 'outbound')
        brief['direction'] = direction
        if direction == 'inbound':
            from .phone_brief import INBOUND_DISCLOSURES
            brief['disclosure'] = INBOUND_DISCLOSURES[brief['language']]
        record = dict(schema=1, call_id=uuid.uuid4().hex, direction=direction, status='prepared',
                      brief=brief, transcript=[], turn_count=0, outcome=None, summary='', session_id=session_id,
                      created_at=now(), ended_at=None)
        record = _save(ledger, record, args.get('trip_id'))
        return {'status': 'prepared', 'call_id': record['call_id'], 'call_card': brief}
    if action == 'status' and not args.get('call_id'):
        return [row['fields'] for row in ledger.list('action') if row['action_type'] == 'call'][-10:][::-1]
    identity = args['call_id']
    row = ledger.get('action', 'pa:call:' + identity)
    record = row['fields'] if row and row['action_type'] == 'call' else None
    if action == 'status':
        return record or {'status': 'not_found'}
    if action == 'compile':
        if not record or record['status'] != 'prepared':
            return {'status': 'invalid_state'}
        from .phone_brief import compile_brief
        return {'status': 'compiled', 'call_id': identity,
                'conversation_initiation_client_data': compile_brief(record['brief']),
                'note': 'Payload only, not call permission. No service, agent change, or call started.'}
    if action == 'start':
        if not record or record['status'] != 'prepared' or args.get('confirmed') is not True:
            return {'status': 'confirmation_required', 'note': 'Show the call card and obtain an explicit yes.'}
        if config.get('transport') == 'elevenlabs':
            return {'status': 'not_activated',
                    'note': 'Phase 1 only compiles briefs and polls finished calls. Real phone activation needs separate approval and integration.'}
        if record['direction'] == 'inbound':
            return {'status': 'not_activated', 'note': 'Real inbound activation is not implemented.'}
        if config.get('transport', 'none') == 'none':
            record.update(status='handoff', outcome='handoff')
            _save(ledger, record)
            return {'status': 'no_transport', 'script': _script(record['brief']),
                    'note': 'Call yourself with this script, or connect a phone transport (#98).'}
    elif record and record.get('transport') == 'elevenlabs':
        return {'status': 'not_activated', 'note': 'Legacy bridge record: reconcile separately. pa_call cannot send speech, hang up, or invent a remote outcome.'}
    elif action == 'answer':
        if record:
            return {'status': 'invalid_state'}
    elif not record or (record['status'] not in {'active', 'ringing', 'confirmed'}
                        and not (action == 'end' and record['status'] in {'prepared', 'handoff'})
                        and not (action == 'end' and record['status'] == 'ended' and record['outcome'] is None)):
        return {'status': 'invalid_state'}
    if action == 'say':
        if record['status'] != 'active':
            return {'status': 'invalid_state'}
        elapsed = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(record['started_at'])
        if record['turn_count'] >= 40 or elapsed.total_seconds() >= 900:
            return {'status': 'call_limit', 'note': 'End this call: 40 turns or 15 minutes reached.'}
    if action == 'end' and record['status'] in {'prepared', 'confirmed', 'handoff'}:
        # No remote call is open: a declined card, a start that never connected, or a call the user
        # placed themselves and reported back. Close it locally and honestly.
        if (record['status'] == 'prepared') != (args['outcome'] == 'cancelled'):
            return {'status': 'invalid_request', 'note': 'Only a call that was never started ends as cancelled.'}
        record.update(status='ended', outcome=args['outcome'], summary=args['summary'], ended_at=now())
        return _save(ledger, record)
    try:
        if config.get('transport') != 'sim':
            raise ValueError('unsupported transport')
        url = sim_url(config.get('sim_url', ''))
    except (ValueError, TypeError):
        return {'status': 'transport_error', 'note': 'Only sim with a plain loopback HTTP sim_url is supported.'}
    try:
        if action == 'start':
            record.update(status='confirmed', started_at=now())
            _save(ledger, record)  # An uncertain start is not replayed automatically.
            reply = request(url, '/calls', {k: record['brief'][k] for k in ('to', 'language', 'disclosure')} | {'call_id': identity})
            _turn(record, 'pa', record['brief']['disclosure'])
        elif action == 'answer':
            reply = request(url, '/calls/' + identity)
            if reply.get('direction') != 'inbound' or reply.get('status') != 'ringing':
                raise ValueError('not a ringing inbound call')
            record = dict(schema=1, call_id=identity, direction='inbound', status='ringing',
                          brief={'purpose': reply['context'], 'language': reply['language'],
                                 'to': reply['to'], 'may_share': [], 'limits': {'max_deposit': 0},
                                 'disclosure': disclosure(reply['language'])}, transcript=[],
                          outcome=None, turn_count=0, summary='', session_id=session_id, created_at=now(),
                          started_at=now(), ended_at=None)
        elif action == 'say':
            _turn(record, 'pa', args['text'])  # The ledger keeps the cleaned line; the call hears the original.
            record['turn_count'] += 1
            _save(ledger, record)
            reply = request(url, '/calls/' + identity + '/say', {'text': args['text']})
        else:
            outcome, summary = args['outcome'], args['summary']
            reply = request(url, '/calls/' + identity + '/end', {'outcome': outcome, 'summary': clean(summary)})
            if reply.get('status') != 'ended' or reply.get('call_id') != identity:
                raise ValueError('invalid end acknowledgement')
            record.update(status='ended', outcome=outcome, summary=summary, ended_at=now())
            return _save(ledger, record)
        _turn(record, 'them', reply['text'])
        record['status'] = 'ended' if reply.get('ended') else 'active'
        if reply.get('ended'):
            record['ended_at'] = now()
        saved = _save(ledger, record)
        return {'status': saved['status'], 'call_id': identity, 'text': saved['transcript'][-1]['text'],
                'ended': bool(reply.get('ended')), 'context': clean(reply.get('context', ''))}
    except Exception:
        return {'status': 'transport_error', 'note': 'Simulator unavailable or invalid reply. Check status before retrying; the last send may have arrived.'}
