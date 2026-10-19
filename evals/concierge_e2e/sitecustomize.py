"""Adapted from heartbeat2/tests/e2e/sitecustomize.py at HB2 commit 3ed7a21."""
import os

if os.environ.get("PA_E2E_CHILD") == "1":
    from loopback import install
    install(allowed_hosts=("chatgpt.com",) if os.getenv("PA_E2E_CODEX") == "1" else ())
    if os.getenv("PA_E2E_CODEX") == "1":
        os.environ.pop("CODEX_HOME", None)
        import json
        from pathlib import Path
        import httpx
        original_send = httpx.Client.send

        def send(client, request, **kwargs):
            if request.url.host != "chatgpt.com":
                return original_send(client, request, **kwargs)
            body = json.loads(request.content or "{}")
            row = {key: body.get(key) for key in ("model", "reasoning", "service_tier")}
            row["path"] = request.url.path
            try:
                response = original_send(client, request, **kwargs)
                row["status"] = response.status_code
                return response
            except Exception as exc:
                row["error"] = type(exc).__name__
                raise
            finally:
                path = Path(os.environ["HERMES_HOME"]) / "logs/model-wire.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a") as stream:
                    stream.write(json.dumps(row) + "\n")

        httpx.Client.send = send
