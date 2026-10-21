"""Synthetic evidence recording, isolation and read-only export."""
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import validate

from personal_assistant.context import retrieve, status_snapshot
from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.evidence import AREAS, EVIDENCE_TYPES
from personal_assistant.state import Ledger, legacy
from evals.scorecard.areas import AREAS as SCORECARD_AREAS
from evals.scorecard.build import build

ROOT = Path(__file__).resolve().parents[1]


def call(root, action, **data):
    args = {"operation": "evidence", "data": {"action": action, **data}}
    validate(args, SCHEMA["parameters"])
    return dispatch(root, args)


def record(root, **data):
    return call(root, "record", **{"area": "research", "title": "Compare options",
                                 "due": "2026-11-01", "agreed_outcome": "Short sourced recommendation", **data})


def time_records(root, week_ending="2026-10-21"):
    call(root, "baseline", week_of="2026-10-01", minutes_by_type={"research": 60, "inbox": 40})
    call(root, "day30", week_ending=week_ending, minutes=75,
         first_pass_task_types=["research", "inbox", "calendar", "travel"])


def test_record_defaults_and_duplicate(tmp_path):
    row = record(tmp_path)
    assert row["started"] == datetime.now(timezone.utc).date().isoformat()
    assert re.fullmatch(r"va-task:compare-options-[0-9a-f]{6}-" + row["started"], row["identity"])
    assert row["status"] == "pending" and row["owner_accepted"] is None
    assert row["facts"] == [] and row["correction"] == "none" and row["cohort"] == "default"
    assert row["created_at"]
    with pytest.raises(ValueError, match="exists .*same task use update.*different task.*title or its own task_id"):
        record(tmp_path)
    other = record(tmp_path, task_id="compare-options-second")  # A different task with the same title.
    assert other["identity"] == "va-task:compare-options-second"
    assert AREAS == [a["key"] for a in SCORECARD_AREAS[:12]]


@pytest.mark.parametrize("data", [
    {"area": "unknown"}, {"due": "2026-02-30"}, {"started": "20261001"},
    {"title": "api key: sk-live-12345678"}, {"title": "Card 4111 1111 1111 1111"},
    {"raw_message": "synthetic text"}, {"task_id": "UPPER"}, {"title": "x" * 121},
    {"agreed_outcome": "x" * 201}, {"cohort": "x" * 41},
])
def test_record_rejects_invalid_or_private_without_write(tmp_path, data):
    with pytest.raises(ValueError):
        record(tmp_path, **data)
    assert Ledger(tmp_path).list("action") == []


def test_update_lifecycle_and_export(tmp_path):
    row = record(tmp_path)
    identity = row["identity"]
    facts = [{"item": "Published price", "source": "https://example.org/pricing", "ok": True, "facing": "money"}]
    updated = call(tmp_path, "update", identity=identity, status="pass", facts=facts,
                   owner_accepted=True, correction="minor", correction_note="Clarified wording")
    assert updated["closed_at"] and updated["facts"] == facts
    assert call(tmp_path, "update", identity=identity, correction_note="")["correction_note"] == ""
    assert Ledger(tmp_path).get("action", identity)["status"] == "pass"
    assert call(tmp_path, "export")["tasks"][0]["owner_accepted"] is True
    assert "closed_at" not in call(tmp_path, "update", identity=identity, status="pending", owner_accepted=None)
    assert "closed_at" not in Ledger(tmp_path).get("action", identity)["fields"]
    assert call(tmp_path, "update", identity=identity, status="fail")["closed_at"]
    call(tmp_path, "update", identity=identity, title="Revised title", due="2026-11-02", agreed_outcome="Revised result")
    export = call(tmp_path, "export")
    assert set(export) == {"tasks", "baselines", "day30", "profile"}
    keys = set("id area owner title started due status owner_accepted correction facts".split())
    assert set(export["tasks"][0]) - {"closed_at"} == keys  # closed_at appears once a task is closed.
    build("test", "a" * 40, [], export, as_of="2026-11-02")


@pytest.mark.parametrize("data", [
    {"facts": [{"item": "Price", "ok": True, "facing": "money"}]},
    {"facts": [{"item": "Price", "source": " ", "ok": True, "facing": "money"}]},
    {"unknown": True}, {"area": "inbox"}, {"started": "2026-10-01"},
    {"owner_accepted": 1}, {"status": "completed"}, {"correction": "large"},
    {"correction_note": "x" * 161}, {"facts": [{}] * 21},
    {"title": "api key: sk-live-12345678"},
])
def test_invalid_updates_do_not_change_task(tmp_path, data):
    row = record(tmp_path)
    with pytest.raises(ValueError):
        call(tmp_path, "update", identity=row["identity"], **data)
    assert call(tmp_path, "list") == [row]


def test_list_filters_cap_and_export_uncapped(tmp_path):
    for i in range(52):
        row = record(tmp_path, task_id=f"task-{i}", area="inbox" if i == 0 else "research")
        if i == 0:
            call(tmp_path, "update", identity=row["identity"], status="pass")
    rows = call(tmp_path, "list")
    assert len(rows) == 50 and rows[0]["identity"] == "va-task:task-51"
    assert len(call(tmp_path, "list", area="inbox", status="pass")) == 1
    assert call(tmp_path, "list", area="inbox", status="pending") == []
    assert len(call(tmp_path, "export")["tasks"]) == 52


def test_time_records_replace_and_round_trip(tmp_path):
    time_records(tmp_path)
    result = call(tmp_path, "export", owner="A")
    assert result["baselines"]["A"]["total_minutes"] == 100
    assert result["day30"]["A"]["minutes"] == 75
    call(tmp_path, "baseline", week_of="2026-10-08", minutes_by_type={"calendar": 30})
    call(tmp_path, "day30", week_ending="2026-10-28", minutes=0, first_pass_task_types=[])
    result = call(tmp_path, "export", owner="A")
    assert result["baselines"]["A"] == {"week_of": "2026-10-08", "minutes_by_type": {"calendar": 30}, "total_minutes": 30}
    assert result["day30"]["A"] == {"week_ending": "2026-10-28", "minutes": 0, "first_pass_task_types": []}
    rows = Ledger(tmp_path).list("action")
    assert len(rows) == 2 and all(r["status"] == "recorded" and r["fields"]["recorded_at"] for r in rows)


@pytest.mark.parametrize("action,data", [
    ("baseline", {"week_of": "2026-10-01", "minutes_by_type": {"inbox": True}}),
    ("baseline", {"week_of": "2026-10-01", "minutes_by_type": {str(i): 1 for i in range(13)}}),
    ("day30", {"week_ending": "2026-10-21", "minutes": -1, "first_pass_task_types": []}),
    ("day30", {"week_ending": "2026-10-21", "minutes": 0, "first_pass_task_types": ["x"] * 13}),
])
def test_invalid_time_records(tmp_path, action, data):
    with pytest.raises(ValueError):
        call(tmp_path, action, **data)


def test_two_owner_scorecard(tmp_path):
    from datetime import timedelta
    today = datetime.now(timezone.utc).date()
    # Day-30 counts only 28 or more days after the first task, so the cohort started 30 days ago.
    START, DUE = (today - timedelta(days=30)).isoformat(), (today + timedelta(days=1)).isoformat()
    exports = []
    for owner in ("A", "B"):
        root = tmp_path / owner
        root.mkdir()
        for i in range(10):
            row = record(root, task_id=f"task-{i}", started=START, due=DUE)  # Closed today, before the due date.
            call(root, "update", identity=row["identity"], status="pass", owner_accepted=True,
                 correction="material" if owner == "B" and i == 9 else "none",
                 facts=[{"item": "Provider comparison", "source": "https://example.org", "ok": True, "facing": "customer"}])
        time_records(root, week_ending=today.isoformat())
        exports.append(call(root, "export", owner=owner))
    result = build("test", "a" * 40, [], exports, as_of=DUE)
    research = next(a for a in result["areas"] if a["key"] == "research")
    assert research["real_work"]["state"] == research["facts"]["state"] == result["day30"]["state"] == "pass"
    assert research["parity"] == "unproven"  # No lab evidence.


def test_exclusions(tmp_path, monkeypatch, capsys):
    record(tmp_path)
    time_records(tmp_path)
    ledger = Ledger(tmp_path)
    ledger.put("action", "ordinary", {"title": "Visible note"}, action_type="note")
    assert {r["action_id"] for r in status_snapshot(ledger)["actions"]} == {"ordinary"}
    assert {r["action_id"] for r in retrieve(ledger, {"kind": "action"})["items"]} == {"ordinary"}
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)
    legacy.main(["summary", "--json"])
    assert {r["action_id"] for r in json.loads(capsys.readouterr().out)["actions"]} == {"ordinary"}


@pytest.mark.parametrize("op,data", [
    *[("action_upsert", {"action_type": kind}) for kind in sorted(EVIDENCE_TYPES)],
    *[(op, {"action_id": prefix + "x"}) for prefix in ("va-task:", "va-baseline:", "va-day30:")
      for op in ("action_upsert", "action_cancel", "action_prepare", "action_confirm", "action_claim", "action_result")],
])
def test_generic_mutators_refuse_evidence(tmp_path, op, data):
    with pytest.raises(ValueError, match="evidence records are written with operation evidence"):
        dispatch(tmp_path, {"operation": op, "data": data})


def test_export_script_copy_read_only(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    record(source)
    time_records(source)
    copy = tmp_path / "copy"
    shutil.copytree(source, copy)
    ledger = Ledger(copy, read_only=True)
    before = ledger.path.read_bytes(), ledger.path.stat().st_mtime_ns
    command = [sys.executable, str(ROOT / "scripts/export_va_evidence.py"), str(copy), "--owner", "A"]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == call(source, "export", owner="A")
    output = tmp_path / "export.json"
    assert subprocess.run([*command, "--out", str(output)], capture_output=True).returncode == 0
    assert json.loads(output.read_text()) == json.loads(result.stdout)
    assert subprocess.run([*command, "--out", str(ledger.path)], capture_output=True).returncode == 2
    alias = tmp_path / "ledger-alias.sqlite"
    alias.hardlink_to(ledger.path)
    assert subprocess.run([*command, "--out", str(alias)], capture_output=True).returncode == 2
    assert (ledger.path.read_bytes(), ledger.path.stat().st_mtime_ns) == before


def test_unknown_action(tmp_path):
    with pytest.raises(ValueError, match="unknown evidence action"):
        call(tmp_path, "unknown")


def test_dates_and_baseline_stay_scoreable(tmp_path):
    """The scorecard rejects due-before-start tasks and zero-minute baselines, so the op refuses them first."""
    with pytest.raises(ValueError, match="due must not be before started"):
        call(tmp_path, "record", area="research", title="Payroll comparison", due="2026-10-01",
             agreed_outcome="one-page answer", started="2026-10-05")
    task = record(tmp_path)
    with pytest.raises(ValueError, match="due must not be before started"):
        call(tmp_path, "update", identity=task["identity"], due="2000-01-01")
    with pytest.raises(ValueError, match="at least one delegated task type"):
        call(tmp_path, "baseline", week_of="2026-10-12", minutes_by_type={"inbox": 0})
    with pytest.raises(ValueError, match="at least one delegated task type"):
        call(tmp_path, "baseline", week_of="2026-10-12", minutes_by_type={})


def test_titles_in_any_script_get_distinct_ids(tmp_path):
    ids = {record(tmp_path, title=title, started="2026-10-21")["identity"]
           for title in ("給与計算サービスの比較", "大阪のホテル予約", "받은편지함 정리",
                         "Compare payroll providers for a twelve person team, option A",
                         "Compare payroll providers for a twelve person team, option B")}
    assert len(ids) == 5 and all(re.fullmatch(r"va-task:[a-z0-9-]{3,60}", i) for i in ids)


@pytest.mark.parametrize("minutes", [{"4111 1111 1111 1111": 30}, {"token=abcdef123456": 30}])
def test_private_baseline_keys_are_refused(tmp_path, minutes):
    with pytest.raises(ValueError, match="evidence records prohibit"):
        call(tmp_path, "baseline", week_of="2026-10-12", minutes_by_type=minutes)
    assert not Ledger(tmp_path).list("action")


def test_ordinary_sources_and_task_types_are_accepted(tmp_path):
    assert call(tmp_path, "baseline", week_of="2026-10-12", minutes_by_type={"travel documents": 30, "network setup": 15})["total_minutes"] == 45
    task = record(tmp_path)
    facts = [{"item": "Gusto price", "source": "https://gusto.com/product/pricing", "ok": True, "facing": "money"},
             {"item": "Passport renewal fee", "source": "Gusto pricing page, gusto.com", "ok": True, "facing": "internal"}]
    assert call(tmp_path, "update", identity=task["identity"], facts=facts)["facts"] == facts
    with pytest.raises(ValueError, match="evidence records prohibit"):
        call(tmp_path, "update", identity=task["identity"],
             facts=[{"item": "x", "source": "https://x.example/?token=abcdef123456", "ok": True, "facing": "money"}])


def test_started_defaults_never_after_due(tmp_path):
    past = "2001-01-02"
    row = call(tmp_path, "record", area="research", title="Old due", due=past, agreed_outcome="done")
    assert row["started"] == past


def test_late_pass_is_not_a_pass_by_the_due_date(tmp_path):
    task = record(tmp_path, started="2026-10-01", due="2026-10-05")
    call(tmp_path, "update", identity=task["identity"], status="pass", owner_accepted=True)
    exported = call(tmp_path, "export", owner="A")["tasks"][0]
    assert exported["closed_at"][:10] > "2026-10-05"
    tasks = [dict(exported, id=f"t{i}", owner=f"o{i % 2}") for i in range(10)]
    real = next(a for a in build("0.9", "a" * 40, [], {"tasks": tasks, "baselines": {}, "day30": {}},
                                 as_of="2026-10-30")["areas"] if a["key"] == "research")["real_work"]
    assert real["passed"] == 0
    on_time = [dict(t, closed_at="2026-10-04T10:00:00Z") for t in tasks]
    real = next(a for a in build("0.9", "a" * 40, [], {"tasks": on_time, "baselines": {}, "day30": {}},
                                 as_of="2026-10-30")["areas"] if a["key"] == "research")["real_work"]
    assert real["passed"] == 10


def test_export_script_without_a_ledger_is_a_usage_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = subprocess.run([sys.executable, str(ROOT / "scripts/export_va_evidence.py"), str(empty), "--owner", "A"],
                            capture_output=True, text=True)
    assert result.returncode in (0, 2) and "Traceback" not in result.stderr


@pytest.mark.parametrize("source", ["https://help.gusto.com/login/pricing", "https://www.youtube.com/watch?v=abc&t=42s"])
def test_source_the_ledger_would_redact_is_refused(tmp_path, source):
    row = record(tmp_path)
    with pytest.raises(ValueError, match=r"stored redacted \(facts\)"):
        call(tmp_path, "update", identity=row["identity"], status="pass",
             facts=[{"item": "Price", "source": source, "ok": True, "facing": "money"}])
    assert Ledger(tmp_path).get("action", row["identity"])["fields"]["status"] == "pending"  # Nothing was written.


def test_task_types_the_ledger_would_drop_are_refused(tmp_path):
    with pytest.raises(ValueError, match=r"stored redacted \(minutes_by_type\)"):
        call(tmp_path, "baseline", week_of="2026-10-12", minutes_by_type={"passport renewal": 30, "wifi setup": 15})


def test_update_returns_what_was_stored(tmp_path):
    row = record(tmp_path)
    result = call(tmp_path, "update", identity=row["identity"], status="pass", closed_on=row["started"],
                  facts=[{"item": "Price", "source": "https://example.org/pricing", "ok": True, "facing": "money"}])
    stored = Ledger(tmp_path).get("action", row["identity"])["fields"]
    assert {k: v for k, v in result.items() if k != "identity"} == stored


def test_closed_on_is_the_owner_local_close_date(tmp_path):
    row = record(tmp_path, started="2026-10-01", due="2026-10-14")
    call(tmp_path, "update", identity=row["identity"], status="pass", closed_on="2026-10-14")
    assert call(tmp_path, "export", owner="A")["tasks"][0]["closed_at"] == "2026-10-14"
    with pytest.raises(ValueError, match="closed_on must not be before started"):
        call(tmp_path, "update", identity=row["identity"], status="fail", closed_on="2026-09-30")


def test_export_carries_one_profile_id_per_ledger(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    record(a)
    time_records(a)
    record(b)
    first, again, other = call(a, "export", owner="A"), call(a, "export", owner="Alias"), call(b, "export", owner="B")
    assert first["profile"] and first["profile"] == again["profile"] != other["profile"]
    rows = [r for r in Ledger(a).list("action") if r["action_type"] in EVIDENCE_TYPES]
    assert {r["fields"]["profile"] for r in rows} == {first["profile"]}
    with pytest.raises(ValueError, match="same profile exported twice"):
        build("test", "a" * 40, [], [first, again], as_of="2026-10-21")
