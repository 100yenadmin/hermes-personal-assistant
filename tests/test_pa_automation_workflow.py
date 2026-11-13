import datetime as dt
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from personal_assistant import automation as auto

from personal_assistant.automation import upsert_automation_rule, record_notification
from personal_assistant.automation_workflow import preferences, cron_precheck, prepare_suggestions, _install_precheck
from personal_assistant.state import Ledger


@pytest.mark.parametrize("pinned", [False, True])
@pytest.mark.parametrize("kind", ["cos_daily", "cos_kickoff", "cos_weekly", "daily_brief", "due_source_check"])
def test_rule_timezone_follows_owner_unless_pinned(tmp_path, pinned, kind):
    ledger = Ledger(tmp_path)
    preferences(ledger, {"timezone": "Asia/Bangkok", "cos_weekly_day": "mon"})
    upsert_automation_rule(ledger, kind, {"kind": kind, "accepted": True,
        "destination": "fixture", "destination_verified": True, "timezone": "Asia/Seoul",
        "source_ref": "fixture-feed",
        **({"timezone_pinned": True} if pinned else {})})
    zone, offset = ("Asia/Seoul", "+09:00") if pinned else ("Asia/Bangkok", "+07:00")
    clock = "12:00:00" if kind == "cos_kickoff" else "07:30:00" if kind == "due_source_check" else "16:00:00"
    now = dt.datetime.fromisoformat("2026-11-09T" + clock + offset)
    jobs = auto.suggest_automation_jobs(ledger=ledger, chief_of_staff=True)["jobs"]
    assert jobs[0]["timezone"] == jobs[0]["schedule_timezone"] == zone
    with patch("personal_assistant.automation_workflow.cos_enabled", return_value=True):
        result = cron_precheck(ledger, kind, enabled=True, moment=now)
    slots = auto.routine_slots(ledger, now=now)
    if kind == "daily_brief" and pinned:
        assert result == {"wakeAgent": False, "reason": "timezone_conflict"}
        assert slots == []
    else:
        assert result["wakeAgent"]
        if kind == "due_source_check":
            assert result["due_sources"] == ["fixture-feed"] and slots == []
        else:
            assert slots and all(s["due_at"].endswith(offset) for s in slots)


@pytest.mark.parametrize("pinned", [False, True])
def test_snooze_release_parses_effective_zone(tmp_path, pinned):
    ledger = Ledger(tmp_path)
    preferences(ledger, {"timezone": "Asia/Bangkok"})
    rule = {"kind": "cos_daily", "timezone": "Asia/Seoul", "timezone_pinned": pinned,
            "snooze_until": "2026-11-09T12:00:00"}
    upsert_automation_rule(ledger, "daily", rule)
    current = dt.datetime.fromisoformat("2026-11-09T04:00:00+00:00")
    with patch.object(auto, "_now", return_value=current):
        row = upsert_automation_rule(ledger, "daily", {**rule, "snooze_until": None})
    # Noon Seoul has passed; noon Bangkok is still snoozed, so clearing it resumes.
    assert ("routine_resumed_at" in row["fields"]) is (not pinned)


def test_acceptance_inherits_later_preferences_and_explicit_update_pins(tmp_path):
    from personal_assistant.automation_workflow import dispatch
    ledger = Ledger(tmp_path)
    preferences(ledger, {"timezone": "Asia/Seoul"})
    rule = {"kind": "cos_daily", "accepted": True,
            "destination": "fixture", "destination_verified": True}
    row = dispatch(ledger, {"action": "rule", "rule_id": "daily", "rule": rule})
    assert "timezone" not in row["fields"]["automation_rule"]
    assert not row["fields"]["automation_rule"].get("timezone_pinned")
    preferences(ledger, {"timezone": "Asia/Bangkok"})
    assert auto.rule_timezone(row, preferences(ledger)) == "Asia/Bangkok"
    assert auto.suggest_automation_jobs(ledger, chief_of_staff=True)["jobs"][0]["schedule_timezone"] == "Asia/Bangkok"
    # A bare zone (a copy of the owner's current one, or a status round trip) never pins.
    row = dispatch(ledger, {"action": "rule", "rule_id": "daily",
                           "rule": {**rule, "timezone": "Asia/Seoul"}})
    assert "timezone" not in row["fields"]["automation_rule"]
    assert auto.rule_timezone(row, preferences(ledger)) == "Asia/Bangkok"
    row = dispatch(ledger, {"action": "rule", "rule_id": "daily",
                           "rule": {**rule, "timezone": "Asia/Seoul", "timezone_pinned": True}})
    assert row["fields"]["automation_rule"]["timezone_pinned"] is True
    assert auto.rule_timezone(row, preferences(ledger)) == "Asia/Seoul"
    # Reading the pinned rule back and writing it again keeps the pin.
    row = dispatch(ledger, {"action": "rule", "rule_id": "daily", "rule": dict(row["fields"]["automation_rule"])})
    assert auto.rule_timezone(row, preferences(ledger)) == "Asia/Seoul"
    for bad in ("invalid/zone", None, ""):
        with pytest.raises(Exception):
            dispatch(ledger, {"action": "rule", "rule_id": "daily",
                              "rule": {**rule, "timezone": bad, "timezone_pinned": True}})
    assert auto.rule_timezone(ledger.get("action", row["action_id"]), preferences(ledger)) == "Asia/Seoul"


@pytest.mark.parametrize("pinned,expected", [(False, []), (True, ["feed"])])
def test_due_source_naive_clock_uses_effective_zone(tmp_path, pinned, expected):
    rule = {"kind": "due_source_check", "accepted": True, "source_ref": "feed",
            "timezone": "Asia/Seoul", "timezone_pinned": pinned,
            "last_checked_at": "2026-11-09T12:00:00", "refresh_interval_minutes": 180}
    # At 13:30 Bangkok / 15:30 Seoul, a three-hour refresh is due only in Seoul.
    result = auto.script_precheck({"timezone": "Asia/Bangkok", "sources": [rule]},
                                  now="2026-11-09T06:30:00+00:00")
    assert result["due_sources"] == expected


@pytest.mark.parametrize("limit", [2, None])
def test_native_backlog_and_brief_accept_text(tmp_path, monkeypatch, limit):
    ledger = Ledger(tmp_path)
    preferences(ledger, {"timezone": "Asia/Seoul"})
    for kind in ("daily_brief", "due_source_check"):
        upsert_automation_rule(ledger, kind, {"kind": kind, "accepted": True,
            "destination": "telegram:fixture-owner", "destination_verified": True})
    records, descriptions = [], {}
    cap = 5 if limit is None else limit

    def add_suggestion(*, title, description, source, job_spec, dedup_key):
        descriptions[dedup_key] = description
        if sum(r["status"] == "pending" for r in records) >= cap:
            return None
        record = dict(id=dedup_key, dedup_key=dedup_key, status="pending")
        records.append(record)
        return record

    fake = SimpleNamespace(add_suggestion=add_suggestion, load_suggestions=lambda: list(records))
    if limit is not None:
        fake.MAX_PENDING = limit
    monkeypatch.setitem(sys.modules, "cron.suggestions", fake)
    monkeypatch.setitem(sys.modules, "cron.jobs", SimpleNamespace(list_jobs=lambda include_disabled=False: []))
    with patch("personal_assistant.automation_workflow.native_profile_guard"):
        result = prepare_suggestions(ledger, native=True)
        assert [j.get("suggestion") for j in result["jobs"]] == ["suggested", "suggested"]
        assert "next_step" not in result
        base = "Optional PA routine; accepting enables it. Briefs use your configured local time."
        assert descriptions["personal-assistant:daily_brief"] == base + (
            " If today's slot has already passed, the first run comes within minutes of accepting.")
        assert descriptions["personal-assistant:due_source_check"] == base
        records[:] = [dict(id=f"foreign-{n}", dedup_key=f"foreign-{n}", status="pending") for n in range(cap)]
        full = prepare_suggestions(ledger, native=True)
        assert [j["suggestion"] for j in full["jobs"]] == ["backlog_full", "backlog_full"]
        assert full["next_step"] == (
            f"Hermes keeps at most {cap} pending suggestions and dropped 2. "
            "Ask the user to review /suggestions (accept or dismiss older ones), then run suggest again.")


class WorkflowTests(unittest.TestCase):
    def setup_ledger(self, root, kind):
        ledger = Ledger(root)
        preferences(ledger, {"timezone": "Asia/Seoul"})
        upsert_automation_rule(ledger, kind, {"kind": kind, "accepted": True,
            "destination": "telegram:fixture-owner", "destination_verified": True,
            "timezone": "Asia/Seoul"})
        return ledger

    def test_daily_timezone_and_restart_no_repeat(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = self.setup_ledger(root, "daily_brief")
            before = dt.datetime.fromisoformat("2026-09-06T07:55:00+09:00")
            ready = before + dt.timedelta(minutes=5)
            self.assertFalse(cron_precheck(ledger, "daily_brief", enabled=True, moment=before)["wakeAgent"])
            claim = cron_precheck(ledger, "daily_brief", enabled=True, moment=ready)
            self.assertTrue(claim["wakeAgent"])
            record_notification(ledger, claim["occurrence_id"], "unknown")
            self.assertFalse(cron_precheck(Ledger(root), "daily_brief", enabled=True, moment=ready)["wakeAgent"])

    def test_due_empty_disabled_pause_snooze(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = self.setup_ledger(root, "due_source_check")
            now = dt.datetime.fromisoformat("2026-09-06T12:00:00+09:00")
            self.assertFalse(cron_precheck(ledger, "due_source_check", enabled=True, moment=now)["wakeAgent"])
            ledger.put("action", "return", {"due_at": "2026-09-06T11:00:00+09:00", "timezone": "Asia/Seoul"}, action_type="return")
            self.assertFalse(cron_precheck(ledger, "due_source_check", enabled=False, moment=now)["wakeAgent"])
            preferences(ledger, {"paused": True})
            self.assertFalse(cron_precheck(ledger, "due_source_check", enabled=True, moment=now)["wakeAgent"])
            preferences(ledger, {"paused": False, "snooze_until": "2026-09-07T12:00:00+09:00"})
            self.assertFalse(cron_precheck(ledger, "due_source_check", enabled=True, moment=now)["wakeAgent"])

    def test_two_native_specs_use_scripts_and_hermes_delivery(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = self.setup_ledger(root, "daily_brief")
            self.setup_ledger(root, "due_source_check")
            result = prepare_suggestions(ledger)
            self.assertFalse((Path(root) / "scripts").exists())
            self.assertEqual(len(result["jobs"]), 2)
            for job in result["jobs"]:
                # Hermes v0.22.2 cron runs have no agent send tool, so the final response is the message.
                self.assertEqual(job["job_spec"]["deliver"], job["deliver"])
                self.assertNotEqual(job["deliver"], "local")
                self.assertIn("exactly [SILENT]", job["job_spec"]["prompt"])
                self.assertIn("never use a message tool", job["job_spec"]["prompt"])
                self.assertNotIn("Record delivered", job["job_spec"]["prompt"])
                self.assertNotIn("collector", job["job_spec"])
                self.assertNotIn("due_rule", job["job_spec"])
                self.assertTrue(job["job_spec"]["script"].endswith("_precheck.py"))
                self.assertEqual(Path(job["job_spec"]["script"]).parent, Path(root).resolve() / "scripts")
                self.assertFalse(job["creates_jobs"])
                self.assertIn("personal-assistant:daily-ops", job["job_spec"]["skills"])
            due = next(job for job in result["jobs"] if job["kind"] == "due_source_check")
            self.assertEqual(due["collector"], "personal_assistant.daily_ops.evening_register")
            self.assertIn("accepted source is due_at<=now", due["due_rule"])
            self.assertIn("not a third scheduled job", due["job_spec"]["prompt"])

    def test_native_precheck_is_owned_idempotent_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = self.setup_ledger(root, "due_source_check")
            path = Path(_install_precheck(ledger, "due_source_check"))
            original = path.read_bytes()
            inode = path.stat().st_ino
            self.assertIn(b"script_main('due_source_check')", original)
            compile(original, str(path), "exec")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(_install_precheck(ledger, "due_source_check"), str(path))
            self.assertEqual(path.stat().st_ino, inode)
            path.write_text("owner's existing script")
            with self.assertRaisesRegex(ValueError, "different content"):
                _install_precheck(ledger, "due_source_check")
            self.assertEqual(path.read_text(), "owner's existing script")
            path.unlink()
            external = Path(root) / "untouched"
            external.write_text("preserve")
            path.symlink_to(external)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                _install_precheck(ledger, "due_source_check")
            self.assertEqual(external.read_text(), "preserve")

    def test_native_completed_commitment_does_not_wake_due_check(self):
        with tempfile.TemporaryDirectory() as root:
            ledger = self.setup_ledger(root, "due_source_check")
            ledger.put("action", "renewal", {"due_at": "2026-09-06T11:00:00+09:00", "timezone": "Asia/Seoul", "kanban_task_id": "fixture-task"})
            with patch("personal_assistant.context.read_kanban_task", return_value={"status": "done"}):
                result = cron_precheck(ledger, "due_source_check", enabled=True, moment=dt.datetime.fromisoformat("2026-09-06T12:00:00+09:00"))
            self.assertFalse(result["wakeAgent"])
            self.assertFalse(any(a["action_type"] == "notification" for a in ledger.list("action")))


if __name__ == "__main__":
    unittest.main()


def test_reporting_routine_skill_lists(tmp_path):
    ledger = Ledger(tmp_path)
    preferences(ledger, {'timezone': 'UTC'})
    for kind in ('daily_brief', 'due_source_check'):
        upsert_automation_rule(ledger, kind, {'kind': kind, 'accepted': True,
            'destination': 'fixture-owner', 'destination_verified': True})
    jobs = {j['kind']: j for j in prepare_suggestions(ledger)['jobs']}
    assert jobs['daily_brief']['skills'] == [
        'personal-assistant:r5-brief-reminders', 'personal-assistant:daily-ops',
        'personal-assistant:r4-calendar-meeting', 'personal-assistant:r6-inbox-replies',
    ]
    assert jobs['due_source_check']['skills'] == [
        'personal-assistant:itinerary-intake', 'personal-assistant:travel-email-calendar',
        'personal-assistant:provider-message-refund', 'personal-assistant:daily-ops',
        'personal-assistant:follow-through', 'personal-assistant:r5-brief-reminders',
        'personal-assistant:r4-calendar-meeting',
        'personal-assistant:r6-inbox-replies',
    ]

    assert 'chase_action_ids' in jobs['due_source_check']['due_rule']
    assert 'end_of_day slot after eod_time' in jobs['daily_brief']['due_rule']
