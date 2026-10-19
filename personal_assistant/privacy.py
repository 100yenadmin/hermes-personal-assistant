"""Conservative export/record filtering, not a claim of universal PII detection."""
import re
from urllib.parse import parse_qsl, unquote, urlsplit

PRIVATE_KEYS = re.compile(r"password|secret|cookie|token|authorization|door.?code|wifi|booking.?ref|confirmation.?id|ticket.?number|passport|travell?er.?name|guest.?name", re.I)
PRIVATE_LINE = re.compile(r"(?:password|passcode|door\s*code|wi-?fi\s*(?:password|credentials)|booking\s*(?:ref|reference)|confirmation\s*(?:id|number|code)|ticket\s*number|bearer\s+[\w.-]+)\s*(?::|=|\bis\b)?", re.I)
# Packing instructions are shared facts. Actual passport values and document
# references remain restricted; the word alone is not evidence of a secret.
PASSPORT_VALUE = re.compile(r"\bpassport\s*(?:(?:number|no\.?|id|scan)\b\s*[:=#-]?\s*\S+|[:=#]\s*\S+|(?:is\s+)?(?=[A-Z0-9-]*\d)[A-Z0-9-]{5,}\b)", re.I)
URL = re.compile(r"(?:https?|webcal)://[^\s<>\]\)\"']+", re.I)


def safe_url(value):
    try:
        p = urlsplit(str(value))
        if p.scheme not in {"https", "http", "webcal"} or not p.hostname or p.username or p.password:
            return ""
        sensitive = lambda k: PRIVATE_KEYS.search(k) or k.lower() in {"code", "key", "signature", "invite", "sig", "t", "auth", "jwt"}
        if any(sensitive(k) for k, _ in parse_qsl(p.query)):
            return ""
        if p.fragment and (any(sensitive(k) for k, _ in parse_qsl(p.fragment)) or re.search(r"(?:access_token|id_token|authorization|bearer|password|secret|(?:^|[?&])code=)", unquote(p.fragment), re.I)):
            return ""
        if re.search(r"/(?:invite|invitations|auth|login|log-in|signin|sign-in|oauth\d*|sso|manage-booking)(?:[/.]|$)", unquote(p.path), re.I):
            return ""
        if p.hostname.endswith("browserbase.com") and any(word in p.path for word in ("devtools", "debug", "session")):
            return ""
        return str(value)
    except ValueError:
        return ""


def safe_text(value):
    lines = []
    for line in str(value or "").splitlines():
        if PRIVATE_LINE.search(line) or PASSPORT_VALUE.search(line):
            lines.append("[Restricted detail omitted; consult the source dashboard.]")
        else:
            lines.append(URL.sub(lambda m: safe_url(m.group()) or "[restricted link omitted]", line))
    return "\n".join(lines)


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if not PRIVATE_KEYS.search(str(k))}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return safe_text(value) if isinstance(value, str) else value
