"""One small structured interface, bound to the installing Hermes profile."""
import inspect
import json
from pathlib import Path

from .state import Ledger, stable_id
from .trip_facts import SEG_SCHEMA, SOURCES
from .trip_watch import MOMENTS, SKIPS

OPERATIONS = ["status", "capabilities", "context", "recipes", "trip_import", "export", "action_upsert",
              "action_prepare", "action_confirm", "action_cancel", "action_claim", "action_result",
              "authorization_prepare", "authorization_confirm", "authorization_cancel", "authorization_status",
              "event_upsert", "projection_claim", "projection_result", "reconcile", "freshness",
              "calendar_bind", "calendar_sync", "disconnect", "automations", "next_action", "setup",
              "trip_watch_plan", "trip_offer", "browser_session"]
SCHEMA = {
    "name": "pa",
    "description": "Personal Assistant Plugin: recover focused context, manage eight recipes, and preserve provider evidence and replay-safe state-loop receipts. Use capabilities for setup or a missing integration; use recipes to locate a needed qualified skill. Load personal-assistant:personal-assistant for setup and operation contracts. Reuse known context without repeating setup. Never infer authentication, spending or messaging approval from configuration or credential access.",
    "parameters": {"type": "object", "properties": {
        "operation": {"type": "string", "enum": OPERATIONS},
        "data": {"type": "object", "properties": {
            "action": {"type": "string"},
            "bb_session_id": {"type": "string"},
            "region": {"type": "string"},
            "trip_id": {"type": "string"},
            "departure_at": {"type": "string"},
            "arrival_at": {"type": "string"},
            "arrival_timezone": {"type": "string"},
            "commitments": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "at": {"type": "string"}}, "required": ["title", "at"]}},
            "airport_lead_minutes": {"type": "integer", "minimum": 0},
            "airport_transfer_minutes": {"type": "integer", "minimum": 0, "maximum": 600},
            "weather_included_minutes": {"type": "integer", "minimum": 0, "description": "weather buffer already inside airport_lead_minutes; set from trip_offer next"},
            "check_in_lead_minutes": {"type": "integer", "minimum": 0},
            "hb2_quiet_hours": {"type": "string", "description": "HH:MM-HH:MM; default 22:00-08:00; empty disables the HB2 window."},
            "armed": {"type": "boolean", "description": "record_wake: HB2 armed state, including false for confirmation-pending wakes."},
            "hb2_timezone": {"type": "string", "description": "HB2 IANA timezone; defaults to the Hermes-resolved timezone when available."},
            "reserve": {"type": "boolean", "default": True},
            "moment": {"type": "string", "enum": list(MOMENTS)},
            "arm": {"type": "array", "items": {"type": "string", "enum": list(MOMENTS)}, "minItems": 1, "uniqueItems": True},
            "check_in_window_hours": {"type": "integer", "minimum": 1, "maximum": 72},
            "night_alerts": {"type": "boolean"}, "weather": {"type": "boolean"},
            "reason": {"type": "string", "enum": list(SKIPS)},
            "expires_at": {"type": "string"},
            "wakes": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "status": {"type": "string"}, "expires_at": {"type": "string"}}, "required": ["id", "status"]}},
            "segments": {"anyOf": [{"type": "array", "items": SEG_SCHEMA, "minItems": 1, "maxItems": 8}, SEG_SCHEMA,
                                   {"type": "string", "description": "JSON-encoded segments; record_facts parses it."}]},
            "source": {"type": "string", "enum": SOURCES},
            "wake_id": {"type": "string", "pattern": "^w_[A-Za-z0-9_-]+$"},
            "offer_type": {"type": "string", "pattern": "^[a-z][a-z_]{1,39}$"},
            "section": {"type": "string"},
            "answers": {"type": "object"},
            "skipped": {"type": "array", "items": {"type": "string"}},
            "asked": {"type": "array", "items": {"type": "string"}},
            "consent": {"type": "string", "enum": ["granted", "declined"]},
            "writes": {"type": "array"},
            "readbacks": {"type": "array"},
            "action_id": {"type": "string", "description": "Stable existing action identity; allocate before a provider attempt."},
            "action_type": {"type": "string", "description": "action_upsert: use note for ordinary research/preparation evidence; commitment only for an actionable task linked to native Kanban. Transaction records are lifecycle-owned."},
            "status": {"type": "string", "description": "action_upsert: use completed when ordinary preparation/readback is finished. Provider outcomes use action_result instead."},
            "fields": {"type": "object", "description": "Nontransaction facts for action_upsert."},
            "summary": {"type": "object", "description": "Required for action_prepare, action_confirm and action_claim. Include provider and final_action plus current material details. Pass the exact same summary object to confirm and claim."},
            "confirmation": {"type": "string", "description": "Required for action_confirm: the user's explicit confirmation of these exact details."},
            "enforcement_profile": {"type": "string", "enum": ["exact_action"], "description": "action_prepare: opt into automatic exact-action enforcement for this durable action."},
            "action_revision": {"type": "string", "description": "Stable revision of the complete proposed provider effect."},
            "semantic_target": {"type": "object", "description": "Exact-action target: paths is a list of tool-argument key paths and value is the corresponding ordered value list."},
            "tool_name": {"type": "string", "description": "authorization_prepare: exact Hermes registry tool name."},
            "tool_args": {"type": "object", "description": "authorization_prepare: complete provider arguments; hashed but not retained by PA."},
            "reliability_profile": {"type": "string", "enum": ["exact"]},
            "workflow_id": {"type": "string"},
            "workflow_revision": {"type": "string"},
            "risk_class": {"type": "string"},
            "authority": {"type": "object"},
            "source_revision": {"type": "string"},
            "fresh_until": {"type": "string"},
            "execution_budget": {"type": "integer", "enum": [1]},
            "required_pre_action_projections": {"type": "array", "items": {"type": "string"}},
            "preconditions": {"type": "object"},
            "expected_readback": {"type": "string"},
            "outcome": {"type": "string", "description": "Outcome values are scoped by operation below."},
            "proof": {"description": "Provider or canonical readback evidence required for a known terminal outcome."},
            "freshness_seconds": {"type": "integer", "minimum": 1, "maximum": 315360000, "description": "Optional caller-owned projection freshness duration; PA supplies no domain default."},
            "at": {"type": "string", "description": "Explicit timezone-aware evaluation or transition timestamp."},
            "kind": {"type": "string", "enum": ["trip", "action", "source", "guide"], "description": "Optional for context when exactly one of trip_id/action_id/source_id is given; trip_id plus query needs explicit kind."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            "offset": {"type": "integer", "minimum": 0}
        }, "description": "Operation arguments. browser_session: action status/create/live_view/release; live_view/release take bb_session_id; create accepts region. trip_watch_plan: plan (default), status, record_wake, record_cancel, record_skip, verify or record_facts with trip_id; plan arms check_in_window/arrival_logistics/watch; receipts take moment/wake_id, verify takes wakes, record_facts takes segments/source or flat carrier, number, origin, destination, origin_timezone, destination_timezone, scheduled_departure, scheduled_arrival, optional estimated_departure, estimated_arrival, terminal_departure, terminal_arrival, status. trip_import/record_facts may return next_step. trip_offer: action check or record with trip_id/offer_type and outcome for record; occurrence comes from an observer notice; record example: data={\"action\":\"record\",\"trip_id\":…,\"offer_type\":…,\"outcome\":\"accepted\",\"occurrence\":\"n_…\"} (occurrence at the top level of data, not in fields); check reserves by default (reserve false skips reservation); opted_out requires an explicit never request. setup actions: status (default), start, record, propose, applied, fresh_check, pause, decline; record accepts consent granted/declined for the look-around; after apply it preserves applied/checked status and flags pending_changes for the next /pa setup review, then propose and apply. propose with draft true saves deeper-answer summaries and keeps the interview in progress. applied takes readbacks with target plus skill/path as needed; PA reads back the files and computes hashes. capabilities takes no data and never proves authentication. context: kind plus trip_id/action_id/source_id/query and optional limit/offset; kind is optional with exactly one ID, except trip_id plus query; guide needs explicit kind. recipes: optional recipe_id R1-R8; trip_import: trip_id, ics_path, optional guide_path/timezone/title/source_url/complete; export: trip_id/output_dir and optional guarded overwrite for same-profile PA files; action_upsert: optional action_id/source_id/action_kind/occurrence, fields. Transaction prepare/confirm/claim require action_id and summary; confirm also requires confirmation. action_prepare with enforcement_profile exact_action automatically registers a server-bound pending scope; action_cancel cancels that governed action. Action result requires action_id, outcome and proof. authorization_prepare records a generic exact-action envelope and hashes complete tool_args without retaining them; authorization_confirm requires action_id and explicit confirmation; authorization_status reads one action. event_upsert requires source_type/source_id/source_revision/projections and optional payload/occurred_at; each projection may declare freshness_seconds. projection_claim requires event_id/projection_key/claimed_by and optional lease_seconds/at. projection_result requires event_id/projection_key/claim_token/outcome and optional proof/at. reconcile optionally accepts event_id. freshness requires explicit at and optionally accepts event_id."}},
        "required": ["operation"],
        "allOf": [{
            "if": {"properties": {"operation": {"const": "projection_result"}}},
            "then": {"properties": {"data": {"properties": {
                "outcome": {"type": "string", "enum": ["confirmed", "failed", "unknown", "not_applicable"]}
            }}}},
            "else": {"if": {"properties": {"operation": {"const": "trip_offer"}}},
            "then": {"properties": {"data": {"properties": {
                "occurrence": {"type": "string", "pattern": "^n_[0-9a-f]{8}$"},
                "outcome": {"type": "string", "enum": ["offered", "accepted", "declined", "completed", "useful", "not_useful", "opted_out"]}
            }}}}, "else": {"if": {"properties": {"operation": {"const": "action_result"}}},
            "then": {"properties": {"data": {"properties": {
                "outcome": {"type": "string", "enum": ["confirmed", "failed", "unknown"]}
            }}}}}}
        }]},
}


def _call_with_supported_data(function, *args, data):
    parameters = inspect.signature(function).parameters
    supported = {
        key: value for key, value in data.items()
        if key in parameters and parameters[key].kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    }
    return function(*args, **supported)


def _authorization_store(profile_root, ledger, runtime_scope):
    from .action_gateway import ActionAuthorizationStore

    scope = runtime_scope or {}
    store = scope.get("authorization_store")
    if store is not None:
        return store
    return ActionAuthorizationStore(ledger, Path(profile_root).expanduser().resolve().name)


def dispatch(profile_root, args, *, runtime_scope=None):
    op, data = args.get("operation", "status"), args.get("data") or {}
    data = dict(json.loads(data) if isinstance(data, str) else data)
    if op not in OPERATIONS:
        raise ValueError("unknown PA operation")
    if op == "recipes":
        from .recipes import route
        return route(data["recipe_id"]) if data.get("recipe_id") else [route(f"R{i}") for i in range(1, 9)]
    if op == "capabilities":
        from .capabilities import discover
        return discover(profile_root=profile_root)
    ledger = Ledger(profile_root)
    if op == "browser_session":
        from .browserbase import browser_session
        scope = runtime_scope or {}
        return browser_session(ledger, data, opener=scope.get("browserbase_opener"), get_secret=scope.get("get_secret"))
    if op == "trip_watch_plan":
        from .trip_watch import dispatch as watch_dispatch, snapshot_settings
        data.pop("session_id", None)
        data.pop("_arm_epoch", None)
        data.pop("_carry", None)
        if (runtime_scope or {}).get("session_id"):
            data["session_id"] = runtime_scope["session_id"]
        result = watch_dispatch(ledger, data)
        if "observe_settings" in (runtime_scope or {}) and result.get("status") != "needs_input":
            snapshot_settings(ledger, runtime_scope["observe_settings"])
        return result
    if op == "trip_offer":
        from .concierge import dispatch as offer_dispatch
        return offer_dispatch(ledger, data)
    if op == "setup":
        from . import setup
        action = data.pop("action", "status")
        if action not in {"status", "start", "record", "propose", "applied", "fresh_check", "pause", "decline"}:
            raise ValueError("unknown setup action")
        if action in {"applied", "fresh_check"}:
            data["session_id"] = (runtime_scope or {}).get("session_id")
        if action in {"start", "record"}:
            from .modes import config_getter, cos_enabled
            section = data.get("section") if action == "start" else None
            if ((section or setup.state(ledger)["requested_section"]) == "chief_of_staff"
                    and not cos_enabled(config_getter(ledger.root))):
                raise ValueError("Chief of Staff mode is off; use /pa mode chief-of-staff on, "
                                 "then hermes gateway restart and a new session")
        return _call_with_supported_data(setup.state if action == "status" else getattr(setup, action), ledger, data=data)
    if op in {"authorization_prepare", "authorization_confirm", "authorization_cancel", "authorization_status"}:
        store = _authorization_store(profile_root, ledger, runtime_scope)
        if op == "authorization_prepare":
            at = data.pop("at", None)
            scope = runtime_scope or {}
            return store.prepare(
                data,
                session_id=scope.get("session_id"),
                task_id=scope.get("task_id"),
                at=at,
            )
        if op == "authorization_confirm":
            return store.confirm(data["action_id"], data["confirmation"], at=data.get("at"))
        if op == "authorization_cancel":
            return store.cancel(data["action_id"], at=data.get("at"))
        return store.get(data["action_id"])
    if op in {"event_upsert", "projection_claim", "projection_result", "reconcile", "freshness"}:
        from .state_loop import StateLoop
        loop = StateLoop(ledger)
        return _call_with_supported_data(getattr(loop, op), data=data)
    if op == "automations":
        from .automation_workflow import dispatch as automation_dispatch
        return automation_dispatch(ledger, data, get_config=(runtime_scope or {}).get("get_config"))
    if op == "context":
        from .context import retrieve
        return retrieve(ledger, data)
    if op == "next_action":
        from .context import next_actions
        return next_actions(ledger, data)
    if op == "calendar_bind":
        from .calendar_workflow import bind
        return _call_with_supported_data(bind, ledger, data=data)
    if op == "calendar_sync":
        from .calendar_workflow import sync_trip
        return _call_with_supported_data(sync_trip, ledger, data=data)
    if op == "disconnect":
        from .automation_workflow import preferences
        preferences(ledger, {"paused": True})
        return ledger.put("action", "pa:calendar-binding", {}, status="disconnected", remove=["calendar_id", "expected_account"])
    if op == "status":
        from .context import status_snapshot
        from .modes import config_getter, mode_status
        snapshot = status_snapshot(ledger, data)
        return {"plugin": "personal-assistant", "display_name": "Personal Assistant Plugin",
                "modes": mode_status((runtime_scope or {}).get("get_config") or config_getter(profile_root)),
                "operations": OPERATIONS, **snapshot,
                "commitment_status": "Read linked Hermes Kanban tasks for current commitment status.",
                "automation": "Installation enables no recurring jobs.",
                "capabilities": "Google, browser, messaging and credential availability require profile-specific verification."}
    if op == "trip_import":
        from .trips import import_trip
        source = Path(data.pop("ics_path")).expanduser()
        guide_path = data.pop("guide_path", None)
        if guide_path:
            data["guide"] = Path(guide_path).expanduser().read_text()
        from .trip_watch import offer_hint
        result = _call_with_supported_data(import_trip, ledger, data={**data, "ics": source.read_bytes()})
        hint = offer_hint(ledger, data["trip_id"])
        return {**result, "next_step": hint} if hint else result
    if op == "export":
        from .trips import export_trip
        return _call_with_supported_data(export_trip, ledger, data=data)
    if op == "action_upsert":
        supplied_id = data.pop("action_id", None)
        source_id, kind, occurrence = data.pop("source_id", None), data.pop("action_kind", None), data.pop("occurrence", None)
        identity = supplied_id or ledger.action_id(source_id, kind, occurrence)
        fields = data.pop("fields", {})
        return _call_with_supported_data(ledger.put, "action", identity, fields, data=data)
    identity = data.pop("action_id")
    if op == "action_cancel":
        action = ledger.get("action", identity)
        if not action or action["fields"].get("enforcement_profile") != "exact_action":
            raise ValueError("only approval-governed actions support action_cancel")
        store = _authorization_store(profile_root, ledger, runtime_scope)
        store.cancel_governed(identity, at=data.get("at"))
        return ledger.get("action", identity)
    if op == "action_prepare":
        enforcement_profile = data.pop("enforcement_profile", None)
        if enforcement_profile is None:
            return ledger.prepare(identity, data["summary"])
        if enforcement_profile != "exact_action":
            raise ValueError("unsupported action enforcement profile")
        scope = runtime_scope or {}
        store = _authorization_store(profile_root, ledger, runtime_scope)
        envelope = {
            "protocol": "pa.action-authorization/v1",
            "action_id": identity,
            "action_revision": data["action_revision"],
            "workflow_id": data["workflow_id"],
            "workflow_revision": data["workflow_revision"],
            "tool_name": data["tool_name"],
            "tool_args": data["tool_args"],
            "semantic_target": data["semantic_target"],
            "reliability_profile": "exact",
            "risk_class": data.get("risk_class", "external_write"),
            "authority": data.get("authority", {
                "mode": "exact_confirmation",
                "subject": "server_bound_pa_action",
                "scope_digest": "pa-action:" + identity,
            }),
            "source_revision": data["action_revision"],
            "fresh_until": data["fresh_until"],
            "execution_budget": data["execution_budget"],
            "required_pre_action_projections": data["required_pre_action_projections"],
            "preconditions": data["preconditions"],
            "expected_readback": data["expected_readback"],
        }
        authorization = store.prepare_governed(
            envelope,
            session_id=scope.get("session_id"),
            task_id=scope.get("task_id"),
            at=data.get("at"),
        )
        target = authorization["envelope"]["semantic_target"]
        governed = {
            "enforcement_profile": "exact_action",
            "action_revision": data["action_revision"],
            "workflow_id": data["workflow_id"],
            "workflow_revision": data["workflow_revision"],
            "tool_name": data["tool_name"],
            "semantic_target_digest": target["value_digest"],
            "args_digest": authorization["args_digest"],
            "fresh_until": authorization["fresh_until"],
            "execution_budget": authorization["execution_budget"],
            "expected_readback": data["expected_readback"],
            "gateway_scope_ref": authorization["action_id"],
        }
        return ledger.prepare(identity, data["summary"], governed=governed)
    if op == "action_confirm":
        action = ledger.get("action", identity)
        if action and action["fields"].get("enforcement_profile") == "exact_action":
            store = _authorization_store(profile_root, ledger, runtime_scope)
            store.confirm_governed(
                identity,
                stable_id(data["summary"]),
                data["confirmation"],
                at=data.get("at"),
            )
            return ledger.get("action", identity)
        return ledger.confirm(identity, data["summary"], data["confirmation"])
    if op == "action_claim":
        return ledger.claim_submission(identity, data["summary"])
    return ledger.result(identity, data["outcome"], data.get("proof"))
