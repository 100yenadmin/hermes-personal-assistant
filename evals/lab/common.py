"""Artifact IO with a process-local, never-persisted token scrubber."""
import json
import os
import re
from pathlib import Path

MODEL = "gpt-6.1-sol"
SECRET = ""


CONNECT_KEYS = re.compile(r"((?:signingKey|apiKey|api_key)=)[^&\s\"'\\]+")  # Stops at JSON escapes.
DEVTOOLS_URL = re.compile(r"https?://(?:www\.)?browserbase\.com/devtools[^\s\"'\\]*")


def scrub(value):
    """Remove tokens, Browserbase keys, connect URL keys, and devtools live view URLs."""
    text = str(value)
    for secret in filter(None, (SECRET, os.environ.get("BROWSERBASE_API_KEY", ""))):
        text = text.replace(secret, "[REDACTED]")
    return DEVTOOLS_URL.sub("[REDACTED]", CONNECT_KEYS.sub(r"\1[REDACTED]", text))


def write(path, value):
    Path(path).write_text(scrub(json.dumps(value, ensure_ascii=False, indent=2)), encoding="utf-8")


def read(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default


def lines(path):
    p = Path(path)
    return [json.loads(s) for s in p.read_text().splitlines() if s.strip()] if p.exists() else []


def append(path, value):
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(scrub(json.dumps(value, ensure_ascii=False)) + "\n")
