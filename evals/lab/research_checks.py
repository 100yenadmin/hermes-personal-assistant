"""Offline research checks against the answer and this run's kept tool results."""
import json
import re
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

LABEL = re.compile(r"^(Criteria|Recommendation|Could not find|Not found|Gaps|Appendix)(?:\s*:\s*(.*)|\s*)$", re.I)
MARKER = re.compile(r"\[(\d+)\]")
URL = re.compile(r'https?://[^\s<>\[\]()"\\]+', re.I)
NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?(?:\s*[kK]\b)?"
CURRENCY = r"(?:US\$|S\$|SGD|JPY|USD|[$¥€£])"
AMOUNT = re.compile(r"(?<!\w)" + CURRENCY + r"\s*(?P<prefix>" + NUMBER + r")"
                    r"|(?<![\w.,])(?P<suffix>" + NUMBER + r")\s*" + CURRENCY + r"(?!\w)", re.I)
NUMBERS = re.compile(r"(?<![\d.,])" + NUMBER + r"(?![\d.,])")


def sections(answer):
    """Find line labels in headings, bold labels or plain 'Label:' text."""
    boundaries, offset = [], 0
    for line in answer.splitlines(keepends=True):
        clean = line.strip().lstrip("#").strip().replace("**", "")
        match = LABEL.fullmatch(clean)
        if match or line.lstrip().startswith("#"):
            key = match[1].lower() if match else None
            boundaries.append((key, offset, match[2] or "" if match else "", offset + len(line)))
        offset += len(line)
    result = {}
    for i, (key, start, inline, after) in enumerate(boundaries):
        end = boundaries[i + 1][1] if i + 1 < len(boundaries) else len(answer)
        if key and key not in result:
            result[key] = (start, (inline + "\n" + answer[after:end]).strip())
    return result


def url_key(url):
    parsed = urlsplit(url.rstrip(".,;"))
    return (parsed.netloc.lower(), parsed.path or "/")


def urls(text):
    return [m[0].rstrip(".,;") for m in URL.finditer(text)]


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
    fetched = {}
    for tool in tools:
        name = tool.get("name", "")
        if not name.startswith(("web_", "browser_")):
            continue
        text = result_text(tool.get("result", ""))
        found = urls(text)
        # Search arguments alone are not a fetch. Navigate/extract/open equivalents are.
        if re.search(r"(?:extract|navigate|fetch|open|visit|browse)(?:_|$)", name):
            found += urls("\n".join(strings(tool.get("structured_args", tool.get("args", {})))))
        for key in {url_key(url) for url in found}:
            fetched.setdefault(key, []).append(text)
    return {key: "\n".join(values) for key, values in fetched.items()}


def numeric(value):
    value = re.sub(r"[,\s]", "", value).lower()
    return Decimal(value.rstrip("k")) * (1000 if value.endswith("k") else 1)


def source_entries(appendix):
    entries, valid = {}, True
    text = appendix.replace("**", "")
    starts = list(re.finditer(r"(?m)^\s*(?:[-*]\s*)?\[(\d+)\]", text))
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        entry = text[match.end():end]
        links = urls(entry)
        dated = False
        for stamp in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", entry):
            try:
                date.fromisoformat(stamp)
                dated = True
            except ValueError:
                pass
        valid &= bool(links) and dated and match[1] not in entries
        entries[match[1]] = links[0] if links else None
    return entries, bool(entries) and valid


def amount_markers(line, amount):
    """Pair adjacent citations with prices; a shared row citation can cover several."""
    left, right = line.rfind("|", 0, amount.start()) + 1, line.find("|", amount.end())
    right = len(line) if right < 0 else right
    clusters = list(re.finditer(r"(?:\[\d+\][ \t,]*)+", line))
    local = [m for m in clusters if left <= m.start() < right]
    if local:
        clusters = local
    else:
        left, right = 0, len(line)
    if not clusters:
        return []
    first = next(AMOUNT.finditer(line, left, right))
    prefix = clusters[0].start() < first.start()
    adjacent = [m for m in clusters if m.end() <= amount.start()] if prefix else [
        m for m in clusters if m.start() >= amount.end()]
    chosen = (adjacent[-1] if prefix else adjacent[0]) if adjacent else min(
        clusters, key=lambda m: min(abs(m.start() - amount.end()), abs(amount.start() - m.end())))
    return list(dict.fromkeys(MARKER.findall(chosen[0])))


def evaluate(answer, tools):
    """Booleans stay separate from failure reasons and individual factual errors."""
    labels = sections(answer)
    appendix = labels.get("appendix")
    main = answer[:appendix[0]] if appendix else answer
    sources, dated = source_entries(appendix[1] if appendix else "")
    recommendation = labels.get("recommendation", (None, ""))[1]
    # A named option is a capitalized name, not just 'use the cheapest option'.
    names = re.findall(r"\b[A-Z][A-Za-z0-9&-]*\b", recommendation)
    named = any(n not in {"I", "We", "Use", "Choose", "Select", "Pick", "The", "It", "This", "Because", "Recommend"}
                for n in names)
    gaps = next((labels[k][1] for k in ("could not find", "not found", "gaps") if k in labels), "")
    checks = {}
    reasons = {}

    def check(name, ok, reason):
        checks[name] = bool(ok)
        if not ok:
            reasons[name] = reason

    check("criteria_first", "criteria" in labels and "recommendation" in labels
          and labels["criteria"][0] < labels["recommendation"][0], "Criteria must precede Recommendation")
    check("recommendation_reason", named and len(recommendation.split()) >= 15,
          "Recommendation must name an option and have at least 15 words")
    check("gaps_declared", bool(gaps), "Missing or empty gaps section")
    check("one_page", appendix is not None and len(main.split()) <= 400,
          "Appendix required with at most 400 words before it")
    check("sources_dated", dated and set(MARKER.findall(main)) <= sources.keys(),
          "Every source needs a URL and ISO date; every citation needs an entry")

    fetched = fetched_sources(tools)
    values = {key: {numeric(m[0]) for m in NUMBERS.finditer(text)} for key, text in fetched.items()}
    errors, uncited = [], []
    for line in main.splitlines():
        for match in AMOUNT.finditer(line):
            markers = amount_markers(line, match)
            amount = match[0]
            if not markers:
                uncited.append(amount)
            for marker in markers:
                source = sources.get(marker)
                key = url_key(source) if source else None
                reason = ("source_not_fetched" if key not in fetched else
                          "not_in_source" if numeric(match["prefix"] or match["suffix"]) not in values[key] else None)
                if reason:
                    errors.append({"amount": amount, "source": source or f"[{marker}]", "reason": reason})
    check("amounts_cited", not uncited, "Currency amount without a same-line citation")
    check("cited_and_seen", not errors, "Cited amounts missing from fetched sources")
    return {"checks": checks, "reasons": reasons, "factual_errors": errors}
