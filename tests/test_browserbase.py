import io
import json
import socket
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import HTTPHandler, ProxyHandler, build_opener
from urllib.response import addinfourl

import pytest
from personal_assistant.browserbase import NoRedirect, browser_session
from personal_assistant.capabilities import discover
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger

KEY = "synthetic-bb-key"
CONNECT = "wss://connect.browserbase.com?signingKey=synthetic"
LIVE = "https://www.browserbase.com/devtools/inspector.html?synthetic"
CREATED = {"id": "bb-1", "connectUrl": CONNECT, "expiresAt": "2026-10-21T12:00:00Z"}
SECRETS = {"BROWSERBASE_API_KEY": KEY, "BROWSERBASE_PROJECT_ID": "project"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail("real network is forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


class Opener:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def open(self, req, timeout):
        self.calls.append((req, timeout))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return io.BytesIO(json.dumps(reply).encode())


def test_create_dispatch_and_private_ledger(tmp_path):
    opener = Opener(CREATED, {"debuggerFullscreenUrl": LIVE})
    result = dispatch(tmp_path, {"operation": "browser_session", "data": {"action": "create", "region": "us-east-1"}},
                      runtime_scope={"browserbase_opener": opener, "get_secret": SECRETS.get, "session_id": "hermes-id"})
    assert result == {"bb_session_id": "bb-1", "connect_url": CONNECT, "live_view_url": LIVE,
                      "expires_at": CREATED["expiresAt"], "attach_hint": "agent-browser --session <name> connect <connect_url>"}
    req, timeout = opener.calls[0]
    assert (req.get_method(), req.full_url, timeout, req.get_header("X-bb-api-key")) == ("POST", "https://api.browserbase.com/v1/sessions", 60, KEY)
    assert json.loads(req.data) == {"projectId": "project", "keepAlive": True, "timeout": 1200, "region": "us-east-1",
                                   "browserSettings": {"recordSession": False, "logSession": False, "solveCaptchas": False}}
    assert opener.calls[1][0].get_method() == "GET" and opener.calls[1][0].full_url.endswith("/bb-1/debug")
    ledger = Ledger(tmp_path)
    raw = ledger.path.read_bytes() + json.dumps(ledger.list("action")).encode()
    assert all(value.encode() not in raw for value in (KEY, "connect_url", "signingKey", LIVE, CONNECT))
    assert KEY not in json.dumps(result)
    release = Opener({"debuggerFullscreenUrl": LIVE}, {})
    assert browser_session(ledger, {"action": "live_view", "bb_session_id": "bb-1"}, opener=release, get_secret=SECRETS.get)["live_view_url"] == LIVE
    assert browser_session(ledger, {"action": "release", "bb_session_id": "bb-1"}, opener=release, get_secret=SECRETS.get)["status"] == "released"
    assert json.loads(release.calls[1][0].data) == {"projectId": "project", "status": "REQUEST_RELEASE"}
    assert release.calls[1][0].get_method() == "POST" and release.calls[1][0].full_url.endswith("/bb-1")
    assert ledger.get("action", "pa:browser-session:bb-1")["status"] == "released"


@pytest.mark.parametrize("code", [401, 403, 402])
def test_errors_retry_and_debug_failure(tmp_path, code):
    error = HTTPError("https://api.browserbase.com", code, KEY, {}, io.BytesIO(KEY.encode()))
    opener = Opener(error, CREATED, error) if code == 402 else Opener(error)
    result = browser_session(Ledger(tmp_path), {"action": "create"}, opener=opener, get_secret=SECRETS.get)
    assert KEY not in json.dumps(result)
    assert len(opener.calls) == (3 if code == 402 else 1)
    if code == 402:
        assert "keepAlive" not in json.loads(opener.calls[1][0].data) and result["live_view_url"] is None
    else:
        assert result == {"status": "error", "http_status": code, "reason": "Browserbase request denied"}


def test_missing_raising_unknown_and_capabilities(tmp_path, monkeypatch):
    def raising(name):
        raise RuntimeError(KEY)
    ledger, opener = Ledger(tmp_path), Opener()
    for getter in ({}.get, raising):
        assert browser_session(ledger, {}, opener=opener, get_secret=getter) == {"configured": False}
        for action in ("create", "live_view", "release"):
            assert browser_session(ledger, {"action": action}, opener=opener, get_secret=getter)["status"] == "needs_setup"
    for action in ("live_view", "release"):
        assert browser_session(ledger, {"action": action, "bb_session_id": "unknown"}, opener=opener, get_secret=SECRETS.get)["status"] == "error"
    assert not opener.calls
    monkeypatch.setenv("BROWSERBASE_API_KEY", KEY)
    for check, status in ((lambda name: True, "available"), (lambda name: False, "needs_setup"), (raising, "needs_setup"), (None, "needs_setup")):
        rows = discover([SimpleNamespace(name="browser_open")], secret_present=check)["capabilities"]
        row = next(row for row in rows if row["id"] == "remote_browser")
        assert row["status"] == status and row["recovery_action"] and KEY not in json.dumps(row)
    assert next(row for row in discover([])["capabilities"] if row["id"] == "remote_browser")["status"] == "needs_setup"


def test_redirect_target_never_requested(tmp_path):
    urls = []
    class Redirect(HTTPHandler):
        def http_open(self, req):
            urls.append(req.full_url)
            headers = Message()
            headers["Location"] = "http://redirect.invalid/steal"
            response = addinfourl(io.BytesIO(b""), headers, req.full_url, 302)
            response.msg = "Found"
            return response
    opener = build_opener(ProxyHandler({}), NoRedirect(), Redirect())
    result = browser_session(Ledger(tmp_path), {"action": "create"}, opener=opener,
                             get_secret={**SECRETS, "BROWSERBASE_BASE_URL": "http://fixture.invalid"}.get)
    assert result == {"status": "error", "reason": "Browserbase request failed"}
    assert urls == ["http://fixture.invalid/v1/sessions"]


@pytest.mark.parametrize("path", ["browserbase-checkout-lane/SKILL.md", "food-delivery-to-hotel/SKILL.md",
                                  "browserbase-checkout-lane/references/checkout-login-recovery.md"])
def test_skill_text_uses_browser_session_and_user_final_tap(path):
    text = (Path(__file__).resolve().parents[1] / "skills" / path).read_text()
    for forbidden in ("$BROWSERBASE_API_KEY", "profile environment", "browse cloud sessions", "--remote", "browse open <url> --cdp"):
        assert forbidden not in text
    assert "agent-browser --session <task-name> connect <connect_url>" in text
    if path.endswith("SKILL.md"):
        assert 'operation="browser_session"' in text
    if path == "browserbase-checkout-lane/SKILL.md":
        assert "final pay/book/reserve tap is the user's own, in the live view" in text
        assert "The agent never presses the final submit" in text
