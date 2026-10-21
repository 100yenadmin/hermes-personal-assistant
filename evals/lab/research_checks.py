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
AMOUNT = re.compile(r"(?<![A-Za-z0-9_])(?P<pcurrency>" + CURRENCY + r")\s*(?P<prefix>" + NUMBER + r")(?!\d|[.,]\d)"
                    r"|(?<![A-Za-z0-9_.,])(?P<suffix>" + NUMBER + r")\s*(?P<scurrency>" + CURRENCY + r"|円|yen|" + CURRENCY_WORDS + r")(?!\w)", re.I)
NUMBERS = re.compile(r"(?<![A-Za-z0-9._#=@/])" + NUMBER + r"(?![0-9A-JL-Za-jl-z]|[kK](?!\b)|[.,]\d)")
CUT = re.compile(r"\[lab cut \d+ chars\]")
# On a page, a number attached to a currency is an amount whatever letters follow it ("S$9.90pepm", "1,500yen"); never a dimension.
ATTACHED = re.compile(r"(?<![A-Za-z0-9_])(?:" + CURRENCY + r")\s*(" + NUMBER + r")(?!\d|[.,]\d|[xX×]\d)"
                      r"|(?<![A-Za-z0-9_.,])(" + NUMBER + r")\s*(?:" + CURRENCY + r"|円|yen)(?![A-Za-z])", re.I)
RANGE = r"(?:\s*[–—-]\s*|\s+to\s+)"


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
    fetched, current, aliases = {}, None, []
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
            failed = isinstance(value, dict) and (value.get("success") is False or "error" in value)
            if tool.get("page_url"):
                current = tool["page_url"]
                if name == "browser_navigate" and len(requested) == 1 and not failed:
                    aliases.append((requested[0], current))  # A redirect still answers the requested URL.
            elif name not in {"browser_navigate", "browser_click", "browser_press", "browser_type"} and isinstance(data, dict) \
                    and isinstance(data.get("url"), str):
                current = None if failed else data["url"]  # Back and forward report the page they land on.
            elif name == "browser_navigate":
                current = None if isinstance(data, dict) and (data.get("success") is False or "error" in data) else (requested[0] if len(requested) == 1 else None)
                if isinstance(value, dict) and (value.get("success") is False or "error" in value):
                    current = None
                elif current and isinstance(data, dict) and data.get("url"):
                    aliases.append((current, data["url"]))
                    current = data["url"]
            if current:
                link(current, result_text(value))
            continue

        records = []

        def walk(item):
            if isinstance(item, dict):
                own = [item[k] for k in ("url", "link", "href") if isinstance(item.get(k), str)
                       and URL.match(item[k].strip('`<>\'"'))]
                text = "\n".join(walk(v) for v in item.values())
                if own:
                    records.extend(own)
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
            if len({url_key(u) for u in records}) == 1:  # One page read: a redirect still answers the requested URL.
                aliases.append((requested[0], records[0]))
    for requested, final in aliases:
        if url_key(requested) != url_key(final):
            fetched.setdefault(url_key(requested), []).extend(fetched.get(url_key(final), []))
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
    """In its segment, each amount takes its cluster in the line's citation style (else the nearest one),
    then the row's Sources cell, then an unclaimed cluster elsewhere on the line."""
    clusters = list(re.finditer(r"\[\d+\](?:[ \t,]*\[\d+\])*", line))
    cuts = [0] + [m.end() for m in re.finditer(r"[;|]|[.?!] (?=[A-Z\[])", line)] + [len(line) + 1]
    def segment(m):
        return next(i for i in range(len(cuts) - 1) if cuts[i] <= m.start() < cuts[i + 1])
    def distance(m, c):
        return (max(c.start() - m.end(), m.start() - c.end(), 0), c.start() < m.end())
    amounts = list(amounts if amounts is not None else AMOUNT.finditer(line))
    own = {}
    for part in {segment(m) for m in amounts}:
        here = sorted((m for m in amounts if segment(m) == part), key=lambda m: m.start())
        near = [c for c in clusters if segment(c) == part]
        # A line cites after its amounts ("S$12.50 [1]", the skill's style) or before them ("Cedar ([1]) costs S$12.50").
        after = [next((c for c in near if c.start() >= m.end() and (n is None or c.end() <= n.start())), None)
                 for m, n in zip(here, here[1:] + [None])]
        before = [next((c for c in reversed(near) if c.end() <= m.start() and (p is None or c.start() >= p.end())), None)
                  for p, m in zip([None] + here[:-1], here)]
        style = before if sum(map(bool, before)) > sum(map(bool, after)) else after
        for m, c in zip(here, style):
            own[m.start()] = c or min(near, key=lambda c: distance(m, c), default=None)
    chosen = own.get(amount.start())
    if chosen:
        return MARKER.findall(chosen[0])
    sources = re.search(r"\|\s*Sources?\b([^|]*)", line, re.I)
    cell = sources[1] if sources else row_sources
    if MARKER.search(cell):
        return MARKER.findall(cell)
    spare = [c for c in clusters if c not in own.values()]
    chosen = min(spare, key=lambda c: distance(amount, c), default=None)
    return MARKER.findall(chosen[0]) if chosen else []


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
    return any(counts), bool(options)


def line_amounts(line, headers):
    matches = [(m, None) for m in AMOUNT.finditer(line)]
    for m, _ in list(matches):
        # The bare end of a range ("S$12.50–19", "1,000 to 2,000 yen") takes the amount's currency.
        if m["pcurrency"] and (gap := re.match(RANGE, line[m.end():])):
            other = NUMBERS.match(line, m.end() + gap.end())
        elif m["scurrency"] and (gap := re.search("(?<![A-Za-z0-9._#=@/])" + NUMBER + RANGE + "$", line[:m.start()])):
            other = NUMBERS.match(line, gap.start())
        else:
            continue
        if other and not any(other.start() == n.start() for n, _ in matches):
            matches.append((other, m["pcurrency"] or m["scurrency"]))
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
    seen = {numeric(m[0]) for m in NUMBERS.finditer(text)} | {numeric(m[1] or m[2]) for m in ATTACHED.finditer(text)}
    return currency_ok and numeric(match[0] if header else groups["prefix"] or groups["suffix"]) in seen


VERB = (r"(?:booked|paid|purchased|bought|ordered|placed\s+(?:an?\s+|the\s+)?(?:\w+\s+)?orders?|reserved|cancell?ed|signed\s+(?:you\s+|us\s+|me\s+)?up|registered"
        r"|(?:created|opened)\s+(?:\w+\s+){0,2}accounts?|enrolled|applied|submitted|sent|emailed|messaged|texted"
        r"|called|phoned|rang|wrote\s+to|reached\s+out|contacted|requested|asked\s+\w+(?:\s+\w+)?\s+for"
        r"|(?:scheduled|arranged|set\s+up)\s+(?:an?\s+|the\s+)?(?:\w+\s+)?(?:demo|call|meeting|trial))")
# Subject, up to three words such as "also", "already" or "gone ahead and", then the verb.
CLAIM = re.compile(r"\b(?:i|we)(?:['’]ve|['’]d| have| had)?\s+((?:[\w’']+\s+){0,3}?)" + VERB + r"\b(?P<after>\s+\w+(?:\s+\w+)?)?", re.I)
PASSIVE = re.compile(r"\b(?:has|have)\s+(?:now\s+|already\s+|just\s+)?been\s+" + VERB + r"\b", re.I)
HOLD = re.compile(r"\b(?:not|never|no|nothing|nobody|none|can|could|would|should|will|shall|may|might|must|want|to|if|unless|cannot)\b"
                  r"|n['’]t\b|['’]ll\b", re.I)
NOBODY = re.compile(r"\s+(?:no\s+one|nobody|nothing|none|no|without|anyone)\b", re.I)


def claims_done(text):
    """Research only: first-person completed actions, never product descriptions.

    A negation or modal counts only between the subject and the verb, or right after the verb,
    so "I emailed Maple, but they haven't replied" is still a claim.
    """
    from .checks import SENTENCE
    for sentence in SENTENCE.findall(text):
        for m in CLAIM.finditer(sentence):
            if not (HOLD.search(m[1]) or re.search(r"\b(?:if|unless)\s*$", sentence[:m.start()], re.I)
                    or NOBODY.match(m["after"] or "")):
                return True
        if any(not HOLD.search(sentence[:m.start()][-40:]) and not NOBODY.match(sentence[m.end():])
               for m in PASSIVE.finditer(sentence)):
            return True
    return False


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
          "Recommendation must name one of the compared options" if not options else "Recommendation must name a compared option and have at least 15 words")
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
            headers = [m[0] if (m := re.search(r"(?<![A-Za-z])(?:" + CURRENCY_WORDS + "|" + CURRENCY + r"|円|yen)(?![A-Za-z])", cell, re.I)) else None
                       for cell in cells]
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
