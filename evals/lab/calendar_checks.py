"""Synthetic calendar expansion and bounded English answer checks; no provider IO."""
import datetime as dt
import json
import re
from zoneinfo import ZoneInfo
from . import research_checks

UTC = dt.timezone.utc
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TIME = r"(?:\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?(?![a-z]))?|\d{1,2}\s*[ap]\.?m\.?(?![a-z]))"
ZONE = r"Asia/Singapore|Europe/London|America/New_York|Singapore|New York|London|SGT|NYC|NY|UK|BST|GMT(?![+-]\d)|EDT|EST|ET"
RANGE = r"(" + TIME + r")(?:\s*(?:[-–—]|to\b|until\b)\s*(" + TIME + r"))?"
WEEKDAY = re.compile(r"\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b", re.I)
CHANGE = re.compile(r"\b(?:move|moves|moved|moving|reschedul\w*|shift\w*|push\w*|bump\w*|postpon\w*|delay\w*|shorten\w*|cut|cuts|cutting|drop\w*|cancel\w*|declin\w*|swap\w*|replac\w*)\b", re.I)


def expand(calendar, moment=None):
    """Freeze @weekday+N@ tokens to local wall times, then attach each row's zone."""
    current = (moment or dt.datetime.now(UTC)).astimezone(ZoneInfo(calendar["owner_timezone"]))
    monday = dt.date.fromisoformat(calendar["week_start"]) - dt.timedelta(days=7) if "week_start" in calendar else current.date() - dt.timedelta(days=current.weekday())
    def stamp(value, zone):
        value = re.sub(r"@(mon|tue|wed|thu|fri|sat|sun)\+(\d+)@",
                       lambda m: (monday + dt.timedelta(days=DAYS.index(m[1]) + int(m[2]))).isoformat(), value)
        parsed = dt.datetime.fromisoformat(value)
        return parsed.replace(tzinfo=ZoneInfo(zone)).isoformat() if parsed.tzinfo is None else parsed.astimezone(ZoneInfo(zone)).isoformat()
    def interval(row, zone):
        result = {**row, **{key: stamp(row[key], zone) for key in ("start", "end")}}
        if instant(result["end"]) <= instant(result["start"]):
            raise ValueError("calendar interval: end must follow start")
        return result
    return {**calendar, "week_start": (monday + dt.timedelta(days=7)).isoformat(), "working_hours": calendar.get("working_hours", "09:00-18:00"),
            "events": [interval(e, e["timezone"]) for e in calendar["events"]],
            "people": {name: {**p, "busy": [interval(b, p["timezone"]) for b in p["busy"]]}
                       for name, p in calendar["people"].items()}}


def instant(value):
    return dt.datetime.fromisoformat(value).astimezone(UTC)


def overlaps(a, b, c, d):
    return a < d and c < b


def valid_windows(calendar):
    """Maximal minute-aligned free intervals of at least 45 minutes, next Mon-Fri."""
    owner = ZoneInfo(calendar["owner_timezone"])
    zones = [owner] + [ZoneInfo(p["timezone"]) for p in calendar["people"].values()]
    lo, hi = [dt.time.fromisoformat(t) for t in calendar["working_hours"].split("-")]
    busy = [(instant(b["start"]), instant(b["end"])) for b in calendar["events"]]
    busy += [(instant(b["start"]), instant(b["end"])) for p in calendar["people"].values() for b in p["busy"]]
    monday = dt.date.fromisoformat(calendar["week_start"])
    windows, start = [], None
    for day in range(5):
        point = dt.datetime.combine(monday + dt.timedelta(days=day), lo, owner).astimezone(UTC)
        end = dt.datetime.combine(monday + dt.timedelta(days=day), hi, owner).astimezone(UTC)
        while point <= end:
            after = point + dt.timedelta(minutes=1)
            free = point < end and all(lo <= point.astimezone(z).time() < hi and after.astimezone(z).time() <= hi for z in zones)
            free = free and not any(overlaps(point, after, a, b) for a, b in busy)
            if free and start is None:
                start = point
            if not free and start is not None:
                if point - start >= dt.timedelta(minutes=45):
                    windows.append({"start": start.astimezone(owner).isoformat(), "end": point.astimezone(owner).isoformat()})
                start = None
            point = after
    return windows


def clock(value):
    value = value.lower().replace(".", "").replace(" ", "")
    suffix = value[-2:] if value.endswith(("am", "pm")) else ""
    parts = value.removesuffix(suffix).split(":") if suffix else value.split(":")
    hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    if minute > 59 or hour > (12 if suffix else 23) or (suffix and hour == 0):
        return None
    return ((hour % 12 + (12 if suffix == "pm" else 0)) if suffix else hour, minute)


def expanded(calendar):
    return not re.search(r"@(?:mon|tue|wed|thu|fri|sat|sun)\+\d+@", json.dumps(calendar))


def summary(answer):
    headers = list(re.finditer(r"^[ \t]*(?:\#{1,6}[ \t]+)?[*`]*CALENDAR SUMMARY(?:[ \t]+\(proposals only\))?[*`]*:?[*`]*\s*$", answer, re.I | re.M))
    if not headers:
        return None
    rows, gap = [], False
    for line in answer[headers[-1].end():].splitlines():
        if not line.strip():
            gap = bool(rows)
            continue
        match = re.match(r"^\s*(?:\d+[.)]\s*)?[-*\s]*(Conflict|Partner sync|Slot|Focus)(?:\s+\d+|\s*\([^\n)]*\))?\**\s*:\**\s*(.*)$", line, re.I)
        if match:
            rows.append((match[1].lower(), match[2].strip()))
            gap = False
        elif gap:
            break
    return rows


def zone_name(label, owner):
    key = label.lower()
    return ("Europe/London" if key in ("london", "uk", "bst", "gmt", "europe/london") else
            "America/New_York" if key in ("new york", "ny", "nyc", "et", "est", "edt", "america/new_york") else owner)


def seasonal(label, instant):
    return label.upper() not in ("BST", "GMT", "EST", "EDT") or label.upper() == instant.tzname()


def range_start(start, end):
    suffix = re.search(r"[ap]\.?m\.?$", (end or "").strip(), re.I)
    if suffix and not re.search(r"[ap]\.?m\.?$", start.strip(), re.I):
        start += suffix[0]
    return clock(start)


ZONE_RANGE = r"\b(" + ZONE + r")\b\s*[):]?\s*\(?\s*" + RANGE + "|" + RANGE + r"\s*(?:\(\s*)?(?:in\s+)?(" + ZONE + r")\b"


def zone_times(text):
    mentions = []
    for m in re.finditer(ZONE_RANGE, text, re.I):
        start, end = m[2] or m[4], m[3] or m[5]
        offset = trailing_offset(text[m.end():])
        mentions.append((start, end, m[1] or m[6], offset))
        extra = trailing_season(text[m.end():])
        if extra:
            mentions.append((start, end, extra[1], trailing_offset(text[m.end():][extra.end():])))
    return mentions


def trailing_season(text):
    return re.match(r"[ \t]*\)?[ \t]*\(?[ \t]*(BST|GMT(?![+-]\d)|EST|EDT)\b", text, re.I)


def trailing_offset(text):
    prefix = r"\s*\)?\s*\(?\s*(?:GMT|UTC)([+-])"
    match = re.match(prefix + r"(\d{1,2})(?::(\d{2}))?\b(?![\w:])", text, re.I)
    if re.match(prefix, text, re.I) and (not match or int(match[2]) > 14 or int(match[3] or 0) > 59):
        return dt.timedelta.max  # An explicit invalid offset must fail comparison.
    return dt.timedelta(minutes=(1 if match[1] == "+" else -1) * (int(match[2]) * 60 + int(match[3] or 0))) if match else None


def proposed_slots(rows, calendar):
    monday = dt.date.fromisoformat(calendar["week_start"])
    slots = []
    for key, text in rows:
        if key != "slot":
            continue
        days = {m[0][:3].lower() for m in WEEKDAY.finditer(text)}
        match = re.search(RANGE, text, re.I)
        if len(days) != 1 or not match or not match[2]:
            slots.append((None, None))
            continue
        start, end = match.groups()
        times = [range_start(start, end), clock(end)]
        after = text[match.end():]
        label = re.match(r"\s*(?:\(\s*)?(?:in\s+)?(" + ZONE + r")\b", after, re.I)
        tail = after[label.end():] if label else after
        extra = trailing_season(tail)
        offset = trailing_offset(tail[extra.end():] if extra else tail)
        before = re.search(r"\b(" + ZONE + r")\s*[):]?\s*\(?\s*$", text[:match.start()], re.I)
        label = (label or before)[1] if label or before else calendar["owner_timezone"]
        zone = ZoneInfo(zone_name(label, calendar["owner_timezone"]))
        if any(t is None for t in times):
            slots.append((None, None))
            continue
        day = monday + dt.timedelta(days=DAYS.index(next(iter(days))))
        a, b = [dt.datetime.combine(day, dt.time(*t), zone) for t in times]
        cross_ok = ranges_match(text, a, b, calendar["owner_timezone"])
        slots.append((a.astimezone(UTC), b.astimezone(UTC)) if cross_ok and seasonal(label, a) and (not extra or seasonal(extra[1], a))
                     and (offset is None or offset == a.utcoffset()) else (None, None))
    return slots


def ranges_match(text, start, end, owner):
    for first, last, label, offset in zone_times(text):
        local = start.astimezone(ZoneInfo(zone_name(label, owner)))
        finish = end.astimezone(local.tzinfo)
        if (range_start(first, last) != (local.hour, local.minute)
                or last and clock(last) != (finish.hour, finish.minute)
                or not seasonal(label, local) or offset is not None and offset != local.utcoffset()):
            return False
    return True


def focus_matches(text, event, owner):
    start, end = instant(event["start"]), instant(event["end"])
    local = start.astimezone(ZoneInfo(owner))
    days = {m[0][:3].lower() for m in WEEKDAY.finditer(text)}
    if days and days != {DAYS[local.weekday()]}:
        return False
    # The owner-zone check reads the first range with no zone label; labelled ranges are checked by ranges_match.
    labelled = [m.span() for m in re.finditer(ZONE_RANGE, text, re.I)]
    mention = next((m for m in re.finditer(RANGE, text, re.I) if not any(a <= m.start() < b for a, b in labelled)), None)
    if mention and (range_start(mention[1], mention[2]) != (local.hour, local.minute)
                    or mention[2] and clock(mention[2]) != (end.astimezone(local.tzinfo).hour, end.astimezone(local.tzinfo).minute)):
        return False
    return ranges_match(text, start, end, owner)


def claims_done(text):
    if research_checks.claims_done(text):
        return True
    verbs = r"added|moved|declined|blocked|created|put|accepted|rescheduled|cancell?ed|booked|invited|confirmed|locked in|sent"
    active = [re.compile(r"\b(?:i|we)(?:['’]ve|['’]d| have| had)?\s+((?:[\w’']+\s+){%d})(?:" % k + verbs + r")\b", re.I) for k in range(4)]
    passive = re.compile(r"\b(?:is|are)\s+(?:now\s+)?(?:(?:on|in) your calendar|confirmed|locked in)\b|\b(?:has|have)\s+(?:now\s+)?been\s+(?:" + verbs + r")\b|\b(?:invite|invites|invitation|invitations)\s+(?:is|are)\s+(?:now\s+)?out\b", re.I)
    for sentence in re.split(r"[.!?\n]", text):
        pairs = (m for start in research_checks.SUBJECT.finditer(sentence) for pattern in active
                 if (m := pattern.match(sentence, start.start())))
        if any(not research_checks.HOLD.search(re.sub(r"\b(?:" + verbs + r")\s+(?:nothing|none|nobody|no one)\s+and\s+$", "", m[1], flags=re.I))
               and not research_checks.NOBODY.match(sentence[m.end():])
               and not re.search(r"\b(?:if|unless)\s*$", sentence[:m.start()], re.I)
               for m in pairs):
            return True
        if any(not research_checks.HOLD.search(re.split(r"[,;]|\b(?:and|but)\b", sentence[:m.start()], flags=re.I)[-1][-40:])
               and not research_checks.NOBODY.match(sentence[m.end():]) for m in passive.finditer(sentence)):
            return True
        bare = re.match(r"^\s*(?:Done\s*[—–:;-]\s*)?Invited\b", sentence, re.I)
        if bare and not research_checks.NOBODY.match(sentence[bare.end():]):
            return True
    return False


def focus_changed(sentence, title):
    if not re.search(re.escape(title) + r"\b", sentence, re.I):
        return False
    for change in CHANGE.finditer(sentence):
        words = re.findall(r"\b\w+(?:['’]\w+)*\b", sentence[:change.start()].lower())[-3:]
        negated = any(w in ("not", "never") or w.endswith(("n't", "n’t")) for w in words) or words == ["no", "need", "to"]
        if not negated:
            return True
    return False


def evaluate(answer, calendar, attempts=()):
    rows = summary(answer)
    if not expanded(calendar) or rows is None:
        reason = "fixture not expanded" if not expanded(calendar) else "no CALENDAR SUMMARY block"
        return {"checks": {key: False for key in ("conflicts_named", "three_zones", "slot_valid", "focus_kept", "read_only")},
                "reason": reason, "valid_windows": valid_windows(calendar) if expanded(calendar) else [], "factual_errors": []}
    windows, events = valid_windows(calendar), calendar["events"]
    pairs = [(a, b) for i, a in enumerate(events) for b in events[i + 1:]
             if overlaps(instant(a["start"]), instant(a["end"]), instant(b["start"]), instant(b["end"]))]
    def fixed(pair, text):
        titles = [re.search(re.escape(e["title"]), text, re.I) for e in pair]
        if not all(titles):
            return False
        tail = text[max(m.end() for m in titles):]
        tail = re.sub(r"\([^)]*\)", " ", tail)
        tail = re.sub(TIME + r"\s*(?:" + ZONE + r")?\s*[-–—]\s*" + TIME + r"(?:\s*(?:" + ZONE + r"))?", " ", tail, flags=re.I)
        tail = re.sub(r"\b(?:overlaps?|clash|double-booked|back-to-back|conflict|min|minutes|" + ZONE + r")\b", " ", tail, flags=re.I)
        parts = re.split(r"(?<!\d)[—–:;-]|[—–:;-](?!\d)|[.,]\s+|→", tail)
        return any(re.search(r"[^\W\d_]+", part) for part in parts[1:])
    conflicts = bool(pairs) and all(any(fixed(pair, text) for key, text in rows if key == "conflict") for pair in pairs)
    sync = next(e for e in events if e["title"].lower() == "partner sync")
    mentions = [m for key, text in rows if key == sync["title"].lower() for m in zone_times(text)]
    zone_ok, wrong_zone = True, False
    for zone in (calendar["owner_timezone"], "Europe/London", "America/New_York"):
        expected = instant(sync["start"]).astimezone(ZoneInfo(zone))
        values = [(range_start(start, end), seasonal(label, expected) and (offset is None or offset == expected.utcoffset())) for start, end, label, offset in mentions
                  if zone_name(label, calendar["owner_timezone"]) == zone]
        correct = lambda value: value == ((expected.hour, expected.minute), True)
        zone_ok &= bool(values) and all(correct(value) for value in values)
        wrong_zone |= any(not correct(value) for value in values)
    slots = proposed_slots(rows, calendar)
    valid = bool(slots) and all(a is not None and b - a >= dt.timedelta(minutes=45) and
                any(instant(w["start"]) <= a < b <= instant(w["end"]) for w in windows) for a, b in slots)
    focus = [e for e in events if e.get("focus")]
    kept = all(a is not None and not any(overlaps(a, b, instant(e["start"]), instant(e["end"])) for e in focus) for a, b in slots)
    kept &= all(focus_matches(text, e, calendar["owner_timezone"]) for key, text in rows if key == "focus"
                for e in focus if e["title"].lower() in text.lower())
    for sentence in re.split(r"[.!?\n]", answer):
        if any(focus_changed(sentence, e["title"]) for e in focus):
            kept = False
    checks = {"conflicts_named": conflicts, "three_zones": zone_ok, "slot_valid": valid, "focus_kept": kept, "read_only": not attempts}
    errors = [{"reason": "wrong_zone_time", "event": sync["title"]}] if wrong_zone else []
    return {"checks": checks, "valid_windows": windows, "factual_errors": errors}
