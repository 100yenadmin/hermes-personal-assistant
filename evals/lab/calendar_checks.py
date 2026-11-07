"""Synthetic calendar expansion and bounded English answer checks; no provider IO."""
import datetime as dt
import re
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TIME = r"(?:\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?|\d{1,2}\s*[ap]\.?m\.?)"
ZONE = r"Asia/Singapore|Europe/London|America/New_York|SGT|BST|GMT|EDT|EST|ET"
CLOCK = re.compile(TIME, re.I)
FIX = re.compile(r"\b(?:mov(?:e|ed|ing)|reschedul(?:e|ed|ing)|declin(?:e|ed|ing)|shorten(?:ed|ing)?|shift(?:ed|ing)?)\b", re.I)


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


def blocks(answer):
    return [b for b in re.split(r"\n\s*\n|\n(?=\s*(?:[-*]|\d+[.)])\s)", answer) if b.strip()]


def proposed_slots(answer, calendar):
    """Day + time/range in a proposal sentence; named event statements are excluded."""
    monday = dt.date.fromisoformat(calendar["week_start"])
    slots = []
    for sentence in re.split(r"[.!?](?:\s|$)|\n|;", answer):
        if any(e["title"].lower() in sentence.lower() for e in calendar["events"] if not e.get("focus")):
            continue
        if any(e["title"].lower() in sentence.lower() for e in calendar["events"] if e.get("focus")) and not re.search(r"\b(?:propose|suggest|slot|window|move|reschedule)\b", sentence, re.I):
            continue
        day = re.search(r"\b(mon|tue|wed|thu|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?\b", sentence, re.I)
        if not day:
            continue
        label = re.search(r"\b(?:" + ZONE + r")\b", sentence, re.I)
        zone = calendar["owner_timezone"]
        if label:
            key = label[0].lower()
            zone = ("Europe/London" if key in ("bst", "gmt", "europe/london") else
                    "America/New_York" if key in ("et", "est", "edt", "america/new_york") else "Asia/Singapore")
        pattern = re.compile(r"(" + TIME + r")(?:\s*(?:[-–—]|to)\s*(" + TIME + r"))?", re.I)
        for match in pattern.finditer(sentence[day.end():]):
            times = [clock(t) for t in match.groups() if t]
            if not all(t is not None for t in times):
                slots.append((None, None))
                continue
            start = dt.datetime.combine(monday + dt.timedelta(days=DAYS.index(day[1].lower())), dt.time(*times[0]), ZoneInfo(zone)).astimezone(UTC)
            end = (dt.datetime.combine(start.astimezone(ZoneInfo(zone)).date(), dt.time(*times[1]), ZoneInfo(zone)).astimezone(UTC)
                   if len(times) > 1 else start + dt.timedelta(minutes=45))
            slots.append((start, end))
    return slots


def evaluate(answer, calendar, attempts=()):
    windows, sections = valid_windows(calendar), blocks(answer)
    events = calendar["events"]
    pairs = [(a, b) for i, a in enumerate(events) for b in events[i + 1:]
             if overlaps(instant(a["start"]), instant(a["end"]), instant(b["start"]), instant(b["end"]))]
    conflicts = bool(pairs) and all(any(all(e["title"].lower() in s.lower() for e in pair) and FIX.search(s) for s in sections) for pair in pairs)
    sync = next(e for e in events if e["title"] == "Partner sync")
    sync_text = " ".join(s for s in sections if sync["title"].lower() in s.lower())
    zones = {calendar["owner_timezone"]: "SGT|Asia/Singapore|Singapore", "Europe/London": "BST|GMT|Europe/London|London", "America/New_York": "ET|EST|EDT|America/New_York|New York"}
    zone_ok, wrong_zone = True, False
    for zone, labels in zones.items():
        expected = instant(sync["start"]).astimezone(ZoneInfo(zone))
        mentions = re.finditer(r"(" + TIME + r")\s*(?:\(\s*)?(?:" + labels + r")\b|(?:" + labels + r")\s*[:(]?\s*(" + TIME + r")", sync_text, re.I)
        values = [clock(m[1] or m[2]) for m in mentions]
        zone_ok &= bool(values) and all(t == (expected.hour, expected.minute) for t in values)
        wrong_zone |= any(t != (expected.hour, expected.minute) for t in values)
    slots = proposed_slots(answer, calendar)
    valid = bool(slots) and all(a is not None and b - a >= dt.timedelta(minutes=45) and
                any(instant(w["start"]) <= a < b <= instant(w["end"]) for w in windows) for a, b in slots)
    focus = [e for e in events if e.get("focus")]
    kept = all(a is not None and not any(overlaps(a, b, instant(e["start"]), instant(e["end"])) for e in focus) for a, b in slots)
    for section in sections:
        for event in focus:
            target = r"(?:the\s+)?(?:\*\*)?" + re.escape(event["title"])
            moves = re.finditer(FIX.pattern + r"\s+" + target + "|" + target + r"\s+(?:should|could|can|will|would|must)\s+(?:be\s+)?" + FIX.pattern, section, re.I)
            kept &= not any(not re.search(r"\b(?:not|never|don.t|won.t|no)\b", section[max(0, m.start() - 25):m.start()], re.I) for m in moves)
    checks = {"conflicts_named": conflicts, "three_zones": zone_ok, "slot_valid": valid, "focus_kept": kept, "read_only": not attempts}
    errors = [{"reason": "wrong_zone_time", "event": sync["title"]}] if wrong_zone else []
    return {"checks": checks, "valid_windows": windows, "factual_errors": errors}
