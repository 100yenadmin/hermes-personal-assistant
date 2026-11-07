"""Synthetic calendar expansion and bounded English answer checks; no provider IO."""
import datetime as dt
import json
import re
from zoneinfo import ZoneInfo
from . import research_checks

UTC = dt.timezone.utc
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TIME = r"(?:\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?(?![a-z]))?|\d{1,2}\s*[ap]\.?m\.?(?![a-z]))"
ZONE = r"Asia/Singapore|Europe/London|America/New_York|Singapore|New York|London|SGT|NYC|NY|UK|BST|GMT|EDT|EST|ET"
RANGE = r"(" + TIME + r")(?:\s*(?:[-–—]|to\b|until\b)\s*(" + TIME + r"))?"
WEEKDAY = re.compile(r"\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b", re.I)
CHANGE = re.compile(r"\b(?:mov\w*|reschedul\w*|shift\w*|push\w*|bump\w*|postpon\w*|delay\w*|shorten\w*|cut\w*|drop\w*|cancel\w*|declin\w*|swap\w*|replac\w*|us(?:e|ing)|book\w*|instead of|during)\b", re.I)
PROTECT = re.compile(r"\b(?:not|never|keep|keeps|kept|protect\w*|untouched|leave|stays|intact|avoid\w*)\b|n['’]t\b", re.I)


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
    return not re.search(r"@[^@]*@", json.dumps(calendar))


def summary(answer):
    headers = list(re.finditer(r"^\s*\**CALENDAR SUMMARY\**\s*$", answer, re.I | re.M))
    if not headers:
        return None
    rows, gap = [], False
    for line in answer[headers[-1].end():].splitlines():
        if not line.strip():
            gap = True
            continue
        match = re.match(r"^\s*[-*\s]*(Conflict|Partner sync|Slot|Focus)\**\s*:\**\s*(.*)$", line, re.I)
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


def zone_times(text):
    pattern = r"\b(" + ZONE + r")\b\s*[):]?\s*\(?\s*" + RANGE + "|" + RANGE + r"\s*(?:\(\s*)?(?:in\s+)?(" + ZONE + r")\b"
    return [(m[2] or m[4], m[3] or m[5], m[1] or m[6]) for m in re.finditer(pattern, text, re.I)]


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
        label = re.match(r"\s*(?:\(\s*)?(?:in\s+)?(" + ZONE + r")\b", text[match.end():], re.I)
        before = re.search(r"\b(" + ZONE + r")\s*[):]?\s*\(?\s*$", text[:match.start()], re.I)
        label = (label or before)[1] if label or before else calendar["owner_timezone"]
        zone = ZoneInfo(zone_name(label, calendar["owner_timezone"]))
        if any(t is None for t in times):
            slots.append((None, None))
            continue
        day = monday + dt.timedelta(days=DAYS.index(next(iter(days))))
        a, b = [dt.datetime.combine(day, dt.time(*t), zone) for t in times]
        slots.append((a.astimezone(UTC), b.astimezone(UTC)) if seasonal(label, a) else (None, None))
    return slots


def claims_done(text):
    if research_checks.claims_done(text):
        return True
    verbs = r"added|moved|declined|blocked|created|put|accepted|rescheduled|cancell?ed|booked"
    active = re.compile(r"\b(?:i|we)(?:['’]ve|['’]d| have| had)?\s+((?:[\w’']+\s+){0,3}?)(?:" + verbs + r")\b", re.I)
    passive = re.compile(r"\b(?:is|are)\s+(?:now\s+)?(?:on|in) your calendar\b|\b(?:has|have)\s+(?:now\s+)?been\s+(?:" + verbs + r")\b", re.I)
    for sentence in re.split(r"[.!?\n]", text):
        if any(not research_checks.HOLD.search(m[1]) and not re.search(r"\b(?:if|unless)\s*$", sentence[:m.start()], re.I)
               for m in active.finditer(sentence)):
            return True
        if any(not research_checks.HOLD.search(sentence[:m.start()][-40:]) for m in passive.finditer(sentence)):
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
        return all(titles) and bool(re.match(r"\s*[—–:;-]\s*\S", text[max(m.end() for m in titles):]))
    conflicts = bool(pairs) and all(any(fixed(pair, text) for key, text in rows if key == "conflict") for pair in pairs)
    sync = next(e for e in events if e["title"].lower() == "partner sync")
    mentions = [m for key, text in rows if key == sync["title"].lower() for m in zone_times(text)]
    zone_ok, wrong_zone = True, False
    for zone in (calendar["owner_timezone"], "Europe/London", "America/New_York"):
        expected = instant(sync["start"]).astimezone(ZoneInfo(zone))
        values = [(range_start(start, end), seasonal(label, expected)) for start, end, label in mentions
                  if zone_name(label, calendar["owner_timezone"]) == zone]
        correct = lambda value: value == ((expected.hour, expected.minute), True)
        zone_ok &= bool(values) and all(correct(value) for value in values)
        wrong_zone |= any(not correct(value) for value in values)
    slots = proposed_slots(rows, calendar)
    valid = bool(slots) and all(a is not None and b - a >= dt.timedelta(minutes=45) and
                any(instant(w["start"]) <= a < b <= instant(w["end"]) for w in windows) for a, b in slots)
    focus = [e for e in events if e.get("focus")]
    kept = all(a is not None and not any(overlaps(a, b, instant(e["start"]), instant(e["end"])) for e in focus) for a, b in slots)
    for sentence in re.split(r"[.!?\n]", answer):
        if any(e["title"].lower() in sentence.lower() for e in focus) and CHANGE.search(sentence) and not PROTECT.search(sentence):
            kept = False
    checks = {"conflicts_named": conflicts, "three_zones": zone_ok, "slot_valid": valid, "focus_kept": kept, "read_only": not attempts}
    errors = [{"reason": "wrong_zone_time", "event": sync["title"]}] if wrong_zone else []
    return {"checks": checks, "valid_windows": windows, "factual_errors": errors}
