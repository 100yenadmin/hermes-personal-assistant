"""Synthetic P5 snapshots only: importing the oracle never loads the rig."""
import copy
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

from evals.concierge_e2e.follow_checks import score_chase_at


ASKED = dt.datetime(2026, 11, 12, 12, 11, tzinfo=dt.timezone.utc)
CHECKS = {
    "one_cedar_loop", "chase_at_is_owner_time", "owner_wake_armed", "quiet_until_due",
    "wake_fired_once", "wake_reply_raises_cedar", "wake_reply_holds_draft", "no_send_recorded",
    "chase_recorded", "loop_still_open", "nothing_after",
}


def passing_snapshot():
    wake = {"id": "pa-chase", "kind": "at", "owner_requested": 1, "creator": "agent",
            "parent_wake_id": None, "babysit": 0, "status": "active", "trigger_json": "{}",
            "created_at": (ASKED - dt.timedelta(minutes=10)).timestamp(),
            "next_due_at": ASKED.timestamp()}
    occurrence = {"wake_id": "pa-chase", "dedupe_key": "t:synthetic", "state": "done",
                  "started_at": (ASKED + dt.timedelta(seconds=2)).timestamp(),
                  "ended_at": (ASKED + dt.timedelta(seconds=20)).timestamp(), "delivered": 1}
    before = {"wakes": [wake], "occurrences": []}
    after = {"wakes": [{**wake, "status": "completed", "next_due_at": None}],
             "occurrences": [occurrence]}
    return {
        "asked": ASKED.isoformat(), "dm_sent_at": (ASKED - dt.timedelta(minutes=11)).isoformat(),
        "loops": [{"action_id": "cedar-contract", "status": "pending", "action_type": "commitment",
                   "fields": {"loop_kind": "waiting_on_them", "counterparty": "Cedar Demo",
                              "title": "Signed services contract", "chase_at": ASKED.isoformat(),
                              "chase_log": [{"at": (ASKED + dt.timedelta(seconds=10)).isoformat(),
                                             "how": "nudge draft held", "step": "day2"}]}}],
        "hb2": {"before": before, "after": after, "tail": copy.deepcopy(after)},
        "day0_texts": ["I'll track the contract and show you a draft at the time you asked."],
        "day0_settled_at": (ASKED - dt.timedelta(minutes=9)).isoformat(),
        "wake_texts": ["Cedar Demo's contract is still outstanding. The chase draft is held for your yes."],
        "wake_text_times": [(ASKED + dt.timedelta(seconds=20)).isoformat()], "late_texts": [],
    }


@pytest.mark.parametrize("json_fields", [False, True])
def test_all_checks_pass(json_fields):
    snapshot = passing_snapshot()
    if json_fields:
        row = snapshot["loops"][0]
        row["fields_json"] = json.dumps(row.pop("fields"))
    original = copy.deepcopy(snapshot)
    result = score_chase_at(snapshot)
    assert set(result) == CHECKS
    assert all(type(value) is bool and value for value in result.values()), result
    assert snapshot == original  # The oracle is pure.


@pytest.mark.parametrize("change,key", [
    ("no_loop", "one_cedar_loop"),
    ("two_loops", "one_cedar_loop"),
    ("wrong_chase_time", "chase_at_is_owner_time"),
    ("no_wake", "owner_wake_armed"),
    ("midnight_wake", "owner_wake_armed"),
    ("role_wake", "owner_wake_armed"),
    ("old_wake", "owner_wake_armed"),
    ("early_message", "quiet_until_due"),
    ("two_occurrences", "wake_fired_once"),
    ("early_occurrence", "wake_fired_once"),
    ("late_occurrence", "wake_fired_once"),
    ("wrong_wake_occurrence", "wake_fired_once"),
    ("unfinished_occurrence", "wake_fired_once"),
    ("no_cedar", "wake_reply_raises_cedar"),
    ("no_contract", "wake_reply_raises_cedar"),
    ("sent_chase", "wake_reply_holds_draft"),
    ("nudge_row_completed", "no_send_recorded"),
    ("sent_log_entry", "no_send_recorded"),
    ("pending_other_wake_ignored", None),
    ("not_sent_log_ignored", None),
    ("tail_starts_pending_other", "nothing_after"),
    ("early_message_carries_reply", "wake_reply_holds_draft"),
    ("draft_prepared_log", "chase_recorded"),
    ("undelivered_occurrence", "wake_fired_once"),
    ("other_wake_in_window", "wake_fired_once"),
    ("child_wake", "owner_wake_armed"),
    ("babysit_wake", "owner_wake_armed"),
    ("system_wake", "owner_wake_armed"),
    ("every_wake", "owner_wake_armed"),
    ("inactive_wake", "owner_wake_armed"),
    ("builtin_wake", "owner_wake_armed"),
    ("late_settle", "quiet_until_due"),
    ("missing_time", "quiet_until_due"),
    ("no_log", "chase_recorded"),
    ("early_log", "chase_recorded"),
    ("sent_log", "chase_recorded"),
    ("closed_loop", "loop_still_open"),
    ("late_message", "nothing_after"),
    ("tail_occurrence", "nothing_after"),
])
def test_targeted_failure(change, key):
    snapshot = passing_snapshot()
    data = snapshot["loops"][0]["fields"]
    wake = snapshot["hb2"]["before"]["wakes"][0]
    occurrences = snapshot["hb2"]["after"]["occurrences"]
    if change == "no_loop":
        snapshot["loops"] = []
    elif change == "two_loops":
        snapshot["loops"].append({**copy.deepcopy(snapshot["loops"][0]), "action_id": "cedar-duplicate"})
    elif change == "wrong_chase_time":
        data["chase_at"] = (ASKED + dt.timedelta(minutes=20)).isoformat()
    elif change == "no_wake":
        snapshot["hb2"]["before"]["wakes"] = []
    elif change == "midnight_wake":
        wake["next_due_at"] = ASKED.replace(hour=0, minute=0).timestamp()
    elif change == "role_wake":
        wake["owner_requested"] = 0
    elif change == "old_wake":
        wake["created_at"] = (ASKED - dt.timedelta(days=1)).timestamp()
    elif change == "early_message":
        snapshot["wake_text_times"][0] = (ASKED - dt.timedelta(minutes=1)).isoformat()
    elif change == "two_occurrences":
        occurrences.append({**occurrences[0], "dedupe_key": "t:duplicate"})
    elif change == "early_occurrence":
        occurrences[0]["started_at"] = (ASKED - dt.timedelta(minutes=1)).timestamp()
    elif change == "late_occurrence":
        occurrences[0]["ended_at"] = (ASKED + dt.timedelta(minutes=6)).timestamp()
    elif change == "wrong_wake_occurrence":
        occurrences[0]["wake_id"] = "role-wake"
    elif change == "unfinished_occurrence":
        occurrences[0]["state"] = "started"
    elif change in {"no_cedar", "no_contract"}:
        word = "Cedar" if change == "no_cedar" else "contract"
        snapshot["wake_texts"][0] = snapshot["wake_texts"][0].replace(word, "item")
    elif change == "sent_chase":
        snapshot["wake_texts"] = ["Cedar's contract: I've sent the chase."]
    elif change == "nudge_row_completed":
        snapshot["loops"].append({"action_id": "cedar-contract:nudge:day2", "status": "completed", "action_type": "transaction", "fields": {}})
    elif change == "sent_log_entry":
        data["chase_log"].append({"at": (ASKED + dt.timedelta(seconds=15)).isoformat(), "how": "nudge sent", "step": "day2"})
    elif change == "not_sent_log_ignored":
        data["chase_log"][0]["how"] = "nudge draft held, not sent"
    elif change == "tail_starts_pending_other":
        pending = {"wake_id": "other-agent-wake", "dedupe_key": "t:pending", "state": "pending", "started_at": None}
        occurrences.append(pending)
        snapshot["hb2"]["tail"]["occurrences"].append({**pending, "state": "done",
                                                        "started_at": (ASKED + dt.timedelta(minutes=4)).timestamp()})
    elif change == "early_message_carries_reply":
        snapshot["wake_texts"] = ["Cedar contract: the chase draft is held for your yes.", "Checked in."]
        snapshot["wake_text_times"] = [(ASKED - dt.timedelta(seconds=10)).isoformat(),
                                       (ASKED + dt.timedelta(seconds=20)).isoformat()]
    elif change == "draft_prepared_log":
        data["chase_log"][0]["how"] = "draft prepared"
    elif change == "pending_other_wake_ignored":
        pending = {"wake_id": "other-agent-wake", "dedupe_key": "t:pending", "state": "pending", "started_at": None}
        occurrences.append(pending)
        snapshot["hb2"]["tail"]["occurrences"].append(dict(pending))  # Present before and after the tail: not new.
    elif change == "undelivered_occurrence":
        occurrences[0]["delivered"] = 0
    elif change == "other_wake_in_window":
        occurrences.append({**occurrences[0], "wake_id": "other-agent-wake", "dedupe_key": "t:other"})
    elif change == "child_wake":
        wake["parent_wake_id"] = "parent"
    elif change == "babysit_wake":
        wake["babysit"] = 1
    elif change == "system_wake":
        wake["creator"] = "system"
    elif change == "every_wake":
        wake["kind"] = "every"
    elif change == "inactive_wake":
        wake["status"] = "cancelled"
    elif change == "builtin_wake":
        wake["trigger_json"] = '{"builtin": true}'
    elif change == "late_settle":
        snapshot["day0_settled_at"] = ASKED.isoformat()
    elif change == "missing_time":
        snapshot["wake_text_times"] = []
    elif change == "no_log":
        data.pop("chase_log")
    elif change == "early_log":
        data["chase_log"][0]["at"] = (ASKED - dt.timedelta(minutes=2)).isoformat()
    elif change == "sent_log":
        data["chase_log"][0]["how"] = "nudge sent"
    elif change == "closed_loop":
        data["confirmation"] = {"by": "Cedar Demo", "at": ASKED.isoformat(), "evidence": "signed copy"}
    elif change == "late_message":
        snapshot["late_texts"] = ["Another nudge."]
    elif change == "tail_occurrence":
        snapshot["hb2"]["tail"]["occurrences"].append({**occurrences[0], "dedupe_key": "t:tail", "state": "pending"})
    result = score_chase_at(snapshot)
    if key is None:  # A control: this change must not fail any check.
        assert all(result.values()), result
        return
    assert result[key] is False, result
    assert not all(result.values())


@pytest.mark.parametrize("name_field", ["counterparty", "title", "text"])
def test_cedar_name_fields_and_case(name_field):
    snapshot = passing_snapshot()
    data = snapshot["loops"][0]["fields"]
    data.pop("counterparty")
    data["title"] = "Signed contract"
    data[name_field] = "cEdAr Demo"
    assert all(score_chase_at(snapshot).values())


def test_done_unconfirmed_is_not_closed_but_is_not_open():
    snapshot = passing_snapshot()
    snapshot["loops"][0]["status"] = "done"
    result = score_chase_at(snapshot)
    assert result["one_cedar_loop"] is True
    assert result["loop_still_open"] is False


RUNNER_DIR = Path(__file__).resolve().parents[1] / "evals" / "concierge_e2e"
REPO = Path(__file__).resolve().parents[1]


def _with_fake_pin(tmp_path, body):
    """Run body in a fresh interpreter, with a stand-in pin that ships its own top-level evals package."""
    pin = tmp_path / "pin"
    (pin / "evals").mkdir(parents=True)
    (pin / "evals" / "__init__.py").write_text("PIN = True\n")
    code = "\n".join(["import sys", "from pathlib import Path", f"sys.path.insert(0, {str(RUNNER_DIR)!r})",
                      f"pin = Path({str(pin)!r})", body])
    return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=tmp_path)


def test_the_runner_binds_pa_evals_before_the_pin_goes_first(tmp_path):
    done = _with_fake_pin(tmp_path, "\n".join([
        "import test_follow_live as runner", "runner.bind_paths(pin)",
        "assert sys.path[0] == str(pin), sys.path[:3]",
        "from evals.concierge_e2e.follow_checks import score_chase_at, owner_wakes",
        "import evals", "print(Path(evals.__file__).resolve())"]))
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(REPO / "evals" / "__init__.py")


def test_without_binding_the_pin_shadows_pa_evals(tmp_path):  # Positive control: the stand-in pin really shadows.
    done = _with_fake_pin(tmp_path, "\n".join([
        f"sys.path[:0] = [str(pin), {str(REPO)!r}]",
        "from evals.concierge_e2e.follow_checks import score_chase_at"]))
    assert done.returncode != 0
    assert "No module named 'evals.concierge_e2e'" in done.stderr
