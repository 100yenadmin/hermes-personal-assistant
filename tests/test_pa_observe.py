"""HB2 subprocess contract using synthetic ledger rows and loopback weather."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, parse_qs

import pytest

from personal_assistant.observe import ack
from personal_assistant.state import Ledger

ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / "scripts/pa_observe.py"
UTC = dt.timezone.utc


@pytest.fixture
def profile(tmp_path):
    root = tmp_path / "profile"
    root.mkdir()
    (root / "config.yaml").write_text("# synthetic profile\n")
    ledger = Ledger(root)
    now = dt.datetime.now(UTC)
    departure = now + dt.timedelta(hours=4)
    arrival = now + dt.timedelta(hours=7)
    ledger.put("trip", "synthetic", {})
    watch = {"schema": 1, "watch_id": "w1", "trip_id": "synthetic", "event_id": "event",
             "status": "active", "profile_root": str(root.resolve()),
             "checks": {"trip_change": False, "flight": True, "weather": False},
             "departure_at": departure.isoformat(), "arrival_at": arrival.isoformat(),
             "origin": {"iata": "AAA", "tz": "Asia/Tokyo", "label": "Synthetic Airport"},
             "destination": {"iata": "BBB", "tz": "UTC", "label": "Destination"},
             "airport_lead_minutes": 120, "hb2_quiet_hours": "", "hb2_timezone": "UTC",
             "night_alerts": False, "planned_facts_digest": "plan"}
    segment = {"segment_id": "s1", "carrier": "ZZ", "number": "123", "origin": "AAA", "destination": "BBB",
               "origin_timezone": "Asia/Tokyo", "destination_timezone": "UTC",
               "scheduled_departure": departure.isoformat(), "scheduled_arrival": arrival.isoformat(),
               "status": "scheduled", "source": "synthetic", "observed_at": now.isoformat()}
    ledger.put("action", "pa:observe-watch:w1", watch)
    ledger.put("action", "pa:trip-facts:synthetic", {"schema": 1, "segments": [segment], "digest": "plan", "revision": 1})
    ledger.put("action", "pa:observe-settings", {"weather_provider": "off"})
    return ledger


def get(ledger, name="pa:observe:w1"):
    return (ledger.get("action", name) or {}).get("fields", {})


def watch(ledger, **updates):
    ledger.put("action", "pa:observe-watch:w1", updates)


def settings(ledger, **updates):
    ledger.put("action", "pa:observe-settings", updates)


def segment(ledger, **updates):
    facts = get(ledger, "pa:trip-facts:synthetic")
    facts["segments"][0].update(updates)
    ledger.put("action", "pa:trip-facts:synthetic", facts)


def shift(value, minutes):
    return (dt.datetime.fromisoformat(value) + dt.timedelta(minutes=minutes)).isoformat()


def invoke(ledger, args=("trip", "w1"), code=None, cwd=None):
    argv = [sys.executable, "-I"] + (["-c", code] if code else [str(SHIM), *args])
    return subprocess.run(argv, cwd=cwd or ledger.root, env={k: os.environ[k] for k in ("PATH", "HOME", "LANG") if k in os.environ},
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)


def run(ledger, **kwargs):
    completed = invoke(ledger, **kwargs)
    assert completed.returncode == 0, (completed.returncode, completed.stdout)
    output = json.loads(completed.stdout)
    assert set(output) == {"fire", "message", "state"}
    assert isinstance(output["fire"], bool) and isinstance(output["message"], str) and isinstance(output["state"], dict)
    assert len(json.dumps(output["state"]).encode()) < 200
    assert completed.stdout == json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()
    return output


def age_notices(ledger):
    state = get(ledger)
    for notice in state["notices"]:
        notice["last_at"] = (dt.datetime.now(UTC) - dt.timedelta(hours=1)).isoformat()
    ledger.put("action", "pa:observe:w1", state)


def quiet_now(ledger):
    now = dt.datetime.now(UTC)
    watch(ledger, hb2_quiet_hours=f'{(now - dt.timedelta(hours=1)):%H:%M}-{(now + dt.timedelta(hours=1)):%H:%M}')


@contextmanager
def weather_server(ledger, **values):
    data = {"code": 0, "rain": 0, "probability": 0, "gust": 0, "snow": 0,
            "delay": 0, "status": 200, "body": None, "requests": []}
    data.update(values)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data["requests"].append(self.path)
            time.sleep(data["delay"])
            self.send_response(data["status"])
            self.end_headers()
            if self.path.startswith("/open-meteo/v1/search?"):
                body = {"results": [{"latitude": 1, "longitude": 2, "name": "Synthetic"}]}
            else:
                dep = dt.datetime.fromisoformat(get(ledger, "pa:observe-watch:w1")["departure_at"]).timestamp()
                body = {"hourly": {"time": [dep - 3600], "weather_code": [data["code"]],
                                  "precipitation": [data["rain"]], "precipitation_probability": [data["probability"]],
                                  "wind_gusts_10m": [data["gust"]], "snowfall": [data["snow"]]}}
            raw = data["body"] if data["body"] is not None else json.dumps(body).encode()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    watch(ledger, checks={"weather": True})
    settings(ledger, weather_provider="local", local_base_url=f"http://127.0.0.1:{server.server_port}")
    try:
        yield data
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_output_and_silent_repeat(profile):
    assert not run(profile)["fire"]
    assert not run(profile)["fire"]
    assert get(profile)["usage"][dt.datetime.now(UTC).date().isoformat()]["runs"] == 2


@pytest.mark.parametrize("args,exit_code", [((), 2), (("other", "w1"), 2), (("trip", "unknown"), 4), (("trip", ""), 2)])
def test_exit_codes_no_output(profile, args, exit_code):
    completed = invoke(profile, args=args)
    assert (completed.returncode, completed.stdout) == (exit_code, b"")


def test_nonprofile_never_creates_ledger(profile, tmp_path):
    completed = invoke(profile, cwd=tmp_path)
    assert (completed.returncode, completed.stdout) == (3, b"")
    (tmp_path / "config.yaml").write_text("")
    completed = invoke(profile, cwd=tmp_path)
    assert (completed.returncode, completed.stdout) == (3, b"")
    assert not (tmp_path / "state").exists()


def test_profile_row_must_match_cwd(profile):
    watch(profile, profile_root="/another/profile")
    completed = invoke(profile)
    assert (completed.returncode, completed.stdout) == (3, b"")


def test_internal_exception_is_silent(profile):
    watch(profile, departure_at="invalid")
    completed = invoke(profile)
    assert (completed.returncode, completed.stdout) == (5, b"")


@pytest.mark.parametrize("status", ["cancelled", "ended"])
def test_inactive_watch(profile, status):
    watch(profile, status=status, departure_at="invalid")
    assert not run(profile)["fire"]


def test_warnings_and_stray_prints_are_suppressed(profile):
    code = f'''import sys, runpy, warnings, os
sys.path.insert(0, {str(ROOT)!r})
import personal_assistant.observe as observer
original = observer.probe
def noisy(*args):
    warnings.simplefilter("always")
    warnings.warn("synthetic warning")
    print("stray stdout")
    os.write(2, b"stray stderr")
    return original(*args)
observer.probe = noisy
sys.argv = [{str(SHIM)!r}, "trip", "w1"]
runpy.run_path({str(SHIM)!r}, run_name="__main__")'''
    assert not run(profile, code=code)["fire"]


def test_trip_change_and_silent_rebaseline(profile):
    watch(profile, checks={"trip_change": True})
    assert not run(profile)["fire"]
    assert get(profile)["facts_revision"] == 1
    planned = get(profile, "pa:trip-facts:synthetic")["segments"][0]["scheduled_departure"]
    segment(profile, scheduled_departure=shift(planned, 60))
    profile.put("action", "pa:trip-facts:synthetic", {"revision": 2, "digest": "new"})
    output = run(profile)
    assert output["fire"] and "offer_type=trip_change" in output["message"]
    assert not run(profile)["fire"]
    segment(profile, scheduled_departure=planned)
    profile.put("action", "pa:trip-facts:synthetic", {"revision": 3, "digest": "plan"})
    back = run(profile)  # The traveller was told about the change, so the return is news.
    assert back["fire"] and "back to the planned itinerary" in back["message"]
    assert not run(profile)["fire"]
    assert get(profile)["facts_revision"] == 3


def test_unannounced_change_that_returns_to_plan_stays_silent(profile):
    watch(profile, checks={"trip_change": True}, hb2_quiet_hours="00:00-23:59", hb2_timezone="UTC")
    assert not run(profile)["fire"]
    planned = get(profile, "pa:trip-facts:synthetic")["segments"][0]["scheduled_departure"]
    segment(profile, scheduled_departure=shift(planned, 60))
    profile.put("action", "pa:trip-facts:synthetic", {"revision": 2, "digest": "new"})
    assert not run(profile)["fire"]  # Quiet hours: not announced.
    segment(profile, scheduled_departure=planned)
    profile.put("action", "pa:trip-facts:synthetic", {"revision": 3, "digest": "plan"})
    watch(profile, hb2_quiet_hours="")
    assert not run(profile)["fire"]
    assert get(profile)["facts_revision"] == 3


def test_estimate_only_revision_is_a_flight_change_not_a_trip_change(profile):
    watch(profile, checks={"trip_change": True, "flight": True, "weather": False})
    assert not run(profile)["fire"]
    departure = get(profile, "pa:observe-watch:w1")["departure_at"]
    segment(profile, status="delayed", estimated_departure=shift(departure, 90), terminal_departure="2")
    profile.put("action", "pa:trip-facts:synthetic", {"revision": 2, "digest": "delayed"})
    output = run(profile)
    assert output["fire"] and "offer_type=flight_change" in output["message"]
    assert "Trip facts changed" not in output["message"]
    assert get(profile)["facts_revision"] == 2
    assert not run(profile)["fire"]


@pytest.mark.parametrize("change", [{"number": "124"}, {"status": "cancelled"}])
def test_itinerary_change_with_flight_check_is_a_trip_change(profile, change):
    watch(profile, checks={"trip_change": True, "flight": True, "weather": False})
    assert not run(profile)["fire"]
    segment(profile, **change)
    profile.put("action", "pa:trip-facts:synthetic", {"revision": 2, "digest": "changed"})
    output = run(profile)
    assert output["fire"] and "offer_type=trip_change" in output["message"] and "Trip facts changed" in output["message"]


@pytest.mark.parametrize("minutes,fire", [(19, False), (20, True), (-20, True)])
def test_departure_threshold(profile, minutes, fire):
    value = get(profile, "pa:observe-watch:w1")["departure_at"]
    segment(profile, estimated_departure=shift(value, minutes))
    output = run(profile)
    assert output["fire"] is fire
    if fire:
        assert "Leave by" in output["message"] and "+09:00" in output["message"]
        assert "offer_type=flight_change" in output["message"]
        assert not run(profile)["fire"]


@pytest.mark.parametrize("minutes,departed,fire", [(29, True, False), (30, True, True), (-30, True, True), (40, False, False)])
def test_arrival_threshold_only_after_departure(profile, minutes, departed, fire):
    value = get(profile, "pa:observe-watch:w1")["arrival_at"]
    updates = {"estimated_arrival": shift(value, minutes)}
    if departed:
        past = (dt.datetime.now(UTC) - dt.timedelta(hours=1)).isoformat()
        watch(profile, departure_at=past)
        updates["scheduled_departure"] = past
    segment(profile, **updates)
    assert run(profile)["fire"] is fire


def test_drift_accumulates_against_notified(profile):
    value = get(profile, "pa:observe-watch:w1")["departure_at"]
    for minutes, fire in [(0, False), (10, False), (19, False), (21, True), (30, False), (41, True)]:
        segment(profile, estimated_departure=shift(value, minutes))
        assert run(profile)["fire"] is fire


@pytest.mark.parametrize("status", ["cancelled", "diverted"])
def test_cancel_and_divert(profile, status):
    segment(profile, status=status)
    output = run(profile)
    assert output["fire"] and status in output["message"]
    ack(profile, "w1", output["state"]["notice"])
    age_notices(profile)
    assert not run(profile)["fire"]


@pytest.mark.parametrize("key", ["terminal_departure", "terminal_arrival"])
def test_terminal_change_requires_previous_value(profile, key):
    assert not run(profile)["fire"]
    segment(profile, **{key: "A"})
    assert not run(profile)["fire"]
    segment(profile, **{key: "B"})
    assert run(profile)["fire"]
    assert not run(profile)["fire"]


@pytest.mark.parametrize("departure_hours,arrival_hours", [(25, 28), (-10, -4)])
def test_flight_outside_window(profile, departure_hours, arrival_hours):
    now = dt.datetime.now(UTC)
    watch(profile, departure_at=(now + dt.timedelta(hours=departure_hours)).isoformat(), arrival_at=(now + dt.timedelta(hours=arrival_hours)).isoformat())
    segment(profile, status="cancelled")
    assert not run(profile)["fire"]
    assert "flight" not in get(profile)


@pytest.mark.parametrize("values,severity", [
    ({"code": 95}, "thunderstorm"), ({"code": 96}, "thunderstorm"), ({"code": 99}, "thunderstorm"),
    ({"code": 71}, "snow"), ({"code": 77}, "snow"), ({"code": 85}, "snow"), ({"code": 86}, "snow"), ({"snow": .5}, "snow"),
    ({"code": 56}, "freezing"), ({"code": 57}, "freezing"), ({"code": 66}, "freezing"), ({"code": 67}, "freezing"),
    ({"code": 65}, "heavy rain"), ({"code": 82}, "heavy rain"), ({"rain": 7.6, "probability": 50}, "heavy rain"),
    ({"gust": 60}, "gusts"), ({"code": 95, "snow": 1, "gust": 90}, "thunderstorm")])
def test_weather_severities(profile, values, severity):
    with weather_server(profile, **values) as data:
        output = run(profile)
        assert output["fire"] and severity in output["message"]
        assert "offer_type=weather_leave_early" in output["message"]
        assert not run(profile)["fire"]
        assert sum("/search?" in r for r in data["requests"]) == 1
        query = parse_qs(urlsplit(data["requests"][1]).query)
        assert query["timezone"] == ["UTC"] and query["timeformat"] == ["unixtime"]
        assert get(profile)["weather"]["coords"]["lat"] == 1


def test_weather_escalation_and_two_clears(profile):
    with weather_server(profile, gust=60) as data:
        assert run(profile)["fire"]
        data.update(code=65)
        assert run(profile)["fire"]
        data.update(code=0)
        assert not run(profile)["fire"]  # gusts is below the notified heavy rain
        data.update(gust=0)
        assert not run(profile)["fire"]
        output = run(profile)
        assert output["fire"] and "cleared" in output["message"]
        assert not run(profile)["fire"]


def test_provider_error_breaks_consecutive_clear_checks(profile):
    with weather_server(profile, code=95) as data:
        assert run(profile)["fire"]
        data.update(code=0)
        assert not run(profile)["fire"]
        data.update(status=503)
        assert not run(profile)["fire"]
        assert get(profile)["weather"]["clear_streak"] == 0
        data.update(status=200)
        assert not run(profile)["fire"]
        output = run(profile)
        assert output["fire"] and "cleared" in output["message"]


@pytest.mark.parametrize("values", [{"rain": 7.6, "probability": 49}, {"gust": 59}, {"snow": .49}])
def test_weather_below_thresholds(profile, values):
    with weather_server(profile, **values):
        assert not run(profile)["fire"]


@pytest.mark.parametrize("url", ["http://example.com", "http://127.0.0.1.example.com", "http://10.0.0.1", "file:///tmp/data", "http://user@127.0.0.1"])
def test_refuse_nonloopback_provider(profile, url):
    watch(profile, checks={"weather": True})
    settings(profile, weather_provider="local", local_base_url=url)
    assert not run(profile)["fire"]
    assert get(profile)["weather"]["error"]["kind"] == "refused"


@pytest.mark.parametrize("hours", [49, -1])
def test_weather_outside_window(profile, hours):
    with weather_server(profile, code=95) as data:
        watch(profile, departure_at=(dt.datetime.now(UTC) + dt.timedelta(hours=hours)).isoformat())
        assert not run(profile)["fire"]
        assert data["requests"] == []


def test_weather_samples_only_leave_window(profile):
    with weather_server(profile, code=95) as data:
        dep = dt.datetime.fromisoformat(get(profile, "pa:observe-watch:w1")["departure_at"]).timestamp()
        data["body"] = json.dumps({"hourly": {"time": [dep - 4 * 3600, dep - 3600], "weather_code": [95, 0],
                "precipitation": [0, 0], "precipitation_probability": [0, 0], "wind_gusts_10m": [0, 0], "snowfall": [0, 0]}}).encode()
        # Cache coordinates so this body is used only for forecast.
        profile.put("action", "pa:observe:w1", {"schema": 1, "trip_id": "synthetic", "notices": [], "weather": {"coords": {"lat": 1, "lon": 2}}})
        assert not run(profile)["fire"]


@pytest.mark.parametrize("minutes", [20, 59, 60])
def test_quiet_delay_critical_or_deferred(profile, minutes):
    quiet_now(profile)
    value = get(profile, "pa:observe-watch:w1")["departure_at"]
    segment(profile, estimated_departure=shift(value, minutes))
    output = run(profile)
    assert output["fire"] is (minutes >= 60)
    watch(profile, hb2_quiet_hours="")
    assert run(profile)["fire"] is (minutes < 60)
    assert not run(profile)["fire"]


@pytest.mark.parametrize("status", ["cancelled", "diverted"])
def test_quiet_status_is_critical(profile, status):
    quiet_now(profile)
    segment(profile, status=status, terminal_departure="A")
    output = run(profile)
    assert output["fire"]
    age_notices(profile)
    assert not run(profile)["fire"]  # even critical notices are not re-emitted during quiet hours


def test_quiet_defers_weather_and_trip_even_with_critical_flight(profile):
    with weather_server(profile, code=95):
        watch(profile, checks={"trip_change": True, "flight": True, "weather": True})
        quiet_now(profile)
        profile.put("action", "pa:trip-facts:synthetic", {"digest": "new", "revision": 2})
        segment(profile, status="cancelled")
        first = run(profile)
        assert first["fire"] and "Weather" not in first["message"] and "Trip facts" not in first["message"]
        watch(profile, hb2_quiet_hours="")
        second = run(profile)
        assert second["fire"] and "Trip facts" in second["message"] and "Weather" in second["message"]
        assert not run(profile)["fire"]


def test_quiet_timezone_uses_watch_zone(profile):
    local = dt.datetime.now(UTC) + dt.timedelta(hours=9)
    watch(profile, hb2_timezone="Asia/Tokyo", hb2_quiet_hours=f'{(local - dt.timedelta(hours=1)):%H:%M}-{(local + dt.timedelta(hours=1)):%H:%M}')
    segment(profile, status="scheduled", estimated_departure=shift(get(profile, "pa:observe-watch:w1")["departure_at"], 20))
    assert not run(profile)["fire"]


def test_concurrent_runs_emit_once(profile):
    segment(profile, status="cancelled")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda _: run(profile), range(2)))
    assert sum(o["fire"] for o in outputs) == 1
    assert len(get(profile)["notices"]) == 1


def test_reemit_at_most_twice(profile):
    segment(profile, status="cancelled")
    first = run(profile)
    assert not run(profile)["fire"]
    for _ in range(2):
        age_notices(profile)
        output = run(profile)
        assert output["fire"] and output["state"]["notice"] == first["state"]["notice"]
    age_notices(profile)
    assert not run(profile)["fire"]
    assert get(profile)["notices"][0]["emits"] == 3


def test_ack_stops_reemission_and_does_not_lose_other_acks(profile):
    segment(profile, status="cancelled")
    output = run(profile)
    ack(profile, "w1", output["state"]["notice"])
    ack(profile, "w1", "n_other")
    age_notices(profile)
    assert not run(profile)["fire"]
    assert len(get(profile, "pa:observe-control:w1")["acks"]) == 2


@pytest.mark.parametrize("values", [{"status": 503}, {"status": 302}, {"body": b"invalid json"}, {"body": b"x" * (256 * 1024 + 1)}])
def test_transient_provider_errors(profile, values):
    with weather_server(profile, **values):
        assert not run(profile)["fire"]
        assert get(profile)["weather"]["error"]["streak"] == 1


def test_attention_once_after_eight_errors(profile):
    with weather_server(profile, status=503) as data:
        for _ in range(7):
            assert not run(profile)["fire"]
        output = run(profile)
        assert output["fire"] and "offer_type=watch_attention" in output["message"]
        ack(profile, "w1", output["state"]["notice"])
        assert not run(profile)["fire"]
        data.update(status=200)
        assert not run(profile)["fire"]
        assert "error" not in get(profile)["weather"]


def test_watchdog_hanging_provider(profile):
    with weather_server(profile, delay=5):
        settings(profile, budget_s=3)
        start = time.monotonic()
        output = run(profile)
        assert time.monotonic() - start < 4
        assert output == {"fire": False, "message": "", "state": {"watch": "w1", "timeout": True}}


def test_message_bound_and_untrusted_characters(profile):
    trip = '<>&⟦"' + "旅" * 20
    watch(profile, trip_id=trip)
    facts = get(profile, "pa:trip-facts:synthetic")
    facts["segments"][0].update(status="cancelled", source="<>&⟦" + "天" * 1000)
    profile.put("action", "pa:trip-facts:" + trip, facts)
    output = run(profile)
    assert output["fire"]
    assert len(output["message"].encode()) <= 800
    assert not any(c in output["message"] for c in '<>&⟦')
    assert "before messaging." in output["message"]
    argument = output["message"].split("trip_id=", 1)[1].split(" offer_type=", 1)[0]
    assert json.loads(argument) == trip


def test_notice_and_usage_storage_caps(profile):
    assert not run(profile)["fire"]
    old = get(profile)
    old["usage"] = {(dt.datetime.now(UTC).date() - dt.timedelta(days=day)).isoformat(): {} for day in range(1, 21)}
    profile.put("action", "pa:observe:w1", old)
    for index in range(12):
        value = get(profile, "pa:observe-watch:w1")["departure_at"]
        segment(profile, estimated_departure=shift(value, (index + 1) * 20))
        assert run(profile)["fire"]
    assert len(get(profile)["notices"]) == 10
    assert len(get(profile)["usage"]) == 14


def test_multiple_segments_have_independent_baselines(profile):
    facts = get(profile, "pa:trip-facts:synthetic")
    facts["segments"].append({**facts["segments"][0], "segment_id": "s2", "number": "456", "status": "diverted"})
    profile.put("action", "pa:trip-facts:synthetic", facts)
    output = run(profile)
    assert output["fire"] and "ZZ456" in output["message"]
    assert get(profile)["flight"]["notified"]["status"] == {"s1": "scheduled", "s2": "diverted"}
    assert not run(profile)["fire"]


def test_successful_geocode_cached_even_if_forecast_fails(profile):
    with weather_server(profile) as data:
        # A forecast with no covered hours is a transient parse/coverage failure.
        dep = dt.datetime.fromisoformat(get(profile, "pa:observe-watch:w1")["departure_at"]).timestamp()
        watch(profile, airport_lead_minutes=-1000)
        assert not run(profile)["fire"]
        assert get(profile)["weather"]["coords"]["lat"] == 1
        assert not run(profile)["fire"]
        assert sum("/search?" in r for r in data["requests"]) == 1


def test_isolated_import_closure(profile):
    code = f'''import sys, json, sysconfig
sysconfig.get_paths()  # macOS generated _sysconfigdata is also stdlib
sys.path = [p for p in sys.path if "site-packages" not in p]
sys.path.insert(0, {str(ROOT)!r})
before = set(sys.modules)
import personal_assistant.observe
loaded = set(sys.modules) - before
bad = [n for n in loaded if n.split(".")[0] not in sys.stdlib_module_names and n.split(".")[0] not in {{"personal_assistant", "pa_legacy_ledger"}}]
print(json.dumps(bad))'''
    completed = invoke(profile, code=code)
    assert completed.returncode == 0 and json.loads(completed.stdout) == []


@pytest.mark.parametrize("code,allowed", [
    ("import json\nfrom personal_assistant.state import Ledger", True),
    ("from personal_assistant import observe_sources", True), ("from .privacy import clean", True),
    ("import requests", False), ("from personal_assistant.trip_watch import plan", False),
    ("from .trips import parse", False), ("import certifi", False),
    ("try:\n import certifi\nexcept ImportError:\n pass", True),
    ("try:\n pass\nexcept ImportError:\n import certifi", False)])
def test_pack_import_ast_check(tmp_path, code, allowed):
    spec = importlib.util.spec_from_file_location("pa_pack_validator", ROOT / "scripts/validate_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "observe.py"
    path.write_text(code)
    assert (not module.observer_import_errors(path)) is allowed


def test_weather_cache_regeocodes_when_origin_changes(monkeypatch):
    from personal_assistant import observe_sources as sources
    names = []
    def fake_fetch(url, params, timeout, deadline, usage, provider):
        if "name" in params:
            names.append(params["name"])
            return {"results": [{"latitude": len(names), "longitude": 2, "name": params["name"]}]}
        return {"hourly": {"time": [10], "weather_code": [0], "precipitation": [0], "precipitation_probability": [0],
                           "wind_gusts_10m": [0], "snowfall": [0]}}
    monkeypatch.setattr(sources, "fetch", fake_fetch)
    coords = {}
    sources.weather({}, {"iata": "HND", "label": "HND"}, coords, 0, 20, 1e12, {})
    sources.weather({}, {"iata": "HND", "label": "HND"}, coords, 0, 20, 1e12, {})
    sources.weather({}, {"iata": "NRT", "label": "NRT"}, coords, 0, 20, 1e12, {})
    assert names == ["HND", "NRT"] and coords["place"] == "NRT"


@pytest.mark.parametrize("age,extra", [(None, 0), (179, 45), (181, 0)])
def test_flight_leave_by_default_and_recent_weather(profile, age, extra):
    from personal_assistant import trip_math
    profile.put("action", "pa:observe-watch:w1", {}, remove=["airport_lead_minutes"])
    if age is not None:
        profile.put("action", "pa:observe:w1", {"weather": {"last": {"severity": "snow", "at":
            (dt.datetime.now(UTC) - dt.timedelta(minutes=age)).isoformat()}}})
    departure = get(profile, "pa:observe-watch:w1")["departure_at"]
    estimated = shift(departure, 25)
    segment(profile, estimated_departure=estimated)
    output = run(profile)
    expected = trip_math.leave_by(departure, 180, "Asia/Tokyo", estimated=estimated, severity="snow" if extra else None)
    signals = get(profile)["notices"][-1]["signals"]
    assert signals[-1] == f'Leave by {expected["local_time"]}' + (" (+45 min for snow)" if extra else "")
    assert len(output["message"].encode()) <= 800 and all(len(s.encode()) <= 400 for s in signals)


def test_weather_notice_leave_by_and_raw_last_on_no_notify(profile):
    from personal_assistant.trip_math import leave_by
    with weather_server(profile, code=95) as data:
        output = run(profile)
        current = get(profile, "pa:observe-watch:w1")
        expected = leave_by(current["departure_at"], 120, current["origin"]["tz"], severity="thunderstorm")
        signals = get(profile)["notices"][-1]["signals"]
        assert signals[-1] == f'Leave by {expected["local_time"]} (+30 min for thunderstorm)'
        assert len(output["message"].encode()) <= 800 and all(len(s.encode()) <= 400 for s in signals)
        assert not run(profile)["fire"]
        assert get(profile)["weather"]["last"]["severity"] == "thunderstorm"
        data.update(code=0)
        assert not run(profile)["fire"]
        assert get(profile)["weather"]["last"]["severity"] == "clear"
        assert get(profile)["weather"]["last"]["at"] == get(profile)["weather"]["checked_at"]


def test_weather_leave_by_missing_origin_is_silent_fallback(profile):
    with weather_server(profile, code=95):
        watch(profile, origin={"label": "Synthetic Airport"})
        assert run(profile)["fire"]
        assert not any(s.startswith("Leave by") for s in get(profile)["notices"][-1]["signals"])


@pytest.mark.parametrize("suppression", [None, "already_recorded", "declined", "opted_out"])
def test_offer_ack_commits_and_prevents_probe_reemission(profile, suppression):
    from personal_assistant.concierge import dispatch
    from personal_assistant.trip_watch import _watch_id
    watch_id = _watch_id("synthetic")
    profile.put("action", "pa:observe-watch:" + watch_id, get(profile, "pa:observe-watch:w1"))
    segment(profile, status="cancelled")
    output = run(profile, args=("trip", watch_id))
    occurrence = output["state"]["notice"]
    data = dict(trip_id="synthetic", offer_type="flight_change", occurrence=occurrence)
    if suppression == "declined":
        dispatch(profile, dict(trip_id="synthetic", offer_type="flight_change", action="record", outcome="declined"))
    elif suppression == "opted_out":
        dispatch(profile, dict(trip_id="synthetic", offer_type="flight_change", action="record", outcome="opted_out"))
    if suppression in {None, "already_recorded"}:
        assert dispatch(profile, data)["reason"] == "new_offer"
        assert dispatch(profile, data)["reason"] == "retry_reserved"  # A failed turn's retry is not acked.
        assert not get(profile, "pa:observe-control:" + watch_id)
    if suppression == "already_recorded":
        dispatch(profile, {**data, "action": "record", "outcome": "offered"})
    if suppression is None:
        dispatch(profile, {**data, "action": "record", "outcome": "offered"})
    else:
        assert dispatch(profile, {**data, "reserve": False})["reason"] == suppression
    assert occurrence in get(profile, "pa:observe-control:" + watch_id)["acks"]
    state = get(profile, "pa:observe:" + watch_id)
    state["notices"][0]["last_at"] = (dt.datetime.now(UTC) - dt.timedelta(hours=1)).isoformat()
    profile.put("action", "pa:observe:" + watch_id, state)
    assert not run(profile, args=("trip", watch_id))["fire"]


def test_flight_leave_by_does_not_readd_notified_snow(profile):
    watch(profile, airport_lead_minutes=225, weather_included_minutes=45)
    departure = get(profile, "pa:observe-watch:w1")["departure_at"]
    profile.put("action", "pa:observe:w1", {"weather": {
        "last": {"severity": "snow", "at": dt.datetime.now(UTC).isoformat()},
        "notified": {"severity": "snow"}}})
    estimated = shift(departure, 25)
    segment(profile, estimated_departure=estimated)
    assert run(profile)["fire"]
    expected = (dt.datetime.fromisoformat(estimated) - dt.timedelta(minutes=225)).astimezone(
        ZoneInfo("Asia/Tokyo"))
    expected = expected.replace(minute=expected.minute // 5 * 5)
    assert get(profile)["notices"][-1]["signals"][-1] == f"Leave by {expected:%H:%M}"


@pytest.mark.parametrize("included,old,extra", [(45, "clear", 0), (30, "heavy rain", 15)])
def test_weather_notice_adds_only_unincluded_minutes(profile, included, old, extra):
    watch(profile, airport_lead_minutes=180 + included, weather_included_minutes=included)
    profile.put("action", "pa:observe:w1", {"weather": {"notified": {"severity": old}}})
    with weather_server(profile, code=71):
        assert run(profile)["fire"]
    notice = get(profile)["notices"][-1]
    current = get(profile, "pa:observe-watch:w1")
    expected = (dt.datetime.fromisoformat(current["departure_at"]) - dt.timedelta(
        minutes=180 + included + extra)).astimezone(ZoneInfo("Asia/Tokyo"))
    expected = expected.replace(minute=expected.minute // 5 * 5)
    assert notice["signals"][-1] == f'Leave by {expected:%H:%M} (+{extra} min for snow)'
    assert notice["weather_extra_minutes"] == extra
