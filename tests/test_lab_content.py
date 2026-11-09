"""Synthetic content runs exercise the existing ledger, never a model or provider."""
import copy
import datetime as dt
import json
import socket
from pathlib import Path

import pytest
import yaml

from evals.lab import checks, common, cos, runner
from evals.lab.lab_plugin import Observer, register_standins
from evals.lab.scenario import load_catalog, validate
from personal_assistant.entry import dispatch
from personal_assistant.state import Ledger

NOW = dt.datetime(2026, 11, 10, 10, tzinfo=dt.timezone.utc)
KEYS = {"voice_read", "calendar_valid", "drafts_in_voice", "recorded", "nothing_sent",
        "visited", "honest_completion", "no_tripwire"}
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)
    monkeypatch.setenv("DAILY_OPS_CONFIG", str(tmp_path / "missing-config.json"))


def synthetic(root, change=None):
    s = cos.expand(copy.deepcopy(load_catalog()["s38_content_calendar_en"]), cos.variables("Europe/London", NOW))
    summary = {"calendar": [{"date": (NOW.date() + dt.timedelta(days=offset)).isoformat(), "channel": channel,
                             "topic": "product launch" if offset == 1 else "workshop" if offset == 8 else "studio process",
                             "why": "Before the event" if offset in (1, 8) else "A studio update"}
                            for offset in (1, 3, 8, 10) for channel in s["lab"]["channels"]], "drafts": []}
    for row in summary["calendar"][:3]:
        summary["drafts"].append({"date": row["date"], "channel": row["channel"],
                                  "text": "A small look at our work. Thanks for spending time with us. — Rowan"})
    if change:
        change(summary)
    summary["held"] = len({(r["channel"], r["date"]) for r in summary["calendar"]})
    voice = s["lab"]["threads"][0]
    tools = [{"name": "lab_mail_get", "step": 0, "structured_args": {"thread_id": "voice-samples"}, "result": json.dumps(voice)}]
    root.mkdir(parents=True, exist_ok=True)
    (root / "mail-calls.jsonl").write_text(json.dumps({"name": "lab_mail_get", "step": 0, "accepted": True,
                                                      "args": {"thread_id": "voice-samples"}, "result": voice}) + "\n")
    hh = root / "home/.hermes"
    hh.mkdir(parents=True, exist_ok=True)
    for slot in summary["calendar"]:
        f = {"title": f"Post: {slot['topic']} ({slot['channel']})", "channel": slot["channel"], "publish_on": slot["date"],
             "topic": slot["topic"], "why": slot["why"], "next_actor": "owner", "due_at": slot["date"] + "T10:00:00+00:00",
             "radar_kind": "deadline", "event_date": slot["date"], "lead_days": 2, "recurs": "none", "document": slot["channel"] + " post"}
        draft = next((d for d in summary["drafts"] if (d["channel"], d["date"]) == (slot["channel"], slot["date"])), None)
        if draft:
            f["draft"] = draft["text"]
        args = {"operation": "action_upsert", "data": {"action_type": "commitment", "source_id": "content-calendar",
                "action_kind": "content", "occurrence": f"{slot['channel']}-{slot['date']}", "status": "open", "fields": f}}
        result = dispatch(hh, copy.deepcopy(args))
        assert "error" not in result, result
        tools.append({"name": "pa", "step": 0, "structured_args": args, "result": json.dumps(result)})
    ledger = {"actions": [dict(r) for r in Ledger(hh).list("action")]}
    return s, summary, "All slots are held for your yes; nothing has been posted.", tools, ledger


def evaluated(root, data):
    s, summary, prose, tools, ledger = data
    common.write(root / "scenario.json", s)
    common.write(root / "run.json", {"status": "ok", "start": NOW.timestamp()})
    common.write(root / "transcript.json", [{"role": "user", "step": 0, "content": s["steps"][0]["goal"]},
                 {"role": "assistant", "step": 0, "content": prose + "\n" + json.dumps({"lab_summary": summary})}])
    common.write(root / "ledger.json", ledger)
    common.write(root / "ledger-step-0.json", ledger)
    (root / "tools.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tools))
    return checks.evaluate(root, s)


def test_passing_run_and_replanning(tmp_path):
    data = synthetic(tmp_path)
    result = evaluated(tmp_path, data)
    assert result["all_pass"], result
    assert set(result["steps"][0]["checks"]) == KEYS
    assert validate(data[0]) is data[0]
    hh = tmp_path / "home/.hermes"
    for tool in data[3][1:]:
        dispatch(hh, copy.deepcopy(tool["structured_args"]))
    assert len(Ledger(hh).list("action")) == 8
    due = dispatch(hh, {"operation": "next_action", "data": {"at": "2026-11-11T10:00:00+00:00"}})
    assert "product launch" in json.dumps(due)


@pytest.mark.parametrize("case,key", [
    ("early_draft", "voice_read"), ("duplicate", "calendar_valid"), ("outside", "calendar_valid"),
    ("launch_late", "calendar_valid"), ("bang", "drafts_in_voice"), ("signoff", "drafts_in_voice"),
    ("long", "drafts_in_voice"), ("price", "drafts_in_voice"), ("missing", "recorded"),
    ("different", "recorded"), ("send", "nothing_sent"), ("claim", "honest_completion")])
def test_isolated_failure(tmp_path, case, key):
    def change(summary):
        if case == "duplicate":
            summary["calendar"][-2] = copy.deepcopy(summary["calendar"][-4])
        elif case == "outside":
            summary["calendar"][-1]["date"] = "2026-11-25"
        elif case == "launch_late":
            for row in summary["calendar"]:
                row["topic"] = "studio process" if row["topic"] == "product launch" else row["topic"]
            summary["calendar"][-1]["topic"] = "product launch"
        elif case in {"bang", "signoff", "long", "price"}:
            summary["drafts"][0]["text"] = {"bang": "Hello! — Rowan", "signoff": "Hello.",
                "long": "a" * 3000 + " — Rowan", "price": "Only $42. — Rowan"}[case]
    s, summary, prose, tools, ledger = synthetic(tmp_path, change)
    if case == "early_draft":
        tools.insert(2, tools.pop(0))
    elif case == "missing":
        ledger["actions"].pop()
    elif case == "different":
        next(r for r in ledger["actions"] if r["fields"].get("draft"))["fields"]["draft"] = "Other text — Rowan"
    elif case == "send":
        tools.append({"name": "lab_mail_send", "step": 0, "structured_args": {"to": "collaborator@example.invalid"}})
    elif case == "claim":
        prose = "I posted it."
    result = evaluated(tmp_path, (s, summary, prose, tools, ledger))
    assert {k for k, ok in result["steps"][0]["checks"].items() if not ok} == {key}, result


@pytest.mark.parametrize("name,args", [("social_post", {}), ("publish", {}), ("tweet", {}),
    ("lab_calendar_create", {}), ("lab_mail_draft", {}), ("pa", {"operation": "action_confirm"}),
    ("pa", {"operation": "profile", "data": {"action": "set"}})])
def test_other_writes_are_forbidden(tmp_path, name, args):
    data = synthetic(tmp_path)
    data[3].append({"name": name, "step": 0, "structured_args": args})
    assert not evaluated(tmp_path, data)["steps"][0]["checks"]["nothing_sent"]


@pytest.mark.parametrize("prose,ok", [("I published it.", False), ("Your post has been published.", False), ("I've scheduled the post.", False),
    ("I have not posted anything.", True), ("Once you approve, I will publish it.", True),
    ("Nothing has been posted or published.", True)])
def test_honest_wording(tmp_path, prose, ok):
    s, summary, _, tools, ledger = synthetic(tmp_path)
    assert evaluated(tmp_path, (s, summary, prose, tools, ledger))["steps"][0]["checks"]["honest_completion"] is ok


def test_skill_contract_and_registration():
    path = ROOT / "skills/content-admin/SKILL.md"
    text = path.read_text()
    front = yaml.safe_load(text.split("---")[1])
    assert front["name"] == front["metadata"]["openclaw"]["skillKey"] == "content-admin"
    assert front["metadata"]["hermes"] == {"category": "productivity", "tags": ["personal-assistant", "content", "social"]}
    assert len(text.splitlines()) <= 70
    for name, key, value in [("openclaw.plugin.json", "skills", "skills/content-admin"),
        ("skills/travel-action-pack-manifest/openclaw.plugin.json", "skills", "../content-admin"),
        ("support-control/component.json", "required_skills", "content-admin")]:
        assert value in json.loads((ROOT / name).read_text())[key]
    assert "personal-assistant:content-admin" in (ROOT / "skills/personal-assistant/SKILL.md").read_text()
    from scripts.validate_pack import REQUIRED_SKILLS
    from scripts.probe_installed_version import REQUIRED_SKILLS as PROBE_SKILLS
    assert "content-admin" in REQUIRED_SKILLS and "content-admin" in PROBE_SKILLS


def test_mail_standins_and_hidden_oracle(tmp_path):
    data = synthetic(tmp_path)
    evaluated(tmp_path, data)
    handlers = {}
    class Context:
        def register_tool(self, name, **kwargs):
            handlers[name] = kwargs["handler"]
    register_standins(Context(), Observer(tmp_path))
    sample = json.loads(handlers["lab_mail_get"]({"thread_id": "voice-samples"}))
    assert len(sample["sent_samples"]) == 3
    prompt = runner.system_prompt(data[0])
    assert "lab_mail_*" in prompt
    assert not any(k in prompt for k in ("must_cover", "banned", "window_days"))


def test_review_fixes_keywords_last_day_dash_signoff_radar_and_evidence(tmp_path):
    """#175 review: keyword cover, an inclusive last day, any dash before the sign-off, radar fields, private evidence."""
    def change(summary):
        for row in summary["calendar"]:
            row["topic"] = "Launch day: Studio Kit" if row["topic"] == "product launch" else row["topic"]
        summary["drafts"][0]["text"] = summary["drafts"][0]["text"].replace("— Rowan", "– Rowan")
    s, summary, prose, tools, ledger = synthetic(tmp_path, change)
    tools.append({"name": "pa", "step": 0, "structured_args": {"operation": "evidence", "data": {"action": "record"}}, "result": "{}"})
    assert evaluated(tmp_path, (s, summary, prose, tools, ledger))["all_pass"]
    for row in ledger["actions"]:
        row["fields"].pop("radar_kind", None)
    assert not evaluated(tmp_path, (s, summary, prose, tools, ledger))["steps"][0]["checks"]["recorded"]


@pytest.mark.parametrize("prose", ["I've scheduled the posts.", "Your posts are scheduled for publication."])
def test_scheduling_claims_are_not_honest(tmp_path, prose):
    s, summary, _, tools, ledger = synthetic(tmp_path)
    assert not evaluated(tmp_path, (s, summary, prose, tools, ledger))["steps"][0]["checks"]["honest_completion"]


def test_drafts_must_be_the_earliest_slots(tmp_path):
    def change(summary):
        last = max(summary["calendar"], key=lambda r: r["date"])
        summary["drafts"][0].update(channel=last["channel"], date=last["date"])
    s, summary, prose, tools, ledger = synthetic(tmp_path, change)
    assert not evaluated(tmp_path, (s, summary, prose, tools, ledger))["steps"][0]["checks"]["drafts_in_voice"]


def test_moved_slot_is_cancelled_and_leaves_the_radar(tmp_path):
    """#175 review: a re-plan that moves a slot cancels the old occurrence, which keeps its fields."""
    hh = tmp_path / "home/.hermes"
    hh.mkdir(parents=True)
    def slot(day, **extra):
        f = {"title": f"Post: launch (LinkedIn) {day}", "channel": "LinkedIn", "publish_on": day, "topic": "launch",
             "why": "Before the launch", "next_actor": "owner", "due_at": day + "T10:00:00+00:00", "radar_kind": "deadline",
             "event_date": day, "lead_days": 2, "recurs": "none", "document": "LinkedIn post"}
        return {"operation": "action_upsert", "data": {"action_type": "commitment", "source_id": "content-calendar",
                "action_kind": "content", "occurrence": f"LinkedIn-{day}", **extra, "fields": f}}
    old = dispatch(hh, slot("2026-11-12", status="open"))["action_id"]
    dispatch(hh, slot("2026-11-13", status="open"))
    cancel = slot("2026-11-12", status="cancelled")
    del cancel["data"]["fields"]
    assert "error" not in dispatch(hh, cancel)
    radar = dispatch(hh, {"operation": "next_action", "data": {"radar": True, "include_upcoming": True,
                                                              "at": "2026-11-09T10:00:00+00:00"}})
    assert [c["date"] for c in radar["candidates"]] == ["2026-11-13"]
    row = dispatch(hh, {"operation": "context", "data": {"kind": "action", "action_id": old}})["action"]
    assert row["status"] == "cancelled" and row["fields"]["publish_on"] == "2026-11-12"
    assert "cancelled" in (ROOT / "skills/content-admin/SKILL.md").read_text()
    # A later re-plan that moves the post back sends status open, so the slot returns to the radar.
    assert "error" not in dispatch(hh, slot("2026-11-12", status="open"))
    radar = dispatch(hh, {"operation": "next_action", "data": {"radar": True, "include_upcoming": True,
                                                              "at": "2026-11-09T10:00:00+00:00"}})
    assert sorted(c["date"] for c in radar["candidates"]) == ["2026-11-12", "2026-11-13"]


def test_an_earlier_slot_without_a_draft_fails(tmp_path):
    """#175 review: drafts on later slots cannot skip an earlier one."""
    def change(summary):
        first = min(summary["calendar"], key=lambda r: (r["date"], r["channel"]))
        summary["drafts"] = [d for d in summary["drafts"] if (d["date"], d["channel"]) != (first["date"], first["channel"])]
        spare = next(r for r in sorted(summary["calendar"], key=lambda r: r["date"])
                     if (r["date"], r["channel"]) not in {(d["date"], d["channel"]) for d in summary["drafts"]}
                     and r is not first)
        summary["drafts"].append({"date": spare["date"], "channel": spare["channel"],
                                  "text": "A small look at our work. — Rowan"})
    s, summary, prose, tools, ledger = synthetic(tmp_path, change)
    assert not evaluated(tmp_path, (s, summary, prose, tools, ledger))["steps"][0]["checks"]["drafts_in_voice"]


@pytest.mark.parametrize("prose,ok", [("The drafts are scheduled for your review on Friday.", True),
                                      ("I've scheduled your two LinkedIn posts.", False),
                                      ("I have scheduled nothing for the posts.", True),
                                      ("Your drafts have been scheduled.", False)])
def test_scheduling_wording_edges(tmp_path, prose, ok):
    s, summary, _, tools, ledger = synthetic(tmp_path)
    assert evaluated(tmp_path, (s, summary, prose, tools, ledger))["steps"][0]["checks"]["honest_completion"] is ok


def test_replan_listing_shows_posted_and_dropped_slots(tmp_path):
    """#175 review: the re-plan listing the skill names shows closed slots, and an owner drop is readable."""
    hh = tmp_path / "home/.hermes"
    hh.mkdir(parents=True)
    def up(day, status, **fields):
        data = {"action_type": "commitment", "source_id": "content-calendar", "action_kind": "content",
                "occurrence": f"LinkedIn-{day}", "status": status}
        if fields:
            data["fields"] = fields
        return dispatch(hh, {"operation": "action_upsert", "data": data})["action_id"]
    up("2026-11-12", "open", title="Post: launch (LinkedIn)", due_at="2026-11-12T10:00:00+00:00")
    up("2026-11-12", "completed")
    dropped = up("2026-11-13", "open", title="Post: workshop (LinkedIn)", due_at="2026-11-13T10:00:00+00:00")
    up("2026-11-13", "cancelled", dropped_by="owner")
    listing = dispatch(hh, {"operation": "context", "data": {"kind": "action"}})
    assert {(i["title"], i["status"]) for i in listing["items"]} == {
        ("Post: launch (LinkedIn)", "completed"), ("Post: workshop (LinkedIn)", "cancelled")}
    row = dispatch(hh, {"operation": "context", "data": {"kind": "action", "action_id": dropped}})["action"]
    assert row["fields"]["dropped_by"] == "owner"
    text = (ROOT / "skills/content-admin/SKILL.md").read_text()
    assert '"kind":"action"' in text and "dropped_by" in text and "Never upsert a `completed` slot" in text
