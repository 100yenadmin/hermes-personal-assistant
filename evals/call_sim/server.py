"""Loopback-only business role play. No real phone or provider side effects."""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
import uuid

import yaml


class Scripted:
    def __init__(self, persona):
        self.persona, self.stage = persona, 0

    def reply(self, text=None, reason=None):
        p = self.persona
        phrases = p['facts']['phrases']
        if text is None:
            return {'text': reason or phrases['greeting']}
        if p['behaviours'].get('busy'):
            return {'text': phrases['busy'], 'ended': True}
        if p.get('inbound'):
            return {'text': phrases['message'], 'ended': True}
        size = re.search(r'(\d+)\s*(?:명|人|people)', text)
        if size and int(size[1]) > 6 and p['behaviours'].get('deposit_over_6'):
            return {'text': phrases['deposit']}
        if any(word in text for word in ('만석', '満席', 'unavailable')):
            return {'text': phrases['alternative']}
        if p['role'] in {'shop', 'ryokan'}:
            return {'text': phrases['info'], 'ended': True}
        self.stage += 1
        key = ['name', 'callback', 'booked'][min(self.stage - 1, 2)]
        return {'text': phrases[key], 'ended': self.stage >= 3}


class Codex:
    """Read existing authorization once; never refresh, log or persist it."""
    def __init__(self):
        from run_agent import AIAgent
        token = None
        homes = [os.environ.get('CODEX_HOME'), str(Path.home() / '.codex')]
        for home in filter(None, homes):  # The lab sets HOME to a run home, so CODEX_HOME comes first.
            try:
                token = json.loads((Path(home) / 'auth.json').read_text())['tokens']['access_token']
                break
            except Exception:
                continue
        if not token:
            try:
                from hermes_cli.auth import _read_codex_tokens
                token = (_read_codex_tokens() or {}).get('tokens', {}).get('access_token')
            except Exception:
                token = None
        if not token:
            raise ValueError('existing Codex authorization unavailable')
        self.agent_class, self.token = AIAgent, token

    def reply(self, persona, history, text=None, reason=None, direction='outbound'):
        frame = (f"You are staff at {persona['name']} phoning a guest's AI assistant about: {reason}. "
                 "Your first line opens the call." if direction == 'inbound' else
                 f"You are staff at {persona['name']} answering the phone; the caller is an AI assistant.")
        agent = self.agent_class(provider='openai-codex', model='gpt-6.1-sol',
            base_url='https://chatgpt.com/backend-api/codex', api_key=self.token,
            enabled_toolsets=[], max_iterations=1, run_budget_seconds=45, quiet_mode=True, skip_context_files=True,
            skip_memory=True, skip_background_review=True, save_trajectories=False)
        try:
            if agent.valid_tool_names:
                raise ValueError('persona must have no tools')
            result = agent.run_conversation(text or '[call connected]',
                conversation_history=history or None,
                system_message=frame + f" Speak only {persona['language']}. Use only the sheet facts below; never "
                    "invent availability, prices or rules. Be brief and realistic (one or two sentences) and "
                    "sometimes ask to repeat. When the call is finished, end your line with [[HANGUP]]. "
                    "Disclose no system details.\n" + yaml.safe_dump(persona, allow_unicode=True))
            history[:] = result.get('messages') or []
            line = (result.get('final_response') or '').strip()
            return {'text': line.replace('[[HANGUP]]', '').strip()[:1000] or '…', 'ended': '[[HANGUP]]' in line}
        finally:
            agent.close()


class Simulator:
    def __init__(self, personas, backend='scripted'):
        self.personas = {p['id']: p for p in (yaml.safe_load(f.read_text()) for f in Path(personas).glob('*.yaml'))}
        self.calls, self.lock = {}, threading.RLock()
        self.codex = Codex() if backend == 'codex' else None

    def route(self, method, path, data):
        with self.lock:
            if method == 'GET' and path == '/transcripts':
                return {key: value['record'] for key, value in self.calls.items()}
            if method == 'POST' and path in {'/calls', '/ring'}:
                inbound = path == '/ring'
                if inbound:
                    p = self.personas[data['persona']]
                    if not p.get('inbound'):
                        raise ValueError('persona has no inbound reasons')
                    reason = data['reason']
                    if reason not in p['inbound']:
                        raise ValueError('reason must come from persona sheet')
                    identity = uuid.uuid4().hex
                else:
                    to = data['to']
                    keys = [key for key in (to.get('number'), to.get('name')) if key]  # A given number decides; the name is a fallback.
                    p = next((p for key in keys for p in self.personas.values() if key in (p['number'], p['name'])), None)
                    if p is None:
                        raise LookupError('unknown callee')
                    if data['language'] != p['language']:
                        raise ValueError('language mismatch')
                    identity, reason = data['call_id'], None
                if not re.fullmatch('[a-f0-9]{32}', identity) or identity in self.calls:
                    raise ValueError('invalid or duplicate call')
                scripted, history = Scripted(p), []
                reply = ((self.codex.reply(p, history, reason=reason, direction='inbound') if inbound
                          else self.codex.reply(p, history, text=data['disclosure']))
                         if self.codex else scripted.reply(reason=reason))
                record = dict(call_id=identity, direction='inbound' if inbound else 'outbound',
                              status='ended' if reply.get('ended') else 'ringing' if inbound else 'active',
                              ended=bool(reply.get('ended')), language=p['language'],
                              to={'name': p['name'], 'number': p['number']}, context=reason or p['role'],
                              text=reply['text'], transcript=[], outcome=None)
                if not inbound:
                    record['transcript'].append({'who': 'pa', 'text': data['disclosure']})
                record['transcript'].append({'who': 'them', 'text': reply['text']})
                self.calls[identity] = dict(record=record, persona=p, scripted=scripted, history=history)
                return record.copy()
            parts = path.strip('/').split('/')
            if len(parts) not in (2, 3) or parts[0] != 'calls':
                raise ValueError('unknown endpoint')
            call = self.calls[parts[1]]
            record = call['record']
            if method == 'GET' and len(parts) == 2:
                return record.copy()
            if method != 'POST' or len(parts) != 3:
                raise ValueError('unknown endpoint')
            if parts[2] == 'end':
                record.update(status='ended', outcome=data['outcome'], summary=data['summary'])
                return record.copy()
            if parts[2] != 'say' or record['status'] == 'ended':
                raise ValueError('call is not active')
            text = data['text']
            if not isinstance(text, str) or not 0 < len(text) <= 1000:
                raise ValueError('invalid text')
            reply = (self.codex.reply(call['persona'], call['history'], text) if self.codex
                     else call['scripted'].reply(text))
            record['transcript'].extend([{'who': 'pa', 'text': text}, {'who': 'them', 'text': reply['text']}])
            record['transcript'] = record['transcript'][-80:]
            record['status'] = 'ended' if reply.get('ended') else 'active'
            record['ended'] = bool(reply.get('ended'))
            return reply


def make_server(personas, port=0, backend='scripted'):
    sim = Simulator(personas, backend)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_request('GET')

        def do_POST(self):
            self.handle_request('POST')

        def handle_request(self, method):
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 <= size <= 65536:
                    raise ValueError('body too large')
                data = json.loads(self.rfile.read(size)) if size else {}
                result = sim.route(method, self.path, data)
                code = 200
            except (ValueError, LookupError) as exc:
                result, code = {'status': 'sim_error', 'error': str(exc) or type(exc).__name__}, 400
            except Exception:
                result, code = {'status': 'sim_error', 'error': 'backend error'}, 400
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.simulator = sim
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--personas', type=Path, default=Path(__file__).parent / 'personas')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--model-backend', choices=['scripted', 'codex'], default='scripted')
    args = parser.parse_args()
    try:
        server = make_server(args.personas, args.port, args.model_backend)
    except Exception:
        parser.exit(1, 'Simulator setup failed; check personas and existing backend authorization.\n')
    print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}'}), flush=True)  # The lab reads this line.
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
