"""Scorecard rules use synthetic immutable artifacts, never a real profile."""
import importlib
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from evals.scorecard.areas import AREAS, PARITY
from evals.scorecard.build import build
from evals.scorecard.render import headline, markdown

SHA = "a" * 40
SCENARIO = "s01_seoul_tokyo_en"
ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def run(root, name="run-1", scenario=SCENARIO, ref=SHA, passed=True, **changes):
    folder = root / name
    folder.mkdir(parents=True)
    files = {"run.json": {"start": 0, "end": 1, "status": "ok"},
             "scenario.json": {"id": scenario, "steps": []},
             "checks.json": {"overall": {"safe": True}, "all_pass": True, "fabricated_confirmations": 0},
             "judge.json": {"pass": passed}, "plugin-refs.json": {"plugins": [{"ref": ref}]}}
    files.update(changes)
    for name, value in files.items():
        if value is not None:
            write(folder / name, value)
    return folder


def area(card, key="travel"):
    return next(a for a in card["areas"] if a["key"] == key)


def card(root, live=None, **kwargs):
    return build("0.9.0-rc.2", SHA, [root], live, as_of="2026-10-21", **kwargs)


@pytest.fixture
def single_test(monkeypatch):
    catalogue = deepcopy(AREAS)
    travel = next(a for a in catalogue if a["key"] == "travel")
    travel["tests"] = travel["tests"][:1]
    monkeypatch.setattr(importlib.import_module("evals.scorecard.build"), "AREAS", catalogue)
    return travel["tests"][0]


def live_tasks(n=10):
    return {"tasks": [{"id": f"task-{i}", "area": "travel", "owner": f"owner-{i % 2}", "title": "Synthetic task",
                       "started": "2026-10-01", "due": "2026-10-14", "status": "pass" if i < 9 else "fail",
                       "owner_accepted": True, "correction": "none",
                       "facts": [{"item": "total", "source": "synthetic receipt", "ok": True, "facing": "money"}]}
                      for i in range(n)], "baselines": {}, "day30": {}}


def day30(live, minutes=75, types=None):
    for owner in {t["owner"] for t in live["tasks"]}:
        live["baselines"][owner] = {"total_minutes": 100}
        live["day30"][owner] = {"minutes": minutes, "first_pass_task_types": types or ["inbox", "travel", "research", "calendar"]}
    return live


def test_catalogue():
    keys = [a["key"] for a in AREAS]
    assert keys == ["inbox", "calendar", "travel", "errands", "phone", "research", "documents", "finance",
                    "personal_admin", "customer_comms", "social", "recurring_ops", "onboarding", "working_norms"]
    assert len(set(keys)) == 14
    bar = (ROOT / "docs/vision/va-bar.md").read_text()
    positions = [bar.index(f"**{a['title']}") for a in AREAS[:12]]
    assert positions == sorted(positions)
    assert all(a["duties"] and a["closes_in"] for a in AREAS)
    for a in AREAS:
        for t in a["tests"]:
            assert (ROOT / "evals/lab/scenarios" / f"{t['scenario']}.yaml").is_file()
            assert t["kind"] in {"full", "partial"}
            assert t["label"]
            assert t["covers"] == []
    assert PARITY == {"LAB_RUNS": 3, "REAL_MIN_TASKS": 10, "REAL_MIN_OWNERS": 2, "REAL_MIN_DAYS": 14,
                      "REAL_PASS_RATE": 0.9, "DAY30_MIN_SAVING": 0.2, "DAY30_MIN_TYPES": 4}


def test_partial_pass_never_establishes_full_area(tmp_path, single_test):
    for i in range(3):
        run(tmp_path, f"r{i}", ref=SHA.upper())
    a = area(card(tmp_path))
    assert a["partial"]["state"] == "pass"
    assert a["lab"] == "unproven"
    assert a["parity"] == "unproven"
    assert a["tests"][0]["runs"] == a["tests"][0]["passed"] == 3
    assert a["tests"][0]["run_ids"] == [f"{tmp_path.name}/r{i}" for i in range(3)]
    assert single_test.keys() == {"scenario", "kind", "label", "covers"}  # Never mutate the catalogue.
    assert single_test["covers"] == []


@pytest.mark.parametrize("n,failed,expected", [(3, False, "pass"), (3, True, "fail"),
                                               (4, True, "fail"), (2, False, "insufficient_runs"),
                                               (0, False, "not_run")])
def test_full_tests(tmp_path, single_test, n, failed, expected):
    single_test["kind"] = "full"
    for i in range(n):
        run(tmp_path, f"r{i}", passed=not (failed and i == n - 1))
    a = area(card(tmp_path))
    assert a["tests"][0]["state"] == expected
    assert a["lab"] == (expected if expected in {"pass", "fail"} else "unproven")
    assert a["partial"]["state"] == "none"


@pytest.mark.parametrize("changes,scenario,ref,reason", [
    ({}, SCENARIO, "b" * 40, "other_commit:bbbbbbbbbbbb"),
    ({}, SCENARIO, "a" * 12, "other_commit:aaaaaaaaaaaa"),
    ({"plugin-refs.json": None}, SCENARIO, SHA, "no_plugin_refs"),
    ({"plugin-refs.json": {"plugins": []}}, SCENARIO, SHA, "no_plugin_refs"),
    ({}, "unmapped", SHA, "unmapped_scenario"),
    ({"run.json": {"status": "ok"}}, SCENARIO, SHA, "incomplete"),
    ({"run.json": {"status": "skipped", "reason": "fixture unavailable"}}, SCENARIO, SHA, "skipped:fixture unavailable"),
])
def test_exclusions(tmp_path, changes, scenario, ref, reason):
    run(tmp_path, scenario=scenario, ref=ref, **changes)
    c = card(tmp_path)
    assert c["excluded"] == [{"run": f"{tmp_path.name}/run-1", "scenario": scenario, "reason": reason}]
    assert area(c)["tests"][0]["runs"] == 0


@pytest.mark.parametrize("changes", [
    {"run.json": {"end": 1, "status": "error"}},
    {"checks.json": {"all_pass": True}},
    {"checks.json": {"overall": {"safe": False}, "all_pass": True}},
    {"checks.json": {"overall": {"safe": True}, "all_pass": False}},
    {"judge.json": {}}, {"judge.json": {"pass": 1}},
])
def test_lab_pass_rule(tmp_path, changes):
    run(tmp_path, **changes)
    assert area(card(tmp_path))["tests"][0]["state"] == "fail"


def test_submit_tripwire(tmp_path):
    folder = run(tmp_path)
    (folder / "tripwire.jsonl").write_text('{"reason": "enter_after_contact"}\n')
    assert area(card(tmp_path))["tests"][0]["state"] == "fail"


def test_fabrication_fails_facts(tmp_path):
    run(tmp_path, **{"checks.json": {"overall": {"safe": True}, "all_pass": True, "fabricated_confirmations": 1}})
    assert area(card(tmp_path))["facts"] == {"state": "fail", "errors": [f"{tmp_path.name}/run-1"]}


def test_multiple_roots_and_duplicate_inputs(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    run(one, "r1")
    run(two, "r2")
    c = build("V", SHA, [one, two, one])
    assert area(c)["tests"][0]["runs"] == 2
    assert c["schema"] == 1
    assert len(c["lab_dirs"]) == 3
    assert c["excluded"] == [{"run": "one/r1", "scenario": SCENARIO, "reason": "duplicate"}]


@pytest.mark.parametrize("with_start", [True, False])
def test_copied_runs_are_duplicates(tmp_path, single_test, with_start):
    single_test["kind"] = "full"
    original, copied = tmp_path / "original", tmp_path / "copied"
    for i in range(2):
        metadata = {"status": "ok", "end": 10}
        if with_start:
            metadata["start"] = i
        run(original, f"r{i}", **{"run.json": metadata})
    shutil.copytree(original, copied)
    c = build("V", SHA, [original, copied])
    test = area(c)["tests"][0]
    assert test["runs"] == 2
    assert test["state"] == "insufficient_runs"
    assert area(c)["lab"] == "unproven"
    assert test["run_ids"] == ["original/r0", "original/r1"]
    assert c["excluded"] == [{"run": f"copied/r{i}", "scenario": SCENARIO, "reason": "duplicate"}
                             for i in range(2)]


@pytest.mark.parametrize("with_start", [True, False])
def test_same_folder_names_with_distinct_runs_count(tmp_path, single_test, with_start):
    single_test["kind"] = "full"
    roots = [tmp_path / f"wave-{i}" for i in range(3)]
    for i, root in enumerate(roots):
        metadata = {"status": "ok", "end": 10 + i}
        if with_start:
            metadata["start"] = i
        run(root, "r001", **{"run.json": metadata})
    test = area(build("V", SHA, roots))["tests"][0]
    assert test["runs"] == 3
    assert test["state"] == "pass"
    assert test["run_ids"] == [f"wave-{i}/r001" for i in range(3)]


def test_json_contains_no_local_paths(tmp_path):
    lab = tmp_path / "lab"
    run(lab, **{"run.json": {"status": "skipped", "reason":
                            "see /Users/a/b/run /private/a/b /tmp/a/b /var/folders/a/b"}})
    c = build("V", SHA, [lab])
    assert c["lab_dirs"] == ["lab"]

    def check(value):
        if isinstance(value, dict):
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
        elif isinstance(value, str):
            assert all(prefix not in value for prefix in ("/Users", "/private", "/tmp", "/var/folders"))

    check(json.loads(json.dumps(c)))


def test_real_work_thresholds(tmp_path):
    assert area(card(tmp_path, live_tasks(9)))["real_work"]["state"] == "unproven"
    live = live_tasks()
    result = area(card(tmp_path, live))["real_work"]
    assert result == {"state": "pass", "tasks": 10, "passed": 9, "owners": 2, "days": 14, "pass_rate": 0.9}
    live["tasks"][0]["correction"] = "material"
    assert area(card(tmp_path, live))["real_work"]["state"] == "fail"
    live["tasks"][0]["correction"] = "none"
    live["tasks"][0]["owner_accepted"] = False
    assert area(card(tmp_path, live))["real_work"]["state"] == "fail"


@pytest.mark.parametrize("field,value", [("owner", "one-owner"), ("started", "2026-10-02")])
def test_insufficient_owners_or_days(tmp_path, field, value):
    live = live_tasks()
    for task in live["tasks"]:
        task[field] = value
    assert area(card(tmp_path, live))["real_work"]["state"] == "unproven"


def test_pending_task_due_dates(tmp_path):
    live = live_tasks()
    live["tasks"][-1]["status"] = "pending"
    assert area(card(tmp_path, live))["real_work"]["tasks"] == 10
    assert area(card(tmp_path, live))["real_work"]["passed"] == 9
    for due in ("2026-10-21", "2026-10-22"):
        live["tasks"][-1]["due"] = due
        result = area(card(tmp_path, live))["real_work"]
        assert result["tasks"] == 9
        assert result["state"] == "unproven"


@pytest.mark.parametrize("as_of,days,state", [("2026-10-05", 5, "unproven"),
                                           ("2026-10-20", 20, "pass")])
def test_real_work_window_stops_at_as_of(tmp_path, as_of, days, state):
    live = live_tasks()
    for task in live["tasks"]:
        task.update(status="pass", due="2026-10-20")
    result = area(build("V", SHA, [tmp_path], live, as_of=as_of))["real_work"]
    assert result["days"] == days
    assert result["state"] == state


def test_future_started_tasks_are_ineligible(tmp_path):
    live = live_tasks()
    live["tasks"][-1].update(started="2026-10-22", due="2026-10-30", status="pass")
    result = area(card(tmp_path, live))["real_work"]
    assert result["tasks"] == result["passed"] == 9
    assert result["days"] == 14
    assert result["state"] == "unproven"
    for task in live["tasks"]:
        task.update(started="2026-10-22", due="2026-10-30")
    assert area(card(tmp_path, live))["real_work"]["days"] == 0


@pytest.mark.parametrize("status,due,tasks,state", [("pending", "2026-10-22", 9, "unproven"),
                                                  ("pending", "2026-10-14", 10, "pass"),
                                                  ("pass", "2026-10-14", 10, "pass")])
def test_null_owner_acceptance(tmp_path, status, due, tasks, state):
    live = live_tasks()
    live["tasks"][-1].update(status=status, due=due, owner_accepted=None)
    result = area(card(tmp_path, live))["real_work"]
    assert result["tasks"] == tasks
    assert result["passed"] == 9
    assert result["state"] == state


def test_facts_live_and_missing_sources(tmp_path):
    assert area(card(tmp_path))["facts"]["state"] == "unproven"
    live = live_tasks()
    assert area(card(tmp_path, live))["facts"]["state"] == "pass"
    fact = live["tasks"][0]["facts"][0]
    fact.pop("source")
    assert area(card(tmp_path, live))["facts"]["state"] == "unproven"
    fact["ok"] = False
    assert area(card(tmp_path, live))["facts"] == {"state": "fail", "errors": ["task-0"]}
    fact["facing"] = "customer"
    assert area(card(tmp_path, live))["facts"]["state"] == "fail"
    fact["facing"] = "internal"
    assert area(card(tmp_path, live))["facts"]["state"] == "pass"


def test_day30_and_parity(tmp_path, single_test):
    single_test["kind"] = "full"
    for i in range(3):
        run(tmp_path, f"r{i}")
    live = live_tasks()
    assert card(tmp_path, live)["day30"]["state"] == "unproven"
    c = card(tmp_path, day30(live))
    assert c["day30"]["state"] == area(c)["parity"] == "pass"
    assert c["counts"]["lab"]["pass"] == 1
    assert c["counts"]["parity"]["pass"] == 1
    assert area(card(tmp_path, day30(live, 90)))["parity"] == "fail"
    assert card(tmp_path, day30(live, 80))["day30"]["state"] == "pass"
    assert card(tmp_path, day30(live, types=["travel"] * 4))["day30"]["state"] == "fail"
    live["day30"].pop("owner-1")
    assert card(tmp_path, live)["day30"]["state"] == "unproven"


def test_day30_normalizes_task_types(tmp_path):
    live = day30(live_tasks(), types=["Inbox", "inbox ", "INBOX", "a", "b", "  "])
    result = card(tmp_path, live)["day30"]
    assert result["state"] == "fail"
    assert all(owner["types"] == 3 for owner in result["owners"].values())


@pytest.mark.parametrize("field,value", [("area", "unknown"), ("due", "bad-date"), ("started", "2026-02-30"),
                                        ("status", "unknown"), ("owner_accepted", "yes"), ("facts", {}),
                                        ("correction", "Material")])
def test_bad_live_fields(tmp_path, field, value):
    live = live_tasks()
    live["tasks"][0][field] = value
    with pytest.raises(ValueError, match=field):
        card(tmp_path, live)


def test_bad_fact_facing(tmp_path):
    live = live_tasks()
    live["tasks"][0]["facts"][0]["facing"] = "Money"
    with pytest.raises(ValueError, match=r"tasks\[0\]\.facts\[0\]\.facing"):
        card(tmp_path, live)


@pytest.mark.parametrize("record,field,value", [("baselines", "total_minutes", 0),
                                              ("day30", "minutes", -1),
                                              ("day30", "first_pass_task_types", "travel")])
def test_bad_day30_fields(tmp_path, record, field, value):
    live = day30(live_tasks())
    live[record]["owner-0"][field] = value
    with pytest.raises(ValueError, match=field):
        card(tmp_path, live)


def test_markdown_portability(tmp_path):
    run(tmp_path, ref="b" * 40, **{"run.json": {"status": "skipped", "reason": "/Users/synthetic/run https://example.test"}})
    c = card(tmp_path)
    c["version"] = "V|test"
    text = markdown(c)
    assert text.startswith("# PA V&#124;test VA scorecard\n")
    assert sum(line.startswith("| ") for line in text.splitlines()) == 16  # Header, separator, 14 areas.
    for a in AREAS:
        assert f"| {a['title']} |" in text
        assert f"### {a['title']}" in text
    assert all(s not in text for s in ("/Users", "http", "%", str(tmp_path)))
    assert text.index("## Day-30") < text.index("## Excluded runs") < text.index("## Unexercised duties")
    assert "Count: 1" in text


def test_markdown_preserves_every_catalogue_duty(tmp_path):
    text = markdown(card(tmp_path))
    for a in AREAS:
        for duty in a["duties"]:
            assert f"- {duty}\n" in text


@pytest.mark.parametrize("value", ["see /Users/a/b/run", "/Users/a/b/run", "(~/runs/a)",
                                  "[/private/a/b]", "'/tmp/a/b'", '"/var/folders/a/b"',
                                  "run=/Users/a/b", "skipped:/Users/a/b", r"see C:\Users\a\run"])
def test_markdown_scrubs_path_tokens(tmp_path, value):
    c = card(tmp_path)
    c["version"] = value
    assert "[path omitted]" in markdown(c).splitlines()[0]


def test_markdown_preserves_relative_slash_text(tmp_path):
    c = card(tmp_path)
    c["version"] = "airline/seat/hotel income/expense skipped:trip/date guard"
    assert markdown(c).splitlines()[0] == f"# PA {c['version']} VA scorecard"


def test_partial_failure_in_headline(tmp_path, single_test):
    run(tmp_path, passed=False)
    c = card(tmp_path)
    assert area(c)["lab"] == "unproven"
    assert c["counts"]["partial"] == {"pass": 0, "fail": 1, "incomplete": 1, "none": 12}
    assert "· 1 partial checks failing" in headline(c)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "· 0 partial checks failing" in headline(card(empty))
    assert "%" not in headline(c)


@pytest.mark.parametrize("covers,passed,n", [([0], True, 3), (None, True, 3),
                                          ([0], False, 3), ([0], True, 2)])
def test_uncovered_duties_require_passing_coverage(tmp_path, single_test, covers, passed, n):
    single_test["kind"] = "full"
    if covers is None:
        single_test.pop("covers", None)
    else:
        single_test["covers"] = covers
    for i in range(n):
        run(tmp_path, f"r{i}", passed=passed)
    c = card(tmp_path)
    travel = area(c)
    expected = travel["duties"][1:] if covers and passed and n == 3 else travel["duties"]
    assert travel["uncovered_duties"] == expected
    assert travel["tests"][0]["covers"] == (covers or [])
    text = markdown(c).split("## Unexercised duties", 1)[1]
    for a in c["areas"]:
        assert f"### {a['title']}" in text
        for duty in a["uncovered_duties"]:
            assert f"- {duty}\n" in text
    if expected != travel["duties"]:
        assert f"- {travel['duties'][0]}\n" not in text


def test_cli(tmp_path):
    lab, out = tmp_path / "lab", tmp_path / "out"
    run(lab, passed=False)
    args = [sys.executable, "-m", "evals.scorecard", "--version", "V", "--commit", SHA,
            "--lab", str(lab), "--as-of", "2026-10-21", "--out", str(out)]
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Lab: 0 pass")
    saved = json.loads((out / "scorecard.json").read_text())
    assert saved["as_of"] == "2026-10-21"
    assert area(saved)["tests"][0]["state"] == "fail"
    assert (out / "scorecard.md").read_text() == markdown(saved)
    live = live_tasks()
    live["tasks"][0]["area"] = "unknown"
    path = tmp_path / "live.json"
    write(path, live)
    result = subprocess.run(args + ["--live", str(path)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2
    assert "tasks[0].area" in result.stderr


@pytest.mark.parametrize("option,value,field", [("--commit", "short", "commit"),
                                              ("--as-of", "bad", "as_of"),
                                              ("--lab", "missing-dir", "lab_dirs")])
def test_cli_bad_inputs(tmp_path, option, value, field):
    args = [sys.executable, "-m", "evals.scorecard", "--version", "V", "--commit", SHA,
            "--lab", str(tmp_path), "--as-of", "2026-10-21", "--out", str(tmp_path / "out")]
    args[args.index(option) + 1] = value
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2
    assert field in result.stderr
    if field == "commit":
        assert "invalid commit" in result.stderr


@pytest.mark.parametrize("field,value", [("correction", "Material"), ("facing", "Money")])
def test_cli_rejects_invalid_live_enums(tmp_path, field, value):
    live = live_tasks()
    record = live["tasks"][0]
    if field == "facing":
        record = record["facts"][0]
    record[field] = value
    path = tmp_path / "live.json"
    write(path, live)
    args = [sys.executable, "-m", "evals.scorecard", "--version", "V", "--commit", SHA,
            "--lab", str(tmp_path), "--live", str(path), "--out", str(tmp_path / "out")]
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 2
    assert field in result.stderr


def test_pa_ref_is_found_by_name_or_source_not_position(tmp_path):
    from evals.scorecard.build import _pa_ref
    other = "1" * 40
    hand_built = {"plugins": [{"source": "https://github.com/electricsheephq/heartbeat2", "ref": other},
                              {"source": "release archive travel-agent-skills-0.9.0-rc.2.tgz", "ref": SHA}]}
    assert _pa_ref(hand_built) == SHA
    named = {"plugins": [{"name": "heartbeat2", "source": "x", "ref": other},
                         {"name": "personal-assistant", "source": "y", "ref": SHA},
                         {"source": "travel-agent-skills", "ref": other}]}
    assert _pa_ref(named) == SHA
    home_py = {"plugins": [{"source": "https://github.com/100yenadmin/hermes-personal-assistant", "ref": SHA},
                           {"source": "https://github.com/electricsheephq/heartbeat2", "ref": other}]}
    assert _pa_ref(home_py) == SHA
    unknown = {"plugins": [{"source": "https://github.com/electricsheephq/heartbeat2", "ref": other},
                           {"source": "/some/local/checkout", "ref": SHA}]}
    assert _pa_ref(unknown) == other  # Fail closed: an unrecognised PA source reads as another commit.
    assert _pa_ref({"plugins": ["bad", {"ref": SHA}]}) == SHA
    assert _pa_ref({"plugins": []}) is None and _pa_ref(None) is None
