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

EXEC_CODE_LIMIT = 20_000
# Match triple quotes first, and consume unfinished strings in truncated code.
_EXEC_STRING = (
    r"""(?>"{3}[\s\S]*?(?:"{3}|\Z)|'{3}[\s\S]*?(?:'{3}|\Z)"""
    r"""|"(?:\\[\s\S]|[^"\\])*+(?:"|\\?\Z)|'(?:\\[\s\S]|[^'\\])*+(?:'|\\?\Z))"""
)
_EXEC_NETWORK_MODULE = r"(?:requests|httpx|aiohttp|socket|smtplib|ftplib|websocket)"
_EXEC_IMPORT_PREFIX = r"(?:\w+(?:\.\w+)*(?:[ \t]+as[ \t]+\w+)?[ \t]*,[ \t]*)*"
_EXEC_PYTHON_NETWORK = re.compile(
    rf"{_EXEC_STRING}|#[^\n]*|(?P<network>\b(?:"
    rf"import[ \t]+{_EXEC_IMPORT_PREFIX}{_EXEC_NETWORK_MODULE}\b"
    rf"|from[ \t]+{_EXEC_NETWORK_MODULE}[ \t]+import\b"
    rf"|{_EXEC_NETWORK_MODULE}\s*\.\s*\w"
    r"|(?:urllib\s*\.\s*request|http\s*\.\s*client|importlib)\b"
    rf"|from[ \t]+urllib[ \t]+import[ \t(]+{_EXEC_IMPORT_PREFIX}request\b"
    r"|urlopen\s*\())"
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
# A slash appended to the workspace variable is a separator, so only skip
# that prefix. Any traversal marker or separate absolute literal still counts.
_EXEC_WORKSPACE_SUFFIX = (
    r"""\bos\s*\.\s*(?:environ\s*\[\s*(?P<env>["'])BH_AGENT_WORKSPACE(?P=env)\s*\]"""
    r"""|getenv\s*\(\s*(?P<get>["'])BH_AGENT_WORKSPACE(?P=get)\s*\))\s*\+\s*["']/"""
)
_EXEC_OUTSIDE = re.compile(
    rf"""{_EXEC_WORKSPACE_SUFFIX}|(?P<outside>["'](?:~|/[\w.~])"""
    r"""|\b(?:expanduser|Path\s*\.\s*home|HOME|HERMES_HOME)\b"""
    r"""|\.hermes\b|(?<=[/'"])\.\.(?=[/'"]|$))"""
)


def exec_effects(code: str) -> list[str]:
    """Flag network use and writes alongside outside-path markers in browser_exec code.

    This static scan recognizes common spellings and literal modes. It does
    not resolve aliases, tie paths to a particular write, or prove execution,
    and it can miss computed or obfuscated code. Code past the cap is flagged
    as unscanned.
    """
    truncated = len(code) > EXEC_CODE_LIMIT
    code = code[:EXEC_CODE_LIMIT]
    effects = []
    if _EXEC_JS_NETWORK.search(code) or any(m["network"] for m in _EXEC_PYTHON_NETWORK.finditer(code)):
        effects.append("network")
    if truncated:
        effects.append("unscanned")
    if _EXEC_WRITE.search(code) and any(m["outside"] for m in _EXEC_OUTSIDE.finditer(code)):
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
