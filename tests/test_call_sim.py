import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from evals.call_sim.server import Simulator, Scripted, Codex
from evals.call_sim.voice_check import check, distance, FishClient

PERSONAS = Path(__file__).resolve().parents[1] / 'evals/call_sim/personas'


def test_persona_sheets_and_scripted_behaviours():
    sim = Simulator(PERSONAS)
    assert len(sim.personas) == 5 and sim.codex is None
    for persona in sim.personas.values():
        assert {'hours', 'address', 'availability', 'prices', 'deposit_rules', 'menu_notes'} <= persona['facts'].keys()
        actor = Scripted(persona)
        assert actor.reply()['text'] == persona['facts']['phrases']['greeting']
        assert actor.reply('問い合わせ')['text']
    p = sim.personas['ko_restaurant_booking']
    assert '70000' in Scripted(p).reply('8명')['text']
    assert '7시' in Scripted(p).reply('unavailable')['text']
    p['behaviours']['busy'] = True
    assert Scripted(p).reply('안녕하세요')['ended'] is True


def test_scripted_import_does_not_load_hermes():
    result = subprocess.run([sys.executable, '-c',
        "import sys; from evals.call_sim.server import Simulator; "
        "assert 'run_agent' not in sys.modules; assert 'hermes_cli.auth' not in sys.modules"],
        check=True, capture_output=True)
    assert result.returncode == 0


def test_codex_no_tools_existing_token_only(monkeypatch, tmp_path):
    reads, instances = [], []
    class Agent:
        def __init__(self, **kwargs):
            self.kwargs, self.valid_tool_names = kwargs, set()
            self.closed = False
            instances.append(self)
        def run_conversation(self, text, **kwargs):
            assert 'sheet facts' in kwargs['system_message']
            assert '가상 식당' in kwargs['system_message']
            return {'final_response': '안녕하세요', 'messages': [{'role': 'assistant', 'content': '안녕하세요'}]}
        def close(self):
            self.closed = True
    monkeypatch.setitem(sys.modules, 'run_agent', SimpleNamespace(AIAgent=Agent))
    monkeypatch.setitem(sys.modules, 'hermes_cli', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'hermes_cli.auth', SimpleNamespace(
        _read_codex_tokens=lambda: (reads.append(1) or {'tokens': {'access_token': 'synthetic-fixture'}})))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))  # No real auth file is read in tests.
    monkeypatch.setenv('HOME', str(tmp_path))
    backend = Codex()
    persona = yaml.safe_load((PERSONAS / 'ko_restaurant_booking.yaml').read_text())
    history = []
    for _ in range(2):
        assert backend.reply(persona, history)['text'] == '안녕하세요'
    assert len(reads) == 1 and history
    assert all(a.kwargs['provider'] == 'openai-codex' and a.kwargs['model'] == 'gpt-6.1-sol'
               and a.kwargs['enabled_toolsets'] == [] and a.closed for a in instances)


@pytest.mark.parametrize('language,reference,hypothesis,expected', [
    ('ja', 'あいう', 'あえう', 1/3), ('ko', '안 녕', '안녕', 0), ('en', 'abc', 'ab', 1/3),
    # transcribe-1-pro marks speakers and breaths; that markup is not a recognition error.
    ('ja', 'あいう', '<|speaker:0|>あ[息を吸う音]いう', 0), ('ko', '네', '<|speaker:1|>네', 0),
    ('en', 'Use [AB12] now', 'Use [AB12] now', 0), ('en', '[breath] hello', '[breath] hello', 0)])  # Brackets in the reference are kept.
def test_voice_cer_and_latency_fake_client(language, reference, hypothesis, expected):
    class Client:
        def tts(self, text, lang, voice):
            assert (text, lang, voice) == (reference, language, 'fixture-voice')
            return b'fake wav'
        def asr(self, audio, lang):
            assert audio == b'fake wav' and lang == language
            return hypothesis
    ticks = iter([10.0, 10.25])
    result = check([{'text': reference}], language=language, voice='fixture-voice',
                   client=Client(), clock=lambda: next(ticks))
    assert result['cer'] == pytest.approx(expected)
    assert result['turns'][0]['tts_latency_seconds'] == .25
    assert distance('', 'abc') == 3


def test_fish_wire_requests_are_fake(monkeypatch):
    from evals.call_sim import voice_check
    requests = []
    def open_fake(req, timeout):
        requests.append(req)
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'wav' if req.full_url.endswith('/tts') else b'{"text":"ok"}'
        return Response()
    monkeypatch.setenv('FISH_API_KEY', 'synthetic-fixture')
    monkeypatch.setattr(voice_check, 'urlopen', open_fake)
    client = FishClient()
    assert client.asr(client.tts('こんにちは', 'ja', 'fixture'), 'ja') == 'ok'
    assert requests[0].get_header('Model') == 's2.1-pro'
    assert json.loads(requests[0].data)['reference_id'] == 'fixture'
    assert b'name="language"' in requests[1].data and b'ja' in requests[1].data


def test_opening_hangup_ends_the_call():
    sim = Simulator(PERSONAS)
    sim.codex = SimpleNamespace(reply=lambda *a, **k: {'text': '只今満席です。失礼いたします。', 'ended': True})
    p = sim.personas['ja_ryokan_late_checkin']
    started = sim.route('POST', '/calls', {'to': {'name': p['name'], 'number': p['number']}, 'language': p['language'],
                                           'disclosure': 'AIアシスタントです。', 'call_id': 'a' * 32})
    assert started['status'] == 'ended' and started['ended'] is True
    with pytest.raises(ValueError):
        sim.route('POST', '/calls/' + 'a' * 32 + '/say', {'text': 'もしもし'})


def test_callee_by_number_or_name_and_unknown_callee_is_named():
    import threading, urllib.error, urllib.request
    from evals.call_sim.server import make_server
    sim = Simulator(PERSONAS)
    p = sim.personas['ja_ryokan_late_checkin']
    # The lab prompt gives a name and a number; a model may put the number in either field.
    for index, to in enumerate(({'number': p['number']}, {'name': p['name']}, {'name': p['number']})):
        started = sim.route('POST', '/calls', {'to': to, 'language': 'ja', 'disclosure': 'AIです。', 'call_id': str(index) * 32})
        assert started['status'] == 'active' and started['to']['name'] == p['name']
    with pytest.raises(LookupError):
        sim.route('POST', '/calls', {'to': {'name': 'nobody'}, 'language': 'ja', 'disclosure': 'AIです。', 'call_id': 'f' * 32})
    server = make_server(PERSONAS)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        body = json.dumps({'to': {'name': 'nobody'}, 'language': 'ja', 'disclosure': 'AI', 'call_id': 'e' * 32}).encode()
        request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/calls', data=body,
                                         headers={'Content-Type': 'application/json'})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        assert json.loads(error.value.read()) == {'status': 'sim_error', 'error': 'unknown callee'}
    finally:
        server.shutdown()
        server.server_close()


def test_lab_rings_inbound_calls_with_the_persona_reason(monkeypatch, tmp_path):
    import io, os
    from evals.lab import calls as lab_calls
    read, write = os.pipe()
    os.write(write, b'{"url": "http://127.0.0.1:9"}\n')
    os.close(write)
    monkeypatch.setattr(lab_calls.subprocess, 'Popen', lambda *a, **k: SimpleNamespace(stdout=io.open(read)))
    sent = []
    monkeypatch.setattr(lab_calls.Calls, 'request', lambda self, path, data=None: sent.append((path, data)) or {'call_id': 'c' * 32})
    package = Path(__file__).resolve().parents[1]
    spec = {'persona': 'ja_hotel_inbound_confirm', 'direction': 'inbound', 'reason': 'ホテルからの電話に出てください。'}
    lab_calls.Calls(package, sys.executable, spec).start()
    persona = yaml.safe_load((PERSONAS / 'ja_hotel_inbound_confirm.yaml').read_text())
    # The scenario reason is the user's instruction; the simulator only accepts a reason from the persona sheet.
    assert sent == [('/ring', {'persona': 'ja_hotel_inbound_confirm', 'reason': persona['inbound'][0]})]


def test_lab_counterpart_runs_without_the_assistants_plugins(monkeypatch, tmp_path):
    # The simulated business is not the assistant: PA's hooks (the /pa setup offer) must not reach its prompt.
    import io, os
    from evals.lab import calls as lab_calls
    read, write = os.pipe()
    os.write(write, b'{"url": "http://127.0.0.1:9"}\n')
    os.close(write)
    seen = {}
    def popen(*a, **k):
        seen.update(k['env'])
        return SimpleNamespace(stdout=io.open(read), terminate=lambda: None, wait=lambda timeout=None: 0)
    monkeypatch.setattr(lab_calls.subprocess, 'Popen', popen)
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'assistant-home'))
    package = Path(__file__).resolve().parents[1]
    calls = lab_calls.Calls(package, sys.executable, {'persona': 'ja_ryokan_late_checkin', 'direction': 'outbound'})
    calls.start()
    home = Path(seen['HERMES_HOME'])
    assert home != tmp_path / 'assistant-home' and home.is_dir() and not any(home.iterdir())
    calls.close()
    assert not home.exists()
