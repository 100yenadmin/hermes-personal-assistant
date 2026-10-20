"""Explicitly started loopback HTTP ingress, not a public Hermes API server."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .phone_bridge import Bridge, BridgeError, verify_signature
from .state import Ledger

MAX_BODY = 262144


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('redirect refused')


class ElevenLabsReader:
    """No dial, agent update, or arbitrary URL capability."""
    def __init__(self, key):
        if not key:
            raise ValueError('read key required for post-call polling')
        self.key = key

    def __call__(self, conversation_id):
        from .phone_bridge import _ID
        if not _ID.fullmatch(conversation_id) or not conversation_id.startswith('conv_'):
            raise ValueError('invalid provider identity')
        request = Request('https://api.elevenlabs.io/v1/convai/conversations/' + conversation_id,
                          headers={'xi-api-key': self.key})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=5) as response:
            raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            raise ValueError('provider result too large')
        return json.loads(raw)


def poll_once(bridge, reader):
    record = bridge.record()
    if record['status'] == 'ended':
        if record.get('handoff', {}).get('status') == 'pending':
            return bridge.publish_handoff()
        return None
    if not record.get('conversation_id'):
        return None
    data = reader(record['conversation_id'])
    if data.get('status') in {'done', 'failed'}:
        return bridge.post_call({'type': 'post_call_transcription', 'data': data})
    return None


def make_server(bridge, bearer, webhook_secret, *, port=8768):
    if (not isinstance(bearer, str) or len(bearer) < 32
            or not isinstance(webhook_secret, str) or len(webhook_secret) < 32
            or hmac.compare_digest(bearer, webhook_secret)):
        raise ValueError('distinct ingress and HMAC secrets of at least 32 characters required')

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        def __init__(self):
            self.slots = threading.BoundedSemaphore(4)
            super().__init__(('127.0.0.1', port), Handler)
        def process_request(self, request, client_address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except Exception:
                self.slots.release()
                raise
        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.slots.release()
        def handle_error(self, request, client_address):
            pass  # Never log raw provider exceptions or request details.

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass
        def setup(self):
            super().setup()
            self.connection.settimeout(5)
        def reply(self, status, data, *, sse=False):
            raw = data if sse else json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/event-stream' if sse else 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            self.reply(404, {'error': 'not_found'})
        def do_POST(self):
            try:
                if self.path not in {'/initiate', '/v1/chat/completions', '/post-call'}:
                    return self.reply(404, {'error': 'not_found'})
                if self.path != '/post-call' and not hmac.compare_digest(
                        self.headers.get('Authorization', ''), 'Bearer ' + bearer):
                    return self.reply(401, {'error': 'unauthorized'})
                if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
                    return self.reply(400, {'error': 'invalid_request'})
                lengths = self.headers.get_all('Content-Length', [])
                if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= MAX_BODY:
                    return self.reply(413, {'error': 'invalid_body_size'})
                raw = self.rfile.read(int(lengths[0]))
                if len(raw) != int(lengths[0]):
                    return self.reply(400, {'error': 'incomplete_body'})
                if self.path == '/post-call':
                    verify_signature(raw, self.headers.get('ElevenLabs-Signature', ''), webhook_secret)
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise BridgeError('invalid_request')
                if self.path == '/initiate':
                    return self.reply(200, bridge.initiate(data))
                if self.path == '/post-call':
                    return self.reply(200, bridge.post_call(data))
                decision = bridge.turn(data)
                delta = {'role': 'assistant', 'content': decision['say']}
                finish = 'stop'
                if decision['end']:
                    tools = data.get('tools', [])
                    if not isinstance(tools, list) or not any(isinstance(t, dict) and isinstance(t.get('function'), dict)
                            and t['function'].get('name') == 'end_call' for t in tools):
                        raise BridgeError('end_call_tool_required')
                    delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': decision['trace_id'],
                        'type': 'function', 'function': {'name': 'end_call',
                            'arguments': json.dumps({'reason': decision['outcome'], 'message': decision['say']})}}]}
                    finish = 'tool_calls'
                chunk = {'id': decision['trace_id'], 'object': 'chat.completion.chunk',
                         'created': int(time.time()), 'model': 'pa-hermes-call',
                         'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
                terminal = dict(chunk, choices=[{'index': 0, 'delta': {}, 'finish_reason': finish}])
                stream = ''.join('data: ' + json.dumps(item, ensure_ascii=False) + '\n\n'
                                 for item in (chunk, terminal)) + 'data: [DONE]\n\n'
                return self.reply(200, stream.encode(), sse=True)
            except BridgeError as exc:
                return self.reply(401 if str(exc) == 'invalid_signature' else 409, {'error': str(exc)})
            except (ValueError, TypeError, KeyError):
                return self.reply(400, {'error': 'invalid_request'})
            except Exception:
                return self.reply(503, {'error': 'bridge_unavailable_check_status'})

    return Server()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-root', required=True, type=Path, help='approved owner ledger home')
    parser.add_argument('--call-id', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--brain-workspace', required=True, type=Path)
    parser.add_argument('--port', default=8768, type=int)
    args = parser.parse_args()
    brain_home = os.environ.get('HERMES_HOME')
    if not brain_home or Path(brain_home).resolve() == args.profile_root.resolve():
        parser.error('HERMES_HOME must select a separate approved call-only brain profile')
    from .phone_brain import HermesBrain
    bridge = Bridge(Ledger(args.profile_root), args.call_id,
                    HermesBrain(model=args.model, provider=args.provider, cwd=args.brain_workspace))
    reader = ElevenLabsReader(os.environ.get('ELEVENLABS_API_KEY'))
    server = make_server(bridge, os.environ.get('PA_PHONE_INGRESS_KEY'), os.environ.get('PA_PHONE_WEBHOOK_SECRET'), port=args.port)
    stop = threading.Event()
    def poll():
        while not stop.wait(5):
            try:
                poll_once(bridge, reader)
                bridge.change(lambda record: record.pop('poll_error', None))
            except Exception:
                # No raw exception text. Expose the failure in pa_call status rather than hide it.
                try:
                    bridge.change(lambda record: record.update(poll_error={
                        'status': 'poll_or_handoff_failed', 'observed_at': time.time()}))
                except Exception:
                    print('{"status":"poll_state_unavailable"}', flush=True)
    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    try:
        print(json.dumps({'status': 'listening', 'host': '127.0.0.1', 'port': server.server_port}))
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        thread.join(timeout=6)


if __name__ == '__main__':
    main()
