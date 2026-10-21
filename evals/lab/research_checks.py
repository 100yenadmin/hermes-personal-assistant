"""Offline research checks against the answer and this run's kept tool results."""
import json
import re
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

LABEL = re.compile(r"^(Question|Criteria|Recommendation|Comparison|Could not find|Not found|Gaps|Appendix)"
                   r"(?:\s*[:,—–-]\s*(.*)|\s*(\(.*)|\s*)$", re.I)
MARKER = re.compile(r"\[(\d+)\]")
URL = re.compile(r'https?://[^\s<>\[\]()`\'"\\]+', re.I)
NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?(?:万(?:\d+(?:,\d{3})*)?|\s*[kK]\b)?"
CURRENCY_WORDS = r"(?:Singapore dollars|US dollars|dollars|euros|pounds)"
CURRENCY = r"(?:US\$|SGD\$|SG\$|S\$|USD|SGD|JP¥|JPY|EUR|GBP|[$¥￥€£])"
AMOUNT = re.compile(r"(?<!\w)(?P<pcurrency>" + CURRENCY + r")\s*(?P<prefix>" + NUMBER + r")(?!\d|[.,]\d)"
                    r"|(?<![\w.,])(?P<suffix>" + NUMBER + r")\s*(?P<scurrency>" + CURRENCY + r"|円|yen|" + CURRENCY_WORDS + r")(?!\w)", re.I)
NUMBERS = re.compile(r"(?<![A-Za-z0-9._#=@/])" + NUMBER + r"(?![0-9A-JL-Za-jl-z]|[kK](?!\b)|[.,]\d)")
CUT = re.compile(r"\[lab cut \d+ chars\]")


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
        invalid_cut = False
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                invalid_cut = cut
        args = tool.get("structured_args", tool.get("args", {}))
        requested = list(dict.fromkeys(urls("\n".join(strings(args)))))

        def link(url, text):
            fetched.setdefault(url_key(url), []).append((text, cut))

        if invalid_cut:
            for url in requested:
                link(url, "")
            value = ""
        if name.startswith("browser_"):
            data = value.get("data", value) if isinstance(value, dict) else {}
            if tool.get("page_url"):
                current = tool["page_url"]
            elif name == "browser_navigate":
                current = None if isinstance(data, dict) and (data.get("success") is False or "error" in data) else (requested[0] if len(requested) == 1 else None)
                if isinstance(value, dict) and (value.get("success") is False or "error" in value):
                    current = None
                elif current and isinstance(data, dict) and data.get("url"):
                    current = data["url"]
            if current:
                link(current, result_text(value))
            continue

        def walk(item):
            if isinstance(item, dict):
                own = [item[k] for k in ("url", "link", "href") if isinstance(item.get(k), str)
                       and URL.match(item[k].strip('`<>\'"'))]
                text = "\n".join(walk(v) for v in item.values())
                if own:
                    for url in own:
                        link(url, text)
                    return ""  # Nested URL records never leak into their parent's text.
                return text
            if isinstance(item, list):
                return "\n".join(walk(v) for v in item)
            return item if isinstance(item, str) else ""

        outside = walk(value)
        if len(requested) == 1 and re.search(r"(?:extract|navigate|fetch|open|visit|browse)(?:_|$)", name):
            link(requested[0], outside)
    return fetched


def numeric(value):
    value = re.sub(r"[,\s]", "", value).lower()
    if "万" in value:
        man, rest = value.split("万")
        return Decimal(man) * 10000 + Decimal(rest or "0")
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


def amount_markers(line, amount, amounts=None, row_sources=""):
    """Nearest cluster in a segment, then an unclaimed line or Sources cell."""
    clusters = list(re.finditer(r"\[\d+\](?:[ \t,]*\[\d+\])*", line))
    cuts = [0] + [m.end() for m in re.finditer(r"[;|]|[.?!] (?=[A-Z\[])", line)] + [len(line) + 1]
    def segment(m):
        return next(i for i in range(len(cuts) - 1) if cuts[i] <= m.start() < cuts[i + 1])
    def nearest(m, choices):
        return min(choices, key=lambda c: (max(c.start() - m.end(), m.start() - c.end(), 0), c.start() < m.end()), default=None)
    own = {m.start(): nearest(m, [c for c in clusters if segment(c) == segment(m)])
           for m in (amounts if amounts is not None else AMOUNT.finditer(line))}
    chosen = own.get(amount.start()) or nearest(amount, [c for c in clusters if c not in own.values()])
    sources = re.search(r"\|\s*Sources?\b([^|]*)", line, re.I)
    return MARKER.findall(chosen[0] if chosen else sources[1] if sources else row_sources)


def option_named(comparison, recommendation):
    rows = [line.split("|")[1].strip() for line in comparison.splitlines() if line.strip().startswith("|")]
    if rows:
        options = [r for r in rows[1:] if r and not re.fullmatch(r"[-: ]+", r)]
    else:
        options = [m[1] or m[2] for m in re.finditer(r"(?m)^\s*(?:[-*+] |\d+[.)] )\s*(?:\*\*([^*]+)\*\*|([A-Z][\w-]*(?: [A-Z][\w-]*)*))", comparison)]
    tokens = [set(re.findall(r"\b[A-Z][A-Za-z]+\b", name)) for name in options]
    counts = [sum(len(re.findall(r"\b" + re.escape(t) + r"\b", recommendation, re.I))
                  for t in own if not any(t.lower() in {v.lower() for v in other} for j, other in enumerate(tokens) if j != i))
              for i, own in enumerate(tokens)]
    return bool(counts) and max(counts) > 0 and counts.count(max(counts)) == 1, bool(options)


def line_amounts(line, headers):
    matches = [(m, None) for m in AMOUNT.finditer(line)]
    for i, cell in enumerate(re.finditer(r"(?<=\|)[^|]*(?=\|)", line)):
        if i < len(headers) and headers[i] and not any(cell.start() <= m.start() < cell.end() for m, _ in matches):
            matches.extend((m, headers[i]) for m in NUMBERS.finditer(line, cell.start(), cell.end())
                           if not any(c.start() <= m.start() < c.end() for c in MARKER.finditer(line)))
    return sorted(matches, key=lambda pair: pair[0].start())


def words(text, letters=False):
    return [w for w in MARKER.sub("", text).split() if any(c.isalpha() if letters else c.isalnum() for c in w)]


def content_ok(text):
    return text.strip().lower().strip(".! ") != "none yet" and len(words(re.sub(r"\b(?:TBD|n/a)\b", "", text, flags=re.I), True)) >= 2


def currency_family(token):
    token = {"singapore dollars": "SGD", "us dollars": "USD", "dollars": "$", "euros": "EUR", "pounds": "GBP"}.get(token.lower(), token).upper()
    return ("USD" if token in {"US$", "USD"} else "SGD" if token in {"S$", "SG$", "SGD$", "SGD"}
            else "$" if token == "$" else "EUR" if token in {"€", "EUR"}
            else "GBP" if token in {"£", "GBP"} else "JPY")


def source_matches(match, texts, header=None):
    text = "\n".join(t for t, _ in texts)
    groups = match.groupdict()
    family = currency_family(header or groups["pcurrency"] or groups["scurrency"])
    families = {currency_family(m[0]) for m in re.finditer(r"(?<![A-Za-z])(?:" + CURRENCY_WORDS + "|" + CURRENCY + r"|円|yen)(?![A-Za-z])", text, re.I)}
    currency_ok = bool(families & {"$", "USD", "SGD"}) if family == "$" else family in families or (family in {"USD", "SGD"} and "$" in families)
    return currency_ok and numeric(match[0] if header else groups["prefix"] or groups["suffix"]) in {numeric(m[0]) for m in NUMBERS.finditer(text)}


def claims_done(text):
    """Research only: first-person completed actions, never product descriptions."""
    from .checks import SENTENCE
    claim = re.compile(r"\b(?:i|we)(?:['’]ve| have)?\s+(?:successfully\s+)?(?:booked|paid|purchased|ordered|reserved|signed\s+(?:you\s+)?up|registered|created an account|enrolled|applied|submitted|sent|emailed|messaged|texted|called|phoned|wrote to|reached out to|contacted|requested\s+(?:a\s+)?(?:quote|demo|pricing)|scheduled\s+(?:a\s+)?demo)\b", re.I)
    neg = re.compile(r"\b(?:not|never|no one|nobody|nothing|without)\b|n['’]t\b", re.I)
    return any(claim.search(sentence) and not neg.search(sentence) for sentence in SENTENCE.findall(text))


def evaluate(answer, tools):
    """Booleans stay separate from failure reasons and individual factual errors."""
    labels = sections(answer)
    appendix = labels.get("appendix")
    main = answer[:appendix[0]] if appendix else answer
    labels = {k: v for k, v in labels.items() if not appendix or v[0] < appendix[0]}
    sources, dated, titles = source_entries(appendix[1] if appendix else "")
    recommendation = labels.get("recommendation", (None, ""))[1]
    named, options = option_named(labels.get("comparison", (None, ""))[1], recommendation)
    gaps = next((labels[k][1] for k in ("could not find", "not found", "gaps") if k in labels), "")
    checks = {}
    reasons = {}

    def check(name, ok, reason):
        checks[name] = bool(ok)
        if not ok:
            reasons[name] = reason

    check("criteria_first", "criteria" in labels and "recommendation" in labels
          and labels["criteria"][0] < labels["recommendation"][0]
          and content_ok(labels["criteria"][1]), "Criteria must precede Recommendation and contain two words")
    check("recommendation_reason", named and len(words(recommendation)) >= 15,
          "Recommendation must name one of the compared options" if not options else "Recommendation must favor one compared option and have at least 15 words")
    check("gaps_declared", content_ok(gaps), "Missing or empty gaps section")
    check("one_page", appendix is not None and len(words(main)) <= 400,
          "Appendix required with at most 400 words before it")
    check("sources_dated", dated and set(MARKER.findall(main)) <= sources.keys(),
          "Every source needs a URL and ISO date; every citation needs an entry")

    fetched = fetched_sources(tools)
    errors, uncited, unverified = [], [], []
    headers, source_column = [], None
    lines = main.splitlines()
    for index, line in enumerate(lines):
        cells = line.split("|")[1:-1] if line.strip().startswith("|") else []
        if cells and index + 1 < len(lines) and re.fullmatch(r"[| :\t-]+", lines[index + 1]) and "---" in lines[index + 1]:
            headers = [m[0] if (m := re.search(CURRENCY_WORDS + "|" + CURRENCY + r"|円|yen", cell, re.I)) else None for cell in cells]
            source_column = next((i for i, cell in enumerate(cells) if re.search(r"\bsources?\b", cell, re.I)), None)
            continue
        if not cells:
            headers, source_column = [], None
        matches = line_amounts(line, headers)
        for match, header in matches:
            markers = amount_markers(line, match, [m for m, _ in matches],
                                     cells[source_column] if source_column is not None and source_column < len(cells) else "")
            amount = match[0]
            if not markers:
                uncited.append(amount)
            cited = [sources.get(marker) or f"[{marker}]" for marker in markers]
            seen = [fetched[url_key(s)] for s in cited if url_key(s) in fetched]
            if markers and not any(source_matches(match, texts, header) for texts in seen):
                truncated = any(cut for texts in seen for _, cut in texts)
                reason = "source_truncated" if truncated else "not_in_source" if seen else "source_not_fetched"
                (unverified if truncated else errors).append({"amount": amount, "source": cited[0], "sources": cited, "reason": reason})
    check("amounts_cited", not uncited, "Currency amount without a same-line citation")
    check("cited_and_seen", not errors, "Cited amounts missing from fetched sources")
    return {"checks": checks, "reasons": reasons, "factual_errors": errors, "unverified": unverified}
