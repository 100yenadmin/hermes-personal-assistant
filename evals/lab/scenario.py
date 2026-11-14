"""Small explicit YAML schema; diagnostics always identify a field."""
import datetime as dt
import re
from pathlib import Path
import yaml
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from personal_assistant.calls import OUTCOMES as CALL_OUTCOMES

CATALOG = Path(__file__).parent / "scenarios"
READ_ONLY_AREAS = {"research", "calendar"}
LAB_AREAS = {"inbox", "calendar", "follow_through", "reporting", "personal_admin", "travel", "errands", "customer_comms", "documents", "finance"}
SESSION_KINDS = {"booking", "approvals", "family", "vendor_request", "disruption", "expense", "onboarding", "week"}


def fixture_path(name):
    base = Path(__file__).parent / "fixtures"
    if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("lab.files: invalid fixture")
    path = (base / name).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError("lab.files: missing fixture")
    return path


def validate(s):
    def require(ok, field):
        if not ok:
            raise ValueError(f"{field}: invalid or missing")
    require(isinstance(s, dict), "scenario")
    week = isinstance(s.get("lab"), dict) and s["lab"].get("kind") == "week"
    require(isinstance(s.get("id"), str) and re.fullmatch(r"[sw]\d\d_[a-z0-9_]+" if week else r"s\d\d_[a-z0-9_]+", s["id"]), "id")
    require(s.get("language") in ("en", "ja", "ko"), "language")
    caps = s.get("capabilities")
    require(isinstance(caps, list) and caps and all(isinstance(c, str) for c in caps), "capabilities")
    if "modes" in s:
        require(isinstance(s["modes"], dict) and s["modes"] == {"chief_of_staff": True}, "modes")
    cos = s.get("modes", {}).get("chief_of_staff") is True
    lab = isinstance(s.get("lab"), dict)
    if lab and "clock" in s["lab"]:
        require(week and s["lab"]["clock"] == "shifted", "lab.clock")
    if week:
        settings = s["lab"].get("week")
        require(isinstance(settings, dict), "lab.week")
        require(isinstance(settings.get("counterparty"), str) and bool(settings["counterparty"].strip()), "lab.week.counterparty")
        topics = settings.get("topic_any")
        require(isinstance(topics, list) and bool(topics)
                and all(isinstance(t, str) and bool(t.strip()) for t in topics), "lab.week.topic_any")
    require(s.get("area") in (None, *READ_ONLY_AREAS, *LAB_AREAS), "area")
    research = s.get("area") == "research"
    calendar = s.get("area") == "calendar" and not lab
    require(lab or s.get("area") not in READ_ONLY_AREAS or (not cos and caps == [s["area"]]), "capabilities")
    require(("calendar" in s) == calendar, "calendar")
    if calendar:
        from .calendar_checks import expand
        try:
            c = expand(s["calendar"])
            lo, hi = [dt.time.fromisoformat(t) for t in c["working_hours"].split("-")]
            require(lo < hi, "calendar.working_hours")
            require(bool(c["events"]) and bool(c["people"]), "calendar")
            for person in c["people"].values():
                ZoneInfo(person["timezone"])
            for event in c["events"]:
                require(isinstance(event["title"], str) and bool(event["title"]), "calendar.events.title")
                require(isinstance(event["attendees"], list) and all(isinstance(n, str) for n in event["attendees"]), "calendar.events.attendees")
                require(type(event["focus"]) is bool, "calendar.events.focus")
        except (KeyError, TypeError, ValueError, AttributeError, ZoneInfoNotFoundError) as exc:
            raise ValueError(f"calendar: {exc}") from None
    if cos or lab:
        require(isinstance(s.get("user_md"), str) and bool(s["user_md"].strip()), "user_md")
    if cos or lab or "timezone" in s or any(st.get("type") == "scheduled" for st in s.get("steps", []) if isinstance(st, dict)):
        try:
            ZoneInfo(s.get("timezone", ""))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError("timezone: expected IANA timezone") from None
    if "preferences" in s:  # Optional per-scenario overrides of the seeded CoS slots.
        require((cos or lab) and isinstance(s["preferences"], dict) and set(s["preferences"]) <= {"brief_time", "eod_time",
            "cos_daily_time", "cos_kickoff_day", "cos_kickoff_time", "cos_weekly_day", "cos_weekly_time", "quiet_hours"}, "preferences")
        quiet = s["preferences"].get("quiet_hours", {"start": "00:00", "end": "00:00"})
        require(isinstance(quiet, dict) and set(quiet) == {"start", "end"}
                and all(isinstance(v, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", v) for v in quiet.values()),
                "preferences.quiet_hours: {start, end} as HH:MM")
    groups = [("persona", ("name", "email", "phone", "home_city", "notes"))]
    if "trip" in s or not (cos or research or calendar or lab):
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
    require(isinstance(s.get("steps"), list) and s["steps"], "steps")
    role_turns = any(isinstance(st, dict) and st.get("type") == "role_turn" for st in s["steps"])
    if role_turns:
        require(lab and s["lab"].get("kind") == "role_followthrough", "lab.kind for role_turn")
    for key in ("max_user_turns", "budget_seconds"):
        require(type(s.get(key)) is int and s[key] >= (0 if key == "max_user_turns" and role_turns else 1), key)
    if role_turns or lab and s["lab"].get("kind") == "role_followthrough":
        role = s.get("lab", {}).get("role")
        require(isinstance(role, dict) and all(isinstance(role.get(k), str) and role[k].strip()
                for k in ("id", "title", "charter")), "lab.role")
    for i, step in enumerate(s["steps"]):
        prefix = f"steps[{i}]"
        require(isinstance(step, dict), prefix)
        if "new_session" in step:
            require(type(step["new_session"]) is bool and i > 0 and lab
                    and s["lab"].get("kind") in SESSION_KINDS, prefix + ".new_session")
        require(step.get("type", "chat") in ("chat", "scheduled", "role_turn"), prefix + ".type")
        if step.get("type") == "role_turn" or week:
            require(type(step.get("day")) is int and step["day"] >= 0, prefix + ".day")
            require(type(step.get("hour")) is int and 0 <= step["hour"] <= 23, prefix + ".hour")
        if step.get("type") == "scheduled":
            require(step.get("job") in (("cos_daily", "cos_kickoff", "cos_weekly") if cos else ("daily_brief", "due_source_check")), prefix + ".job")
        require(type(step.get("hour", 12)) is int and 0 <= step.get("hour", 12) <= 23, prefix + ".hour")
        require(type(step.get("max_tool_gap", 1)) is int and step.get("max_tool_gap", 1) > 0, prefix + ".max_tool_gap")
        if "scripted_yes" in step:
            from .sim_user import scripted_yes
            require(lab and bool(scripted_yes(step)), prefix + ".scripted_yes")
        if step.get("type") != "role_turn":
            require(isinstance(step.get("goal"), str) and bool(step["goal"].strip()), prefix + ".goal")
        require(step.get("capability") in caps, prefix + ".capability")
        require((step.get("capability") == "research") == research, prefix + ".capability")
        require(not calendar or step.get("capability") == "calendar", prefix + ".capability")
        require(isinstance(step.get("answers"), dict), prefix + ".answers")
        ex = step.get("expect")
        require(isinstance(ex, dict), prefix + ".expect")
        if lab:
            require(ex.get("lab") == s["lab"].get("kind"), prefix + ".expect.lab")
        if week:
            require(ex.get("week") in {"record_loop", "raise_due"}, prefix + ".expect.week")
        if "research" in ex:
            require(research and ex["research"] is True, prefix + ".expect.research")
        if "calendar" in ex or calendar:
            require(calendar and ex.get("calendar") is True, prefix + ".expect.calendar")
        for key in ("or_handoff", "ledger", "approval_packet", "packet_is_final"):
            require(type(ex.get(key, False)) is bool, prefix + ".expect." + key)
        if ex.get("packet_is_final"):
            require(isinstance(ex.get("packet_target"), str) and bool(ex["packet_target"]), prefix + ".expect.packet_target")
        if cos:
            require(ex.get("cos") in ("daily", "silence", "scout", "kickoff", "weekly", "radar_reply"), prefix + ".expect.cos")
            require((step.get("type") == "scheduled") == (ex["cos"] in ("daily", "silence", "kickoff", "weekly")), prefix + ".type")
            if step.get("type") == "scheduled":
                require(step["job"] == {"kickoff": "cos_kickoff", "weekly": "cos_weekly"}.get(ex["cos"], "cos_daily"), prefix + ".job")
        require("final" in ex or ex.get("or_handoff") or "calls" in s or cos or ex.get("research") or ex.get("calendar") or (lab and ex.get("lab") == s["lab"].get("kind")), prefix + ".expect.final")
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
    for i, item in enumerate(s.get("seed", [])):
        if isinstance(item, dict) and item.get("operation") == "trip_import":
            require(lab and s["lab"].get("kind") in {"booking", "approvals", "disruption", "expense"}, f"seed[{i}].operation")
    if cos or lab:
        # Week is fully scripted: max_user_turns bounds each step, not days in the run.
        require(week or sum(st.get("type") != "role_turn" for st in s["steps"]) <= s["max_user_turns"], "max_user_turns")
        for i, item in enumerate(s.get("seed", [])):
            if lab and isinstance(item, dict) and item.get("operation") == "profile":
                data = item.get("data")
                require(isinstance(data, dict) and data.get("action") == "remember"
                        and data.get("kind") in {"sop", "person", "preference"}, f"seed[{i}].data")
                continue
            if lab and s["lab"].get("kind") in {"invoice", "tax_pack", "invoice_prep", "month_end"} and isinstance(item, dict) and item.get("operation") == "invoice":
                data = item.get("data")
                require(isinstance(data, dict) and (data.get("action") == "record" and isinstance(data.get("reference"), str)
                         and data.get("direction") in ("receivable", "payable")
                         or s["lab"]["kind"] in {"tax_pack", "month_end"} and data.get("action") == "paid"
                         and all(isinstance(data.get(k), str) and data[k] for k in ("invoice_id", "paid_on", "evidence"))), f"seed[{i}].data")
                continue
            if lab and s["lab"].get("kind") in {"tax_pack", "month_end"} and isinstance(item, dict) and item.get("operation") == "expense":
                from personal_assistant.expenses import OP_SCHEMA
                from jsonschema import Draft7Validator
                data = item.get("data")
                require(isinstance(data, dict) and data.get("action") in {"record", "void"}
                        and not list(Draft7Validator(OP_SCHEMA).iter_errors(data)), f"seed[{i}].data")
                continue
            if lab and s["lab"].get("kind") in {"booking", "approvals", "disruption", "expense"} and isinstance(item, dict) and item.get("operation") == "trip_import":
                data = item.get("data", {})
                require(isinstance(data, dict) and bool(data.get("trip_id"))
                        and isinstance(data.get("ics_text"), str) and bool(data["ics_text"].strip()), f"seed[{i}].data")
                continue
            if lab and s["lab"].get("kind") == "disruption" and isinstance(item, dict) and item.get("operation") in {
                    "trip_watch_plan", "action_prepare", "action_confirm", "action_claim", "action_result"}:
                data = item.get("data")
                require(isinstance(data, dict) and bool(data), f"seed[{i}].data")
                require(data.get("action") == "record_facts" and data.get("source") == "simulated" and bool(data.get("segments"))
                        if item["operation"] == "trip_watch_plan" else bool(data.get("action_id")) and "enforcement_profile" not in data,
                        f"seed[{i}].data")
                continue
            require(isinstance(item, dict) and item.get("operation") == "action_upsert"
                    and isinstance(item.get("data"), dict), f"seed[{i}]")
            data = item["data"]
            require(data.get("action_type") in (("note", "commitment", "offer", "notification") if lab else ("note", "commitment")) and isinstance(data.get("fields"), dict)
                    and isinstance(data.get("action_id"), str) and bool(data["action_id"]), f"seed[{i}].data")
    if lab:
        require(s["lab"].get("kind") in {"chase", "radar", "contracts", "eod", "health", "inbox", "invite", "meetings", "booking", "approvals", "vendor_request", "disruption", "expense", "owner_documents", "documents", "invoice", "tax_pack", "invoice_prep", "month_end", "minutes", "content", "onboarding", "customer_report", "priorities", "family", "role_followthrough", "week"}, "lab.kind")
        if s["lab"]["kind"] == "invoice_prep":
            expected = s["lab"].get("expected")
            require(isinstance(expected, dict), "lab.expected")
            for key in ("counterparty", "reference", "currency", "subtotal", "tax", "total"):
                require(isinstance(expected.get(key), str), "lab.expected." + key)
            require(type(expected.get("terms_days")) is int, "lab.expected.terms_days")
        if s["lab"]["kind"] == "month_end":
            expected = s["lab"].get("expected")
            require(isinstance(expected, dict), "lab.expected")
            # runner.one expands non-step scenario tokens before seeding; saved runs may
            # instead retain tokens. The checker expands both with the seed's variables.
            for key in ("period_start", "period_end"):
                value = expected.get(key)
                valid = isinstance(value, str) and value == "@last_month_" + key.split("_")[1] + "@"
                if isinstance(value, str) and not valid:
                    try:
                        valid = dt.date.fromisoformat(value).isoformat() == value
                    except ValueError:
                        pass
                require(valid, "lab.expected." + key)
            require(isinstance(expected.get("net"), str)
                    and bool(re.fullmatch(r"-?[0-9]+\.[0-9]{2}", expected["net"])), "lab.expected.net")
            for key in ("questions", "overdue"):
                value = expected.get(key)
                require(isinstance(value, list) and bool(value)
                        and all(isinstance(v, str) and v.strip() for v in value), "lab.expected." + key)
            require(set(expected["questions"]) <= {"receipts_missing", "uncategorised", "possible_duplicate",
                    "unpaid_at_end", "several_currencies"}, "lab.expected.questions")
            require(isinstance(expected.get("renewal"), str) and bool(expected["renewal"].strip()), "lab.expected.renewal")
            require(any(item.get("data", {}).get("action_id") == expected["renewal"]
                        for item in s.get("seed", [])), "lab.expected.renewal")
            retainer = expected.get("retainer")
            require(isinstance(retainer, dict), "lab.expected.retainer")
            for key in ("counterparty", "reference", "total"):
                require(isinstance(retainer.get(key), str) and bool(retainer[key].strip()), "lab.expected.retainer." + key)
            require(bool(re.fullmatch(r"[0-9]+\.[0-9]{2}", retainer["total"])), "lab.expected.retainer.total")
            require(type(retainer.get("terms_days")) is int and 0 <= retainer["terms_days"] <= 120,
                    "lab.expected.retainer.terms_days")
            require(len(s["steps"]) == 1, "steps")
        if s["lab"]["kind"] == "owner_documents":
            drive = s["lab"].get("drive")
            require(isinstance(drive, dict) and drive.get("crm") == {"Acme Demo": {"stage": "Qualified", "owner": "Riley Demo"}}, "lab.drive.crm")
            require(s["lab"].get("agenda_points") == ["venue", "catering", "transport", "owners"], "lab.agenda_points")
            require(len(s["steps"]) == 2 and s["steps"][1].get("scripted_yes", {}).get("items") == ["share-agenda", "crm-acme-stage"], "steps.scripted_yes.items")
        if s["lab"]["kind"] == "onboarding":
            threads = s["lab"].get("threads", [])
            require(isinstance(threads, list) and len(threads) >= 2 and all(isinstance(t, dict) and t.get("thread_id") and t.get("bucket") for t in threads), "lab.threads")
            require(sum(bool(t.get("urgent")) for t in threads) >= 2 and all(isinstance(t.get("keywords"), list) and t["keywords"]
                    and all(isinstance(k, str) and k.strip() for k in t["keywords"]) for t in threads if t.get("urgent")), "lab.threads.keywords")
        files = s["lab"].get("files", {})
        require(isinstance(files, dict), "lab.files")
        for destination, source in files.items():
            parts = Path(destination).parts if isinstance(destination, str) else ()
            require(len(parts) > 1 and parts[0] == "imports" and ".." not in parts, "lab.files.destination")
            require(source != s["lab"].get("key") and not str(source).endswith(".key.json"), "lab.files.oracle")
            fixture_path(source)
        if "key" in s["lab"]:
            fixture_path(s["lab"]["key"])
        if s["lab"]["kind"] == "expense":
            from .lab_plugin import BOOKING_FIELDS
            from personal_assistant.expenses import validate as expense_valid
            offers = s["lab"].get("offers")
            require(isinstance(offers, list) and len(offers) == 1 and isinstance(offers[0], dict)
                    and all(k in offers[0] for k in BOOKING_FIELDS), "lab.offers")
            charged = offers[0].get("charged")
            require(isinstance(charged, dict) and set(charged) == {"amount", "currency", "text"}
                    and isinstance(charged["text"], str) and bool(charged["text"].strip()), "lab.offers.charged")
            try:
                expense_valid({"amount": charged["amount"], "currency": charged["currency"], "category": "food"})
            except ValueError as exc:
                raise ValueError(f"lab.offers.charged: {exc}") from None
            require(len(s["steps"]) == 3 and s["steps"][1].get("scripted_yes", {}).get("items") == [offers[0]["id"]],
                    "steps.scripted_yes.items")
        if s["lab"]["kind"] == "invoice":
            seeded = {item["data"]["reference"]: item["data"] for item in s.get("seed", []) if item.get("operation") == "invoice"}
            oracle, remittance = s["lab"].get("invoices"), s["lab"].get("remittance")
            require(isinstance(oracle, dict) and set(oracle) == set(seeded) and all(isinstance(v, dict) for v in oracle.values()), "lab.invoices")
            for ref, expected in oracle.items():
                if seeded[ref]["direction"] == "payable":
                    require(expected == {"payable": True}, f"lab.invoices.{ref}")
                else:
                    require(expected.get("chase") in ("none", "owner_time", "day2", "day5", "day10", "escalate")
                            and set(expected) <= {"chase", "courtesy"}, f"lab.invoices.{ref}")
            require(sum(v.get("chase") == "escalate" for v in oracle.values()) == 1, "lab.invoices.escalate")
            require(isinstance(remittance, dict) and remittance.get("reference") in seeded
                    and seeded[remittance["reference"]]["direction"] == "receivable"
                    and all(isinstance(remittance.get(k), str) and remittance[k] for k in ("paid_on", "evidence")), "lab.remittance")
            require(len(s["steps"]) == 2, "steps")
        if s["lab"]["kind"] == "minutes":
            lab = s["lab"]
            def iso(value):
                try:
                    return isinstance(value, str) and dt.date.fromisoformat(value).isoformat() == value
                except ValueError:
                    return False
            def keyword_lists(value):
                return isinstance(value, list) and bool(value) and all(
                    isinstance(k, list) and k and all(isinstance(w, str) and w.strip() for w in k) for k in value)
            require(len(lab["files"]) == 1 and len(s["steps"]) == 1, "lab.files")
            require(iso(lab.get("meeting_date")) and isinstance(lab.get("owner_name"), str) and lab["owner_name"].strip(), "lab.meeting_date")
            items = lab.get("expected_items")
            require(isinstance(items, list) and bool(items) and all(
                isinstance(i, dict) and set(i) == {"owner", "due_date", "keywords"} and isinstance(i["owner"], str) and i["owner"].strip()
                and iso(i["due_date"]) and i["due_date"] >= lab["meeting_date"] and keyword_lists([i["keywords"]]) for i in items),
                "lab.expected_items")
            require(keyword_lists(lab.get("open_questions")) and keyword_lists(lab.get("decisions")), "lab.open_questions")
        if s["lab"]["kind"] == "disruption":
            from .lab_plugin import BOOKING_FIELDS
            offers, options = s["lab"].get("offers", []), s["lab"].get("flight_options", [])
            require(isinstance(offers, list) and len(offers) == 2 and all(isinstance(o, dict) and all(k in o for k in BOOKING_FIELDS)
                    and o["party_size"] == 2 for o in offers), "lab.offers")
            require(isinstance(options, list) and len(options) == 3 and all(isinstance(o, dict) and all(k in o for k in
                    ("id", "carrier", "number", "origin", "destination", "start", "end", "timezone", "price_text", "fare_difference_text")) for o in options), "lab.flight_options")
            ids = [o["id"] for o in offers + options]
            require(all(isinstance(i, str) and i for i in ids) and len(set(ids)) == 5, "lab.options.id")
            require(s["steps"][-1].get("scripted_yes", {}).get("items") == ["flight-opt-jl125", "offer-kitsune-2100"], "steps.scripted_yes.items")
        if s["lab"]["kind"] == "vendor_request":
            from .lab_plugin import BOOKING_FIELDS
            vendor, offers = s["lab"].get("vendor", {}), s["lab"].get("offers", [])
            require(isinstance(vendor, dict) and all(isinstance(vendor.get(k), str) and vendor[k].strip()
                    for k in ("item", "to", "counterparty")), "lab.vendor")
            require(bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.invalid", vendor["to"])), "lab.vendor.to")
            require(isinstance(offers, list) and len(offers) == 2 and all(isinstance(o, dict) and all(k in o for k in BOOKING_FIELDS)
                    and o["party_size"] == 1 for o in offers), "lab.offers")
            ids = [o["id"] for o in offers] + [vendor["item"]]
            require(all(isinstance(i, str) and i for i in ids) and len(set(ids)) == 3, "lab.offers.id")
            require(s["steps"][-1].get("scripted_yes", {}).get("items") == [ids[0], ids[-1]], "steps.scripted_yes.items")
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
