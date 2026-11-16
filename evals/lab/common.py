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


LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")


def encodable(text):
    """Page text can carry a lone UTF-16 surrogate; UTF-8 cannot encode it, and write_text would leave an empty file."""
    return LONE_SURROGATE.sub("\ufffd", text)


def write(path, value):
    Path(path).write_text(encodable(scrub(json.dumps(value, ensure_ascii=False, indent=2))), encoding="utf-8")


def read(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default


def lines(path):
    p = Path(path)
    # split("\n"), not splitlines(): page text keeps raw U+2028/U+2029 inside JSON strings (ensure_ascii=False).
    return [json.loads(s) for s in p.read_text(encoding="utf-8").split("\n") if s.strip()] if p.exists() else []


def append(path, value):
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(encodable(scrub(json.dumps(value, ensure_ascii=False))) + "\n")
