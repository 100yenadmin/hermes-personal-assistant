import datetime as dt
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from personal_assistant.context import next_actions
from personal_assistant.entry import SCHEMA, dispatch
from personal_assistant.radar import radar_item, scan
from personal_assistant.state import Ledger

TODAY = dt.date(2026, 11, 8)
AT = "2026-11-08T10:00:00+09:00"
UNKNOWN = {"status": "unknown", "evidence": "fixture adapter unavailable"}
COST_GAP = "cost must be {amount, currency, per month|year}"


def _action(**fields):
    return {"action_id": "subscription", "fields": {
        "radar_kind": "renewal", "title": "Synthetic subscription",
        "expires_on": "2026-12-31", **fields}}


@pytest.fixture
def ledger(tmp_path):
    ledger = Ledger(tmp_path)
    ledger.put("action", "pa:preferences", {"timezone": "Asia/Tokyo"}, action_type="preferences")
    return ledger


def _read(ledger, **data):
    return next_actions(ledger, {"radar": True, "at": AT, "limit": 20, **data},
                        kanban_reader=lambda *_: UNKNOWN)


@pytest.mark.parametrize("expires,notice,lead,deadline,surface", [
    ("2026-12-31", 30, 10, "2026-12-01", "2026-11-21"),
    ("2026-12", 30, 10, "2026-11-01", "2026-10-22"),
    ("2026-12-31", 0, 30, "2026-12-31", "2026-12-01"),
    ("2028-12-31", 730, 0, "2027-01-01", "2027-01-01"),
])
def test_notice_math(expires, notice, lead, deadline, surface):
    item = radar_item(_action(expires_on=expires, notice_days=notice, lead_days=lead), TODAY)
    assert (item["decide_by"], item["surface_at"]) == (deadline, surface)
    assert item["days_until_decide_by"] == (dt.date.fromisoformat(deadline) - TODAY).days
    assert item["surfaced"] == (dt.date.fromisoformat(surface) <= TODAY)


@pytest.mark.parametrize("invalid", [None, True, False, -1, 731, 1.0, "30", [], {}])
def test_invalid_notice_surfaces_on_the_date_and_names_a_gap(invalid):
    # Review: never fall back silently, since the real notice deadline may already be past.
    item = radar_item(_action(notice_days=invalid), TODAY)
    assert item.pop("gap") == "notice_days must be an integer from 0 to 730; surface_at uses the renewal date"
    plain = radar_item(_action(), TODAY)
    # It surfaces now, so the owner fixes the terms before the real deadline can pass.
    assert (item.pop("surface_at"), item.pop("surfaced")) == (TODAY.isoformat(), True)
    assert item == {k: v for k, v in plain.items() if k not in ("surface_at", "surfaced")}


@pytest.mark.parametrize("today,date,deadline,surface,missed", [
    ("2026-10-31", "2026-12-31", "2026-12-01", "2026-11-01", False),
    ("2026-11-01", "2026-12-31", "2026-12-01", "2026-11-01", False),
    ("2026-12-01", "2026-12-31", "2026-12-01", "2026-11-01", False),
    ("2026-12-02", "2026-12-31", "2026-12-01", "2026-11-01", True),
    ("2026-12-31", "2026-12-31", "2026-12-01", "2026-11-01", True),
    ("2027-01-01", "2027-12-31", "2027-12-01", "2027-11-01", False),
])
def test_yearly_notice_keeps_cycle_until_occurrence_passes(today, date, deadline, surface, missed):
    today = dt.date.fromisoformat(today)
    item = radar_item(_action(expires_on="2020-12-31", recurs="yearly", notice_days=30), today)
    assert (item["date"], item["decide_by"], item["surface_at"]) == (date, deadline, surface)
    assert item["surfaced"] == (dt.date.fromisoformat(surface) <= today)
    if missed:
        assert item["notice"] == f"missed: the last day to give notice was {deadline}"
    else:
        assert "notice" not in item


@pytest.mark.parametrize("amount,per,annual", [
    ("9.99", "month", "119.88"), ("120.00", "year", "120"), ("0", "month", "0"),
    ("0.0001", "month", "0.0012"),
    ("12345678901234567890123456789.99", "month", "148148146814814814681481481479.88"),
])
def test_cost_uses_exact_decimal(amount, per, annual):
    cost = {"amount": amount, "currency": "USD", "per": per}
    item = radar_item(_action(cost=cost, auto_renews=False, counterparty="Synthetic vendor"), TODAY)
    assert item["cost"] == cost
    assert item["annual_cost"] == annual
    assert item["auto_renews"] is False and item["counterparty"] == "Synthetic vendor"


@pytest.mark.parametrize("cost", [None, [], "9.99", {},
    {"amount": 9.99, "currency": "USD", "per": "month"},
    {"amount": "NaN", "currency": "USD", "per": "month"},
    {"amount": "Infinity", "currency": "USD", "per": "month"},
    {"amount": "1e2", "currency": "USD", "per": "month"},
    {"amount": "-1", "currency": "USD", "per": "month"},
    {"amount": "10", "currency": "usd", "per": "month"},
    {"amount": "10", "currency": 123, "per": "month"},
    {"amount": "10", "currency": "USD", "per": []},
    {"amount": "10", "currency": "USD", "per": "week"},
])
def test_invalid_cost_is_a_gap(cost):
    item = radar_item(_action(cost=cost), TODAY)
    assert "cost" not in item and "annual_cost" not in item
    assert item["gap"] == COST_GAP
    missing_date = radar_item(_action(cost=cost, expires_on=None), TODAY)
    assert missing_date["gap"] == (
        "record has no expires_on or event_date; ask the owner for the date; " + COST_GAP)


@pytest.mark.parametrize("value", [None, 1, "true", [], {}])
def test_invalid_optional_metadata_is_ignored(value):
    item = radar_item(_action(auto_renews=value, counterparty=value), TODAY)
    assert "auto_renews" not in item
    if not isinstance(value, str):
        assert "counterparty" not in item
    else:
        assert item["counterparty"] == value


@pytest.mark.parametrize("kind", ["deadline", "important_date"])
def test_nonrenewals_ignore_contract_fields(kind):
    action = _action(radar_kind=kind)
    extra = {**action, "fields": {**action["fields"], "notice_days": 60, "auto_renews": True,
                                "cost": {}, "counterparty": "Synthetic vendor"}}
    assert radar_item(extra, TODAY) == radar_item(action, TODAY)


def test_contract_summary_is_cumulative_unpaged_and_read_only(ledger):
    for identity, days, cost in [
        ("today", 0, {"amount": "9.99", "currency": "USD", "per": "month"}),
        ("b30", 30, {"amount": "1.12", "currency": "USD", "per": "year"}),
        ("a30", 30, {"amount": "10", "currency": "EUR", "per": "month"}),
        ("cost-future", 91, {"amount": "2", "currency": "USD", "per": "year"}),
        ("d60", 60, None), ("d90", 90, {}), ("future", 91, None), ("past", -1, None),
        ("no-date", None, None), ("completed", 0, None), ("cancelled", 0, None),
        ("kanban", 0, None), ("confirmed-loop", 0, None),
    ]:
        fields = _action(expires_on=(TODAY + dt.timedelta(days=days)).isoformat() if days is not None else None)["fields"]
        if cost is not None:
            fields["cost"] = cost
        if identity == "today":
            fields.update(notice_days=10, auto_renews=True)
        if identity == "kanban":
            fields["kanban_task_id"] = "done-task"
        if identity == "confirmed-loop":
            fields.update(loop_kind="waiting_on_them", confirmation={"by": "Owner", "at": AT, "evidence": "reply"})
        ledger.put("action", identity, fields, action_type="commitment",
                   status=identity if identity in {"completed", "cancelled"} else "pending")
    ledger.put("action", "not-renewal", _action(radar_kind="deadline", cost={})["fields"], action_type="commitment")
    rows = ledger.list("action")
    result = next_actions(ledger, {"radar": True, "contracts": True, "at": AT, "limit": 1},
                          kanban_reader=lambda *_: {"status": "done"})
    summary = result["contracts"]
    assert summary["currencies"] == {"USD": {"annual_cost": "123", "active": 3},
                                      "EUR": {"annual_cost": "120", "active": 1}}
    # Renewals with no contract terms (d60, future, no-date: passports and the like) stay out; d90 has an empty cost.
    assert summary["missing_cost"] == 1
    for window, expected in [("30", ["today", "a30", "b30"]),
                             ("60", ["today", "a30", "b30"]),
                             ("90", ["today", "a30", "b30", "d90"])]:
        assert [item["action_id"] for item in summary["renewing"][window]] == expected
    assert summary["renewing"]["30"][0] == {
        "action_id": "today", "title": "Synthetic subscription", "date": TODAY.isoformat(),
        "decide_by": "2026-10-29", "auto_renews": True, "annual_cost": "119.88", "currency": "USD"}
    assert summary["renewing"]["90"][-1] == {
        "action_id": "d90", "title": "Synthetic subscription", "date": "2027-02-06",
        "decide_by": None, "auto_renews": None, "annual_cost": None, "currency": None}
    assert ledger.list("action") == rows and result["read_only"] is True
    assert len(result["candidates"]) == 1


@pytest.mark.parametrize("flag", [False, None, 1, "true", [], {}])
def test_contract_flag_requires_true_boolean(ledger, flag):
    assert _read(ledger, contracts=flag) == _read(ledger)


def test_contract_schema_and_dispatch(ledger):
    assert SCHEMA["parameters"]["properties"]["data"]["properties"]["contracts"]["type"] == "boolean"
    result = dispatch(ledger.root, {"operation": "next_action", "data": {"radar": True, "contracts": True, "at": AT}})
    assert result["contracts"] == {"currencies": {}, "renewing": {"30": [], "60": [], "90": []}, "missing_cost": 0}


def test_context_waits_for_decision_lead_and_copies_deadline(ledger):
    ledger.put("action", "subscription", _action(notice_days=30, lead_days=10)["fields"], action_type="commitment")
    early = next_actions(ledger, {"at": AT}, kanban_reader=lambda *_: UNKNOWN)
    assert early["candidates"] == [] and early["excluded_radar_upcoming"] == 1
    due = next_actions(ledger, {"at": "2026-11-21T00:00:00+09:00"}, kanban_reader=lambda *_: UNKNOWN)
    assert due["candidates"][0]["radar"] == {"radar_kind": "renewal", "date": "2026-12-31",
        "surface_at": "2026-11-21", "days_until": 40, "decide_by": "2026-12-01"}


def test_legacy_items_and_scans_are_byte_identical_to_origin_main(ledger, tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(["git", "show", "f3c52fd6002e207b52e40c22548e6eaf99ba99e8:personal_assistant/radar.py"], cwd=root)
    # tmp_path is under the caller's scratch basetemp; relative imports keep their package context.
    baseline_path = tmp_path / "radar_origin_main.py"
    baseline_path.write_bytes(source)
    spec = importlib.util.spec_from_file_location("personal_assistant._radar_origin_main", baseline_path)
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    actions = [_action(), _action(expires_on="2027-03", lead_days=183),
               _action(expires_on=None), _action(expires_on="not a date"),
               _action(radar_kind="important_date", event_date="1990-11-29", expires_on=None, recurs="yearly"),
               _action(expires_on="2020-02-29", recurs="yearly", lead_days=True),
               _action(radar_kind="deadline", expires_on="2026-11-12")]
    for i, action in enumerate(actions):
        action["action_id"] = f"legacy-{i}"
        assert json.dumps(radar_item(action, TODAY)) == json.dumps(baseline.radar_item(action, TODAY))
        ledger.put("action", action["action_id"], action["fields"], action_type="commitment")
    kwargs = {"kanban_reader": lambda *_: UNKNOWN, "moment": dt.datetime.fromisoformat(AT),
              "zone": dt.timezone(dt.timedelta(hours=9))}
    for data in ({}, {"include_upcoming": True}, {"limit": 2, "offset": 1}, {"contracts": False}):
        assert json.dumps(scan(ledger, data, **kwargs)) == json.dumps(baseline.scan(ledger, data, **kwargs))
    ledger.put("action", "new-contract", _action(notice_days=30, cost={})["fields"], action_type="commitment")
    ordinary = _read(ledger)
    with_summary = _read(ledger, contracts=True)
    with_summary.pop("contracts")
    assert json.dumps(ordinary) == json.dumps(with_summary)



def test_yearly_notice_of_a_year_or_more_is_a_gap():
    item = radar_item(_action(expires_on="2020-12-31", recurs="yearly", notice_days=365), TODAY)
    assert "decide_by" not in item and "notice" not in item
    assert item["gap"] == "notice_days must be an integer from 0 to 364; surface_at uses the renewal date"
    assert item["surfaced"] is True and item["surface_at"] == TODAY.isoformat()
    assert radar_item(_action(expires_on="2020-12-31", recurs="yearly", notice_days=364), TODAY)["decide_by"] == "2026-01-01"


@pytest.mark.parametrize("today,missed", [("2026-12-01", False), ("2026-12-02", True), ("2026-12-31", True),
                                          ("2027-01-01", False)])
def test_one_off_contract_also_names_a_missed_notice(today, missed):
    item = radar_item(_action(notice_days=30), dt.date.fromisoformat(today))
    assert ("notice" in item) is missed
    if missed:
        assert item["notice"] == "missed: the last day to give notice was 2026-12-01"


def test_ended_one_off_contract_leaves_the_totals(ledger):
    for identity, expires, recurs in (("ended", "2026-01-01", "none"), ("yearly", "2020-01-01", "yearly"),
                                      ("live", "2027-03-01", "none")):
        ledger.put("action", identity, _action(expires_on=expires, recurs=recurs,
                   cost={"amount": "5", "currency": "USD", "per": "year"})["fields"], action_type="commitment")
    summary = _read(ledger, contracts=True)["contracts"]
    assert summary["currencies"] == {"USD": {"annual_cost": "10", "active": 2}} and summary["missing_cost"] == 0


def test_contract_totals_keep_every_digit(ledger):
    for identity, amount in (("big", "99999999999999999999999999999999.5"), ("tiny", "0.0000000000000000000000000000000001")):
        ledger.put("action", identity, _action(cost={"amount": amount, "currency": "USD", "per": "year"})["fields"],
                   action_type="commitment")
    total = _read(ledger, contracts=True)["contracts"]["currencies"]["USD"]["annual_cost"]
    assert total == "99999999999999999999999999999999.5000000000000000000000000000000001"
