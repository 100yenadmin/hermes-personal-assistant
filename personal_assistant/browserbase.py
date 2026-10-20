"""Profile-scoped Browserbase sessions; bearer URLs are transient, never ledger data."""
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .state import now

API = "https://api.browserbase.com"
ATTACH_HINT = "agent-browser --session <name> connect <connect_url>"


def secret(name, get_secret=None):
    try:
        if get_secret is None:
            from agent.secret_scope import get_secret
        return get_secret(name)
    except Exception:  # Includes Hermes-free imports and UnscopedSecretError.
        return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Browserbase redirects are refused")


def browser_session(ledger, data, *, opener=None, get_secret=None, base_url=API):
    # The endpoint is fixed: a profile setting must never be able to send the key elsewhere. Tests pass base_url.
    action = data.get("action", "status")
    if action not in {"status", "create", "live_view", "connect", "release"}:
        raise ValueError("unknown browser_session action")
    key, project = (secret(name, get_secret) for name in ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"))
    if action == "status":
        return {"configured": bool(key and project)}
    if not (key and project):
        return {"status": "needs_setup", "reason": "Browserbase is not configured for this profile",
                "next_step": "Add BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID to the profile's secrets."}
    identity = data.get("bb_session_id") if isinstance(data.get("bb_session_id"), str) else ""
    row_id = "pa:browser-session:" + identity
    if action != "create":
        row = ledger.get("action", row_id)
        if not row or row["action_type"] != "browser_session" or row["fields"].get("bb_session_id") != identity:
            return {"status": "error", "reason": "Unknown PA Browserbase session"}
    base = base_url.rstrip("/")
    transport = opener if opener is not None else build_opener(ProxyHandler({}), NoRedirect())

    def request(path, body=None):
        req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json", "X-BB-API-Key": key})
        with transport.open(req, timeout=60) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized Browserbase reply")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("invalid Browserbase reply")
        return result

    def live_view(identity):
        try:
            return request("/v1/sessions/" + identity + "/debug").get("debuggerFullscreenUrl")
        except Exception:  # Session creation succeeds even if debug is unavailable.
            return None

    try:
        if action == "create":
            body = {"projectId": project, "keepAlive": True, "timeout": 1200,
                    "browserSettings": {"recordSession": False, "logSession": False, "solveCaptchas": False}}
            if data.get("region"):
                body["region"] = data["region"]
            try:
                result = request("/v1/sessions", body)
            except HTTPError as exc:
                if exc.code != 402:
                    raise
                body.pop("keepAlive")
                result = request("/v1/sessions", body)
            identity = result.get("id")
            if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
                raise ValueError("invalid Browserbase session id")
            try:
                connect_url = result.get("connectUrl")
                if not isinstance(connect_url, str) or not connect_url:
                    raise ValueError("no connection URL")
                ledger.put("action", "pa:browser-session:" + identity,
                           {"bb_session_id": identity, "expires_at": result.get("expiresAt"), "created_at": now()},
                           action_type="browser_session", status="active")
            except Exception:  # Without a usable row PA could never release it; end the paid session now.
                try:
                    request("/v1/sessions/" + identity, {"projectId": project, "status": "REQUEST_RELEASE"})
                except Exception:
                    pass
                raise
            # Accepted tradeoff: model-visible URLs are short-lived session bearers and die on release.
            return {"bb_session_id": identity, "connect_url": connect_url,
                    "live_view_url": live_view(identity), "expires_at": result.get("expiresAt"),
                    "attach_hint": ATTACH_HINT}
        if action == "live_view":  # An explicit refresh reports failures instead of a null link.
            debug = request("/v1/sessions/" + identity + "/debug")
            url = debug.get("debuggerFullscreenUrl")
            if not isinstance(url, str) or not url:
                raise ValueError("no live view link")
            # Each tab has its own live view; the agent sends the link of the tab holding the step.
            pages = debug.get("pages") if isinstance(debug.get("pages"), list) else []
            tabs = [{"title": page.get("title"), "origin": _origin(page.get("url")), "live_view_url": page["debuggerFullscreenUrl"]}
                    for page in pages if isinstance(page, dict) and isinstance(page.get("debuggerFullscreenUrl"), str)
                    and page["debuggerFullscreenUrl"]]
            return {"bb_session_id": identity, "live_view_url": url, **({"tabs": tabs} if len(tabs) > 1 else {})}
        if action == "connect":  # Reattach after a lost agent-browser connection; only a running session.
            result = request("/v1/sessions/" + identity)
            connect_url = result.get("connectUrl")
            if result.get("status") != "RUNNING" or not isinstance(connect_url, str) or not connect_url:
                return {"status": "error", "reason": "Browserbase session is not running; create a new one"}
            return {"bb_session_id": identity, "connect_url": connect_url, "expires_at": result.get("expiresAt"),
                    "attach_hint": ATTACH_HINT}
        request("/v1/sessions/" + identity, {"projectId": project, "status": "REQUEST_RELEASE"})
        ledger.put("action", row_id, {}, status="released")
        return {"bb_session_id": identity, "status": "released"}
    except HTTPError as exc:
        return {"status": "error", "http_status": exc.code, "reason": "Browserbase request denied"}
    except Exception:
        return {"status": "error", "reason": "Browserbase request failed"}


def _origin(url):
    """A tab's scheme and host only: page URLs can carry OAuth codes or signed tokens."""
    try:
        parts = urlsplit(url) if isinstance(url, str) else None
        host, port = (parts.hostname, parts.port) if parts else (None, None)
    except ValueError:
        return None
    if not (parts and parts.scheme and host):
        return None
    host = f"[{host}]" if ":" in host else host  # Never the userinfo part of netloc.
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")
