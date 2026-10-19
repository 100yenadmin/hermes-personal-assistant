"""Optional installed call_sim adapter. HTTP is used only during operator live runs."""
import json
import os
import select
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen
import yaml


class Calls:
    def __init__(self, package, python, spec):
        self.package, self.python, self.spec, self.process, self.home = package, python, spec, None, None

    def request(self, path, data=None):
        req = Request(self.url + path, data=json.dumps(data).encode() if data is not None else None,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=15) as response:
            return json.load(response)

    def start(self):
        directory = self.package / "evals/call_sim/personas"
        matches = list(directory.glob(self.spec["persona"] + ".*"))
        if len(matches) != 1:
            raise ValueError("calls.persona: missing or ambiguous installed persona file")
        persona = yaml.safe_load(matches[0].read_text())
        business = persona.get("business", persona)
        self.name, self.number = business.get("name", persona.get("name")), business.get("number", business.get("phone"))
        if not self.name:
            raise ValueError("calls.persona.name: missing")
        # The simulator only rings with a reason from the persona sheet; the scenario reason is the user's instruction.
        self.ring_reason = self.spec.get("ring_reason") or (persona.get("inbound") or [None])[0]
        # The simulated business is not the assistant: an empty Hermes home keeps PA's hooks out of its prompt.
        # Its Codex token comes from CODEX_HOME, which the runner sets.
        self.home = tempfile.mkdtemp(prefix="pa-call-sim-")
        self.process = subprocess.Popen([self.python, "-m", "evals.call_sim.server", "--personas", str(directory),
            "--port", "0", "--model-backend", "codex"], cwd=self.package,
            env={**os.environ, "PYTHONPATH": str(self.package), "HERMES_HOME": self.home},
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if not select.select([self.process.stdout], [], [], 30)[0]:
            raise TimeoutError("call_sim startup timeout")
        self.url = json.loads(self.process.stdout.readline())["url"]
        if not self.url.startswith("http://127.0.0.1:"):
            raise ValueError("call_sim: expected loopback URL")
        if self.spec["direction"] == "inbound":
            self.call_id = self.request("/ring", {"persona": self.spec["persona"], "reason": self.ring_reason})["call_id"]
        return self.url

    def message(self, language, goal):
        if self.spec["direction"] == "outbound":
            return goal + f"\n{self.name}, phone number {self.number or 'unavailable'} (sim persona: {self.spec['persona']})."
        return {"en": f"[Incoming call for you — call_id {self.call_id} from {self.name}. Please answer it for me.]",
                "ja": f"[着信です — {self.name}、call_id {self.call_id}。代わりに電話に出てください。]",
                "ko": f"[전화가 왔어요 — {self.name}, call_id {self.call_id}. 대신 받아 주세요.]"}[language] + "\n" + goal

    def close(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process.stdout.close()
        if self.home:
            shutil.rmtree(self.home, ignore_errors=True)
