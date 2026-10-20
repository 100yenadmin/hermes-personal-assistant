"""Real subprocess deadline tests, no Hermes provider or paid route."""
import json
import os
import subprocess
import sys
import time

import pytest

from personal_assistant.phone_brain import HermesBrain


@pytest.mark.skipif(os.name != 'posix', reason='call-worker process-group isolation requires POSIX')
def test_blocking_worker_is_killed_at_external_deadline(tmp_path):
    marker = tmp_path / 'late-output'
    command = [sys.executable, '-c',
               'import sys,time,pathlib; sys.stdin.read(); time.sleep(1); '
               f'pathlib.Path({str(marker)!r}).write_text("late"); print("{{}}")']
    brain = HermesBrain(model='fixture', provider='fixture', cwd=tmp_path,
                        deadline_seconds=0.1, worker_command=command)
    started = time.monotonic()
    with pytest.raises(ValueError, match='deadline'):
        brain({}, [], 'hello', 'trace_fixture')
    assert time.monotonic() - started < 0.8
    assert not marker.exists()


def test_completed_subprocess_decision_and_private_error_boundary(tmp_path):
    decision = dict(say='A test message?', end=False, outcome='answered')
    good = [sys.executable, '-c', 'import sys,json; payload=json.load(sys.stdin); '
            'assert payload["text"] == "hello"; print(' + repr(json.dumps({'ok': True, 'decision': decision})) + ')']
    brain = HermesBrain(model='fixture', provider='fixture', cwd=tmp_path, worker_command=good)
    assert brain({}, [], 'hello', 'trace_fixture') == decision
    bad = [sys.executable, '-c', 'import sys; sys.stdin.read(); print("private provider detail", file=sys.stderr); sys.exit(2)']
    brain = HermesBrain(model='fixture', provider='fixture', cwd=tmp_path, worker_command=bad)
    with pytest.raises(ValueError) as error:
        brain({}, [], 'hello', 'trace_fixture')
    assert 'private' not in str(error.value)


@pytest.mark.skipif(os.name != 'posix', reason='call-worker process-group isolation requires POSIX')
def test_deadline_terminates_worker_descendants(tmp_path):
    marker = tmp_path / 'descendant-late-output'
    descendant = 'import time,pathlib; time.sleep(1); ' + f'pathlib.Path({str(marker)!r}).write_text("late")'
    command = [sys.executable, '-c', 'import sys,subprocess,time; sys.stdin.read(); '
               f'subprocess.Popen([sys.executable,"-c",{descendant!r}]); time.sleep(5)']
    brain = HermesBrain(model='fixture', provider='fixture', cwd=tmp_path,
                        deadline_seconds=0.2, worker_command=command)
    with pytest.raises(ValueError, match='deadline'):
        brain({}, [], 'hello', 'trace_fixture')
    # Foreground bounded wait verifies a descendant cannot write after the parent was killed.
    time.sleep(1.1)
    assert not marker.exists()
