"""Small explicit YAML schema; diagnostics always identify a field."""
import datetime as dt
import re
from pathlib import Path
import yaml
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
    for group, keys in (("persona", ("name", "email", "phone", "home_city", "notes")),
                        ("trip", ("origin", "destination", "depart_date", "return_date", "travellers"))):
        require(isinstance(s.get(group), dict), group)
        for key in keys:
            require(key in s[group] and s[group][key] is not None, f"{group}.{key}")
    for key in ("name", "email", "phone", "home_city", "notes"):
        require(isinstance(s["persona"][key], str), "persona." + key)
    require(isinstance(s["persona"]["email"], str) and re.fullmatch(r"[^@\s]+@[^@\s]+\.invalid", s["persona"]["email"]), "persona.email")
    require(bool(re.fullmatch(r"\+1[- ]?202[- ]?555[- ]?01\d\d", str(s["persona"]["phone"]))), "persona.phone")
    for key in ("depart_date", "return_date"):
        try:
            dt.date.fromisoformat(str(s["trip"][key]))
        except (ValueError, TypeError):
            raise ValueError(f"trip.{key}: expected ISO date") from None
    require(str(s["trip"]["return_date"]) >= str(s["trip"]["depart_date"]), "trip.return_date")
    require(type(s["trip"]["travellers"]) is int and s["trip"]["travellers"] > 0, "trip.travellers")
    for key in ("max_user_turns", "budget_seconds"):
        require(type(s.get(key)) is int and s[key] > 0, key)
    require(isinstance(s.get("steps"), list) and s["steps"], "steps")
    for i, step in enumerate(s["steps"]):
        prefix = f"steps[{i}]"
        require(isinstance(step, dict), prefix)
        require(isinstance(step.get("goal"), str) and bool(step["goal"].strip()), prefix + ".goal")
        require(step.get("capability") in caps, prefix + ".capability")
        require(isinstance(step.get("answers"), dict), prefix + ".answers")
        ex = step.get("expect")
        require(isinstance(ex, dict), prefix + ".expect")
        for key in ("or_handoff", "ledger", "approval_packet", "packet_is_final"):
            require(type(ex.get(key, False)) is bool, prefix + ".expect." + key)
        if ex.get("packet_is_final"):
            require(isinstance(ex.get("packet_target"), str) and bool(ex["packet_target"]), prefix + ".expect.packet_target")
        require("final" in ex or ex.get("or_handoff") or "calls" in s, prefix + ".expect.final")
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
