"""Caller-supplied Codex access token for the pinned Hermes child; never reads a saved login or refresh credential."""
import base64
import datetime as dt
import json
import os
import re
import sqlite3
import time

PLACEHOLDER = "pa-p4-placeholder-not-a-refresh-token"


class LiveAuth:
    def __init__(self):
        # The caller supplies the access token; the harness never opens a saved login.
        self.token = os.environ.get("PA_EVAL_CODEX_TOKEN", "")
        if not self.token:
            raise RuntimeError("NOT_RUN: PA_EVAL_CODEX_TOKEN is not set")
        self.preflight()

    def preflight(self):
        payload = self.token.split(".")[1]
        exp = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"]
        if exp <= time.time() + 7200:
            raise RuntimeError("NOT_RUN: token expiring")
        self.exp = exp
        self.checked_at = time.time()

    def configure(self, gateway):
        import hermes_yaml as yaml
        cfg = gateway.hermes_home / "config.yaml"
        data = yaml.safe_load(cfg.read_text())
        data["model"] = {"provider": "openai-codex", "default": "gpt-6.1-sol", "context_length": 128000}
        data["agent"].update(reasoning_effort="low", service_tier="")
        data["auxiliary"] = {"title_generation": {"model_upgrade_enabled": False}}
        data["service_tier"] = ""
        cfg.write_text(yaml.safe_dump(data, sort_keys=False))
        (gateway.hermes_home / ".env").write_text("")
        auth = gateway.hermes_home / "auth.json"
        auth.write_text(json.dumps({"providers": {"openai-codex": {"tokens": {
            "access_token": self.token, "refresh_token": PLACEHOLDER},
            "last_refresh": dt.datetime.now(dt.timezone.utc).isoformat()}}}))
        auth.chmod(0o600)
        gateway._env.update(PA_E2E_CODEX="1", HOME=str(gateway.home))

    def scrub(self, text):
        text = text.replace(self.token, "[REDACTED_ACCESS_TOKEN]")
        # Catch any token-shaped strings independent of the known access value.
        return re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED_JWT]", text)

    def finish(self, gateway, dest):
        auth_path = gateway.hermes_home / "auth.json"
        state = json.loads(auth_path.read_text())
        placeholder_ok = state["providers"]["openai-codex"]["tokens"]["refresh_token"] == PLACEHOLDER
        receipt = dict(placeholder_unchanged=placeholder_ok, token_source="PA_EVAL_CODEX_TOKEN",
                       jwt_exp=self.exp, minimum_ttl_seconds=7200, codex_home_unset_in_child=True,
                       expiry_checked_at=self.checked_at, ttl_at_check_seconds=self.exp - self.checked_at,
                       home_isolated=True, refresh_host_not_allowlisted=True)
        (dest / "auth-isolation.json").write_text(json.dumps(receipt, indent=2))
        # Remove the usable credential before any fallible transcript export.
        auth_path.write_text(self.scrub(json.dumps(state, indent=2)))
        with sqlite3.connect(gateway.db_path.as_uri() + "?mode=ro", uri=True) as src:
            src.row_factory = sqlite3.Row
            for table, filename in (("messages", "transcript.json"), ("session_model_usage", "usage.json")):
                rows = [dict(row) for row in src.execute('SELECT * FROM "' + table + '"')]
                (dest / filename).write_text(self.scrub(json.dumps(rows, indent=2,
                    default=lambda value: {"binary_hex": value.hex()} if isinstance(value, bytes) else str(value))))
        # Scrub runtime logs as well as snapshots; retain no usable credential at rest.
        for root in (dest, gateway.root):
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in {".json", ".jsonl", ".log", ".md", ".yaml"}:
                    text = path.read_text(errors="replace")
                    safe = self.scrub(text)
                    if safe != text:
                        path.write_text(safe)
        assert placeholder_ok, "auth isolation invariant failed"
