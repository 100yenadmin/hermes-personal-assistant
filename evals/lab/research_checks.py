"""Offline research checks against the answer and this run's kept tool results."""
import json
import re
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

LABEL = re.compile(r"^(Question|Criteria|Recommendation|Comparison|Could not find|Not found|Gaps|Appendix)"
                   r"(?:\s*[:—–-]\s*(.*)|\s*(\(.*)|\s*)$", re.I)
MARKER = re.compile(r"\[(\d+)\]")
URL = re.compile(r'https?://[^\s<>\[\]()`\'"\\]+', re.I)
NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?(?:\s*[kK]\b)?"
CURRENCY = r"(?:US\$|SGD\$|SG\$|S\$|USD|SGD|JP¥|JPY|EUR|GBP|[$¥￥€£])"
AMOUNT = re.compile(r"(?<!\w)(?P<pcurrency>" + CURRENCY + r")\s*(?P<prefix>" + NUMBER + r")(?!\w|[.,]\d)"
                    r"|(?<![\w.,])(?P<suffix>" + NUMBER + r")\s*(?P<scurrency>" + CURRENCY + r"|円|yen)(?!\w)", re.I)
NUMBERS = re.compile(r"(?<![\d.,])" + NUMBER + r"(?!\d|[.,]\d)")
CUT = re.compile(r"\[lab cut \d+ chars\]")
STOP_NAMES = set("i we use choose select pick the it this because recommend recommendation question criteria comparison could not find gaps appendix sources".split())


def sections(answer):
    """Find line labels in headings, bold labels or plain 'Label:' text."""
    boundaries, offset = [], 0
    for line in answer.splitlines(keepends=True):
        clean = re.sub(r"^(?:(?:#+|\d+[.)])\s*|[-+*]\s+)+", "", line.strip()).replace("*", "").replace("_", "")
        match = LABEL.fullmatch(clean)
        if match:
            boundaries.append((match[1].lower(), offset, match[2] or match[3] or "", offset + len(line)))
        offset += len(line)
    result = {}
    for i, (key, start, inline, after) in enumerate(boundaries):
        end = boundaries[i + 1][1] if i + 1 < len(boundaries) and key != "appendix" else len(answer)
        if key and key not in result:
            result[key] = (start, (inline + "\n" + answer[after:end]).strip())
    return result


def url_key(url):
    parsed = urlsplit(url.strip().strip('`<>\'"').rstrip(".,;:)`<>\'\""))
    return (parsed.netloc.lower().removeprefix("www."), parsed.path.rstrip("/") or "/")


def urls(text):
    return [m[0].rstrip(".,;:)") for m in URL.finditer(text)]


def strings(value):
    if isinstance(value, str):
        yield value
    elif type(value) in (int, float):
        yield str(value)
    elif isinstance(value, (dict, list)):
        for item in value.values() if isinstance(value, dict) else value:
            yield from strings(item)


def result_text(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value
    return "\n".join(strings(value))


def fetched_sources(tools):
    fetched, current = {}, None
    for tool in tools:
        name = tool.get("name", "")
        if not name.startswith(("web_", "browser_")):
            continue
        value = tool.get("result", "")
        cut = bool(CUT.search(result_text(value)))
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        args = tool.get("structured_args", tool.get("args", {}))
        requested = list(dict.fromkeys(urls("\n".join(strings(args)))))
        reported = []

        def link(url, text):
            fetched.setdefault(url_key(url), []).append((text, cut))

        def walk(item):
            if isinstance(item, dict):
                own = [item[k] for k in ("url", "link", "href") if isinstance(item.get(k), str)
                       and URL.match(item[k].strip('`<>\'"'))]
                text = "\n".join(walk(v) for v in item.values())
                if own:
                    reported.extend(own)
                    for url in own:
                        link(url, text)
                    return ""  # Nested URL records never leak into their parent's text.
                return text
            if isinstance(item, list):
                return "\n".join(walk(v) for v in item)
            return result_text(item)

        outside = walk(value)
        if name == "browser_navigate" and len(requested) == 1:
            current = requested[0]
        if name.startswith("browser_") and reported:
            current = reported[-1]
        if name.startswith("browser_") and current:
            link(current, outside)
        elif len(requested) == 1 and re.search(r"(?:extract|navigate|fetch|open|visit|browse)(?:_|$)", name):
            link(requested[0], outside)
    return fetched


def numeric(value):
    value = re.sub(r"[,\s]", "", value).lower()
    return Decimal(value.rstrip("k")) * (1000 if value.endswith("k") else 1)


def source_entries(appendix):
    entries, titles, valid = {}, [], True
    text = appendix.replace("**", "")
    starts = list(re.finditer(r"(?m)^\s*(?:[-*]\s*)?\[(\d+)\]", text))
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        entry = text[match.end():end]
        links = urls(entry)
        titles.append(URL.sub("", entry.split("\n", 1)[0]))
        dated = False
        for stamp in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", URL.sub("", entry)):
            try:
                date.fromisoformat(stamp)
                dated = True
            except ValueError:
                pass
        valid &= bool(links) and dated and match[1] not in entries
        entries[match[1]] = links[0] if links else None
    return entries, bool(entries) and valid, "\n".join(titles)


def amount_markers(line, amount):
    """Pair adjacent citations with prices; a shared row citation can cover several."""
    left, right = line.rfind("|", 0, amount.start()) + 1, line.find("|", amount.end())
    right = len(line) if right < 0 else right
    clusters = list(re.finditer(r"(?:\[\d+\][ \t,]*)+", line))
    amounts = list(AMOUNT.finditer(line, left, right))
    previous = max((m.end() for m in amounts if m.end() <= amount.start()), default=left)
    following = min((m.start() for m in amounts if m.start() >= amount.end()), default=right)
    after = [m for m in clusters if amount.end() <= m.start() and m.end() <= following]
    before = [m for m in clusters if previous <= m.start() and m.end() <= amount.start()]
    chosen = after[:1] or before[-1:] or [m for m in clusters if m.end() <= left or m.start() > right]
    return list(dict.fromkeys(n for m in chosen for n in MARKER.findall(m[0])))


def words(text, letters=False):
    return [w for w in MARKER.sub("", text).split() if any(c.isalpha() if letters else c.isalnum() for c in w)]


def currency_family(token):
    token = token.upper()
    return ("USD" if token in {"US$", "USD"} else "SGD" if token in {"S$", "SG$", "SGD$", "SGD"}
            else "$" if token == "$" else "EUR" if token in {"€", "EUR"}
            else "GBP" if token in {"£", "GBP"} else "JPY")


def source_matches(match, texts):
    text = "\n".join(t for t, _ in texts)
    family = currency_family(match["pcurrency"] or match["scurrency"])
    families = {currency_family(m[0]) for m in re.finditer(r"(?<![A-Za-z])(?:" + CURRENCY + r"|円|yen)(?![A-Za-z])", text, re.I)}
    currency_ok = bool(families & {"$", "USD", "SGD"}) if family == "$" else family in families or (family in {"USD", "SGD"} and "$" in families)
    return currency_ok and numeric(match["prefix"] or match["suffix"]) in {numeric(m[0]) for m in NUMBERS.finditer(text)}


def claims_done(text):
    """Research only: first-person completed actions, never product descriptions."""
    from .checks import NEG, SENTENCE
    claim = re.compile(r"\b(?:i|we)(?:['’]ve| have)?\s+(?:successfully\s+)?(?:signed\s+you\s+up|requested\s+a\s+quote|contacted|booked|reserved|purchased|paid|submitted|cancell?ed)\b", re.I)
    return any(not NEG.search(sentence[:m.end()]) for sentence in SENTENCE.findall(text) for m in claim.finditer(sentence))


def evaluate(answer, tools):
    """Booleans stay separate from failure reasons and individual factual errors."""
    labels = sections(answer)
    appendix = labels.get("appendix")
    main = answer[:appendix[0]] if appendix else answer
    labels = {k: v for k, v in labels.items() if not appendix or v[0] < appendix[0]}
    sources, dated, titles = source_entries(appendix[1] if appendix else "")
    recommendation = labels.get("recommendation", (None, ""))[1]
    # A named option is a capitalized name, not just 'use the cheapest option'.
    names = re.findall(r"\b[A-Z][A-Za-z0-9&-]+\b", recommendation)
    start = labels.get("recommendation", (len(main), ""))[0]
    end = min((pos for pos, _ in labels.values() if pos > start), default=len(main))
    elsewhere = main[:start] + main[end:] + titles
    named = any(n.lower() not in STOP_NAMES and re.search(r"\b" + re.escape(n) + r"\b", elsewhere, re.I) for n in names)
    gaps = next((labels[k][1] for k in ("could not find", "not found", "gaps") if k in labels), "")
    checks = {}
    reasons = {}

    def check(name, ok, reason):
        checks[name] = bool(ok)
        if not ok:
            reasons[name] = reason

    check("criteria_first", "criteria" in labels and "recommendation" in labels
          and labels["criteria"][0] < labels["recommendation"][0]
          and len(words(re.sub(r"\b(?:TBD|n/a)\b", "", labels["criteria"][1], flags=re.I), True)) >= 3, "Criteria must precede Recommendation and contain three words")
    check("recommendation_reason", named and len(words(recommendation)) >= 15,
          "Recommendation must name an option and have at least 15 words")
    check("gaps_declared", len(words(re.sub(r"\b(?:TBD|n/a)\b", "", gaps, flags=re.I), True)) >= 3, "Missing or empty gaps section")
    check("one_page", appendix is not None and len(words(main)) <= 400,
          "Appendix required with at most 400 words before it")
    check("sources_dated", dated and set(MARKER.findall(main)) <= sources.keys(),
          "Every source needs a URL and ISO date; every citation needs an entry")

    fetched = fetched_sources(tools)
    errors, uncited, unverified = [], [], []
    for line in main.splitlines():
        for match in AMOUNT.finditer(line):
            markers = amount_markers(line, match)
            amount = match[0]
            if not markers:
                uncited.append(amount)
            cited = [sources.get(marker) or f"[{marker}]" for marker in markers]
            seen = [fetched[url_key(s)] for s in cited if url_key(s) in fetched]
            if markers and not any(source_matches(match, texts) for texts in seen):
                truncated = any(texts and all(cut for _, cut in texts) for texts in seen)
                reason = "source_truncated" if truncated else "not_in_source" if seen else "source_not_fetched"
                (unverified if truncated else errors).append({"amount": amount, "source": cited[0], "sources": cited, "reason": reason})
    check("amounts_cited", not uncited, "Currency amount without a same-line citation")
    check("cited_and_seen", not errors, "Cited amounts missing from fetched sources")
    return {"checks": checks, "reasons": reasons, "factual_errors": errors, "unverified": unverified}
