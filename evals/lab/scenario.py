"""Small explicit YAML schema; diagnostics always identify a field."""
import datetime as dt
import re
from pathlib import Path
import yaml
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from personal_assistant.calls import OUTCOMES as CALL_OUTCOMES

CATALOG = Path(__file__).parent / "scenarios"


def validate(s):
    def require(ok, field):
        if not ok:
            raise ValueError(f"{field}: invalid or missing")
    require(isinstance(s, dict), "scenario")
    require(isinstance(s.get("id"), str) and re.fullmatch(r"s\d\d_[a-z0-9_]+", s["id"]), "id")
    require(s.get("language") in ("en", "ja", "ko"), "language")
    caps = s.get("capabilities")
    require(isinstance(caps, list) and caps and all(isinstance(c, str) for c in caps), "capabilities")
    if "modes" in s:
        require(isinstance(s["modes"], dict) and s["modes"] == {"chief_of_staff": True}, "modes")
    cos = s.get("modes", {}).get("chief_of_staff") is True
    require(s.get("area") in (None, "research"), "area")
    research = s.get("area") == "research"
    require(not research or (not cos and caps == ["research"]), "capabilities")
    if cos:
        require(isinstance(s.get("user_md"), str) and bool(s["user_md"].strip()), "user_md")
        try:
            ZoneInfo(s.get("timezone", ""))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError("timezone: expected IANA timezone") from None
    if "preferences" in s:  # Optional per-scenario overrides of the seeded CoS slots.
        require(cos and isinstance(s["preferences"], dict) and set(s["preferences"]) <= {
            "cos_daily_time", "cos_kickoff_day", "cos_kickoff_time", "cos_weekly_day", "cos_weekly_time"}, "preferences")
    groups = [("persona", ("name", "email", "phone", "home_city", "notes"))]
    if "trip" in s or not (cos or research):
        groups.append(("trip", ("origin", "destination", "depart_date", "return_date", "travellers")))
    for group, keys in groups:
        require(isinstance(s.get(group), dict), group)
        for key in keys:
            require(key in s[group] and s[group][key] is not None, f"{group}.{key}")
    for key in ("name", "email", "phone", "home_city", "notes"):
        require(isinstance(s["persona"][key], str), "persona." + key)
    require(isinstance(s["persona"]["email"], str) and re.fullmatch(r"[^@\s]+@[^@\s]+\.invalid", s["persona"]["email"]), "persona.email")
    require(bool(re.fullmatch(r"\+1[- ]?202[- ]?555[- ]?01\d\d", str(s["persona"]["phone"]))), "persona.phone")
    for key in (("depart_date", "return_date") if "trip" in s else ()):
        try:
            dt.date.fromisoformat(str(s["trip"][key]))
        except (ValueError, TypeError):
            raise ValueError(f"trip.{key}: expected ISO date") from None
    if "trip" in s:
        require(str(s["trip"]["return_date"]) >= str(s["trip"]["depart_date"]), "trip.return_date")
        require(type(s["trip"]["travellers"]) is int and s["trip"]["travellers"] > 0, "trip.travellers")
    for key in ("max_user_turns", "budget_seconds"):
        require(type(s.get(key)) is int and s[key] > 0, key)
    require(isinstance(s.get("steps"), list) and s["steps"], "steps")
    for i, step in enumerate(s["steps"]):
        prefix = f"steps[{i}]"
        require(isinstance(step, dict), prefix)
        require(step.get("type", "chat") in ("chat", "scheduled"), prefix + ".type")
        if step.get("type") == "scheduled":
            require(cos and step.get("job") in ("cos_daily", "cos_kickoff", "cos_weekly"), prefix + ".job")
        require(isinstance(step.get("goal"), str) and bool(step["goal"].strip()), prefix + ".goal")
        require(step.get("capability") in caps, prefix + ".capability")
        require((step.get("capability") == "research") == research, prefix + ".capability")
        require(isinstance(step.get("answers"), dict), prefix + ".answers")
        ex = step.get("expect")
        require(isinstance(ex, dict), prefix + ".expect")
        if "research" in ex:
            require(research and ex["research"] is True, prefix + ".expect.research")
        for key in ("or_handoff", "ledger", "approval_packet", "packet_is_final"):
            require(type(ex.get(key, False)) is bool, prefix + ".expect." + key)
        if ex.get("packet_is_final"):
            require(isinstance(ex.get("packet_target"), str) and bool(ex["packet_target"]), prefix + ".expect.packet_target")
        if cos:
            require(ex.get("cos") in ("daily", "silence", "scout", "kickoff", "weekly", "radar_reply"), prefix + ".expect.cos")
            require((step.get("type") == "scheduled") == (ex["cos"] in ("daily", "silence", "kickoff", "weekly")), prefix + ".type")
            if step.get("type") == "scheduled":
                require(step["job"] == {"kickoff": "cos_kickoff", "weekly": "cos_weekly"}.get(ex["cos"], "cos_daily"), prefix + ".job")
        require("final" in ex or ex.get("or_handoff") or "calls" in s or cos or ex.get("research"), prefix + ".expect.final")
        if "final" in ex:
            for key in ("url_any", "text_any"):
                values = ex["final"].get(key) if isinstance(ex["final"], dict) else None
                require(isinstance(values, list) and values and all(isinstance(v, str) and v for v in values), prefix + ".expect.final." + key)
    if "calls" in s:
        require(isinstance(s["calls"], dict), "calls")
        require(isinstance(s["calls"].get("persona"), str), "calls.persona")
        require(s["calls"].get("direction") in ("outbound", "inbound"), "calls.direction")
        allowed = s["calls"].get("allowed_outcomes", [])
        require(isinstance(allowed, list) and all(isinstance(o, str) for o in allowed) and set(allowed) <= set(CALL_OUTCOMES), "calls.allowed_outcomes")
    require(s.get("requires") in (None, "gateway"), "requires")
    require(isinstance(s.get("seed", []), list), "seed")
    if cos:
        require(len(s["steps"]) <= s["max_user_turns"], "max_user_turns")
        for i, item in enumerate(s.get("seed", [])):
            require(isinstance(item, dict) and item.get("operation") == "action_upsert"
                    and isinstance(item.get("data"), dict), f"seed[{i}]")
            data = item["data"]
            require(data.get("action_type") in ("note", "commitment") and isinstance(data.get("fields"), dict)
                    and isinstance(data.get("action_id"), str) and bool(data["action_id"]), f"seed[{i}].data")
    return s


def load_catalog(directory=CATALOG):
    result = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        try:
            s = validate(yaml.safe_load(path.read_text()))
            if s["id"] in result:
                raise ValueError("id: duplicate")
            result[s["id"]] = s
        except (ValueError, yaml.YAMLError) as exc:
            raise ValueError(f"{path.name}: {exc}") from None
    if not result:
        raise ValueError("scenarios: empty catalog")
    return result
