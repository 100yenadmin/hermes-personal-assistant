"""Every lab scenario's seed must load through the real PA dispatch (#276); no model or network calls."""
import copy
import datetime as dt
import socket

import pytest

from evals.lab import cos
from evals.lab.scenario import load_catalog
from personal_assistant.entry import dispatch

MOMENT = dt.datetime(2026, 11, 9, 3, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.delenv("TRAVEL_LEDGER_DB", raising=False)
    monkeypatch.setenv("DAILY_OPS_CONFIG", str(tmp_path / "missing-config.json"))


@pytest.mark.parametrize("scenario_id", sorted(load_catalog()))
def test_scenario_seed_loads_through_pa_dispatch(tmp_path, scenario_id):
    s = copy.deepcopy(load_catalog()[scenario_id])
    home = tmp_path / "home"
    home.mkdir()
    def checked(hh, args):
        result = dispatch(hh, args)
        assert not (isinstance(result, dict) and "error" in result), (args.get("operation"), result)
        return result
    cos.seed(home, s, checked, MOMENT)
