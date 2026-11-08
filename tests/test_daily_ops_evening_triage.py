"""Evening register: the second daily mail triage and tomorrow's meetings to confirm; provider-free."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from personal_assistant.daily_ops import common, evening_register, gog_collector, morning_brief
from personal_assistant.daily_ops.common import Collected
from personal_assistant.daily_ops.gog_collector import DailyOpsError

MOMENT = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)  # 19:00 Bangkok; tomorrow is 9 Sep.
OWNER = "owner@example.com"


def cfg(**updates):
    data = {
        "tenant": {"profile_id": "example-profile", "owner_email": OWNER},
        "delivery": {"target": "example-topic", "verified": True},
        "timezone": "Asia/Bangkok",
        "accounts": {"work": OWNER, "personal": None},
        "self_emails": [OWNER],
        "travel": {"leave_by": False},
    }
    data.update(updates)
    return data


def event(ident, hour, attendees=None, **extra):
    item = {"id": ident, "summary": f"Meeting {ident}",
            "start": {"dateTime": f"2026-09-09T{hour:02d}:00:00+07:00", "timeZone": "Asia/Bangkok"},
            "end": {"dateTime": f"2026-09-09T{hour:02d}:30:00+07:00", "timeZone": "Asia/Bangkok"},
            "location": "Example office"}
    if attendees is not None:
        item["attendees"] = attendees
    item.update(extra)
    return item


def patch(monkeypatch, events, mail=None):
    monkeypatch.setattr(evening_register, "run_calendar",
                        lambda *a, **k: Collected(list(events), True, False, None, [{"source": "calendar-1"}]))
    monkeypatch.setattr(evening_register, "run_mail", mail or (lambda *a, **k: Collected(
        [{"id": "t1", "from": "Dana <dana@client.example>", "subject": "Offsite venue?"}], True, False, None)))
    monkeypatch.setattr(evening_register.trip_context, "trip_context", lambda *a: {"status": "unknown"})


def test_evening_packet_carries_humans_bulk_and_meetings_to_confirm(monkeypatch):
    guests = [{"email": OWNER, "self": True, "responseStatus": "accepted"},
              {"email": "Dana@client.example"}, {"email": "lee@partner.example"},
              {"email": "room-1@resource.example", "resource": True}]
    patch(monkeypatch, [event("ev1", 10, guests), event("solo", 12, [{"email": OWNER, "self": True}]),
                        event("focus", 14), {"id": "allday", "summary": "Holiday", "start": {"date": "2026-09-09"},
                                             "end": {"date": "2026-09-10"}}])
    packet = evening_register.collect(cfg(), profile="/synthetic", moment=MOMENT)
    sections = packet["sections"]
    assert sections["humans_1"]["count"] == 1 and sections["humans_1"]["complete"] is True
    assert {"count", "exact", "lower_bound", "sample", "complete", "truncated"} <= set(sections["bulk_1"])
    meetings = sections["meetings_to_confirm"]
    by_id = {row["event_id"]: row for row in meetings["items"]}
    assert set(by_id) == {"ev1", "focus"} and meetings["count"] == 2
    assert by_id["ev1"]["attendees_known"] is True and by_id["ev1"]["attendee_count"] == 2
    assert all(value.startswith("[email-") for value in by_id["ev1"]["attendees"])
    assert by_id["focus"]["attendees_known"] is False and by_id["focus"]["attendee_count"] is None
    assert packet["complete"] is True and packet["truncated"] is False
    text = json.dumps(packet)
    assert "dana@client.example" not in text and "lee@partner.example" not in text


def test_declined_and_cancelled_meetings_are_not_listed(monkeypatch):
    declined = [{"email": OWNER, "self": True, "responseStatus": "declined"}, {"email": "a@client.example"}]
    patch(monkeypatch, [event("d", 10, declined), event("c", 11, [{"email": "a@client.example"}], status="cancelled")])
    packet = evening_register.collect(cfg(), profile="/synthetic", moment=MOMENT)
    assert packet["sections"]["meetings_to_confirm"] == {"items": [], "count": 0, "coverage": [{"source": "calendar-1"}]}


def test_truncated_mail_makes_the_evening_packet_incomplete(monkeypatch):
    patch(monkeypatch, [event("ev1", 10)], mail=lambda *a, **k: Collected([{"id": "x"}] * 3, False, True, None))
    packet = evening_register.collect(cfg(), profile="/synthetic", moment=MOMENT)
    assert packet["sections"]["humans_1"]["truncated"] is True
    assert packet["complete"] is False and packet["truncated"] is True


def test_failed_mail_read_is_a_failure_not_an_empty_complete_result(monkeypatch):
    def broken(*args, **kwargs):
        raise DailyOpsError("GOG_FAIL rc=1 gmail search: synthetic")
    patch(monkeypatch, [event("ev1", 10)], mail=broken)
    with pytest.raises(DailyOpsError, match="synthetic"):
        evening_register.collect(cfg(), profile="/synthetic", moment=MOMENT)


def test_personal_account_gets_its_own_sections(monkeypatch):
    queries = []
    patch(monkeypatch, [], mail=lambda account, query, **k: queries.append((account, query)) or Collected([], True, False, 0))
    packet = evening_register.collect(cfg(accounts={"work": OWNER, "personal": "me@home.example"}),
                                      profile="/synthetic", moment=MOMENT)
    assert {"humans_1", "bulk_1", "humans_2", "bulk_2"} <= set(packet["sections"])
    assert queries == [(OWNER, common.Q_HUMANS), (OWNER, common.Q_BULK),
                       ("me@home.example", common.Q_HUMANS), ("me@home.example", common.Q_BULK)]
    assert morning_brief.Q_HUMANS == common.Q_HUMANS and morning_brief.Q_BULK == common.Q_BULK


def test_evening_register_uses_only_allowlisted_readonly_verbs(monkeypatch):
    commands = []

    class Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(command, **kwargs):
        commands.append(command)
        if "calendar" in command:
            return Result(json.dumps({"events": [event("ev1", 10, [{"email": "a@client.example"}])], "has_more": False}))
        return Result(json.dumps({"threads": [{"id": "t1"}], "has_more": False}))

    monkeypatch.setattr(gog_collector, "gog_binary", lambda: "/bin/gog")
    monkeypatch.setattr(gog_collector.subprocess, "run", fake_run)
    monkeypatch.setattr(evening_register.trip_context, "trip_context", lambda *a: {"status": "unknown"})
    packet = evening_register.collect(cfg(), profile="/synthetic", moment=MOMENT)
    assert packet["sections"]["meetings_to_confirm"]["items"][0]["attendee_count"] == 1
    verbs = set()
    for command in commands:
        assert "--readonly" in command
        start = command.index("--readonly") + 1
        rest = [part for part in command[start:] if part != "--gmail-no-send"]
        verbs.add(tuple(rest[:2]))
    assert verbs == {("calendar", "events"), ("gmail", "search")}


def test_daily_ops_text_hands_evening_mail_and_meetings_to_r6_and_r4():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    skill = " ".join((root / "skills/daily-ops/SKILL.md").read_text().split())
    docs = " ".join((root / "docs/daily-ops.md").read_text().split())
    assert "`meetings_to_confirm`" in skill and "`personal-assistant:r6-inbox-replies`" in skill
    assert "`personal-assistant:r4-calendar-meeting`" in skill and "same complete/truncated flags" in skill
    assert "twice a day without a third routine" in docs and "`attendees_known: false`" in docs


def test_threads_past_the_listed_ones_make_the_section_truncated(monkeypatch):
    threads = [{"id": f"t{n}", "from": "Dana <dana@client.example>", "subject": f"Thread {n}"} for n in range(1, 27)]
    patch(monkeypatch, [event("ev1", 10)], mail=lambda *a, **k: Collected(list(threads), True, False, None))
    packet = evening_register.collect(cfg(), profile="/synthetic", moment=MOMENT)
    humans = packet["sections"]["humans_1"]
    assert humans["count"] == 26 and humans["shown"] == 25 and humans["omitted"] == 1
    assert len(humans["items"]) == 25 and humans["complete"] is True and humans["truncated"] is True
    assert packet["truncated"] is True


def test_morning_and_evening_share_the_honest_humans_section():
    def read(account, query, **kwargs):
        size = 30 if query == common.Q_HUMANS else 2
        return Collected([{"id": f"x{n}"} for n in range(size)], True, False, None)
    sections, complete, truncated = common.mail_sections("owner@example.invalid", 1, read)
    assert sections["humans_1"]["omitted"] == 5 and sections["humans_1"]["truncated"] is True
    assert complete is True and truncated is True
    small, _, small_truncated = common.mail_sections("owner@example.invalid", 1, lambda *a, **k: Collected([{"id": "y"}], True, False, None))
    assert small["humans_1"]["omitted"] == 0 and small["humans_1"]["shown"] == 1 and small_truncated is False
    assert morning_brief.mail_sections is common.mail_sections
