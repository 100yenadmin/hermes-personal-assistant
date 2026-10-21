import datetime as dt
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from personal_assistant.automation import upsert_automation_rule, record_notification
from personal_assistant.automation_workflow import preferences, cron_precheck, prepare_suggestions, _install_precheck
from personal_assistant.state import Ledger


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
