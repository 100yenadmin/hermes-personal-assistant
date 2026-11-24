"""Artifact IO with a process-local, never-persisted token scrubber."""
import json
import os
import re
from pathlib import Path

MODEL = "gpt-6.1-sol"
SECRET = ""
REDACTED = "[REDACTED]"


CONNECT_KEYS = re.compile(r"((?:signingKey|apiKey|api_key)=)[^&\s\"'\\]+")  # Stops at JSON escapes.
DEVTOOLS_URL = re.compile(r"https?://(?:www\.)?browserbase\.com/devtools[^\s\"'\\]*")

_EXEC_STRING = r"""(?:"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*')"""
_EXEC_PYTHON_NETWORK = re.compile(
    rf"{_EXEC_STRING}|\#[^\n]*|(?P<network>\b(?:urllib\s*\.\s*request|urllib\s+import\s+[\w ,]*\brequest|urlopen|requests|http\s*\.\s*client|httpx|aiohttp|"
    r"socket|smtplib|ftplib|websocket)\b)"
)
_EXEC_JS_NETWORK = re.compile(r"\b(?:fetch\s*\(|XMLHttpRequest\b|sendBeacon\b|new\s+WebSocket\b)")
# An open() path can contain quoted commas and calls such as Path.home().
_EXEC_PARENS = rf"""\((?:{_EXEC_STRING}|[^()"'])*\)"""
_EXEC_OPEN_PATH = rf"""(?:{_EXEC_STRING}|[^,();"'#]|\((?:{_EXEC_STRING}|{_EXEC_PARENS}|[^()"'])*\))+"""
_EXEC_WRITE = re.compile(
    rf"\bopen\s*\((?:{_EXEC_OPEN_PATH},\s*(?:mode\s*=\s*)?|\s*mode\s*=\s*)"
    r"""(["'])[rbt]*[wax+][rwaxbt+]*\1"""
    r"""|\.\s*open\s*\(\s*(?:mode\s*=\s*)?(["'])[rbt]*[wax+][rwaxbt+]*\2"""
    r"|\.\s*(?:write_text|write_bytes|mkdir|touch)\s*\("
    r"|\bos\s*\.\s*(?:rename|replace|makedirs|mkdir)\b"
)
_EXEC_OUTSIDE = re.compile(
    r"""["'][/~]|\b(?:expanduser|Path\s*\.\s*home|os\s*\.\s*environ|HOME|HERMES_HOME)\b"""
    r"""|\.hermes\b|(?<=[/'"])\.\.(?=[/'"]|$)"""
)


def exec_effects(code: str) -> list[str]:
    """Flag network tokens and writes alongside outside-path markers in browser_exec code.

    This static scan recognizes common spellings and literal modes. It can
    flag unused tokens, does not tie paths to a particular write or prove
    execution, and can miss computed or obfuscated code.
    """
    effects = []
    if _EXEC_JS_NETWORK.search(code) or any(m["network"] for m in _EXEC_PYTHON_NETWORK.finditer(code)):
        effects.append("network")
    if _EXEC_WRITE.search(code) and _EXEC_OUTSIDE.search(code):
        effects.append("write")
    return effects


def scrub(value, *, limit=None):
    """Remove tokens, Browserbase keys, connect URL keys, and devtools live view URLs."""
    text = str(value)
    for secret in filter(None, (SECRET, os.environ.get("BROWSERBASE_API_KEY", ""))):
        text = text.replace(secret, REDACTED)
    text = DEVTOOLS_URL.sub(REDACTED, CONNECT_KEYS.sub(r"\1" + REDACTED, text))
    if limit is None or len(text) <= limit:
        return text
    # A later scrub of the JSON must not expand a partial redaction past the cap.
    overlap = len(REDACTED) - 1
    crossing = text.find(REDACTED, max(0, limit - overlap), limit + overlap)
    return text[:crossing if crossing >= 0 else limit]


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
