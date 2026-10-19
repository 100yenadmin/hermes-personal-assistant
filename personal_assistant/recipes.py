"""Finite, lazy Personal Assistant recipe catalog.

The native ``pa`` tool owns state, confirmation, and receipts; existing integrations execute provider calls.
this module only describes the supported user-visible paths.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_WORKFLOW = (
    {"id": "capture", "operation": "context", "purpose": "Retrieve only the relevant trip, action, source, or guide context.", "expected": "Bounded source-linked context."},
    {"id": "next_action", "operation": "next_action", "purpose": "Exclude completed Kanban commitments and surface the next supported step.", "expected": "One next action or compact question."},
    {"id": "prepare", "operation": "action_upsert", "purpose": "Record reversible preparation with stable identity.", "expected": "Prepared facts without transaction state."},
    {"id": "verify", "operation": "context", "purpose": "Read back local or native state; use the provider's read tool for provider state.", "expected": "Verified, blocked, or unknown state."},
    {"id": "followup", "operation": "action_upsert", "purpose": "Persist safe proof, gaps, and the next follow-up.", "expected": "Durable follow-up without replay."},
)

_GOVERNED_TRANSACTION_PROTOCOL = (
    {"operation": "action_prepare", "purpose": "Freeze the complete provider call and opt into exact_action enforcement."},
    {"operation": "action_confirm", "purpose": "Bind explicit confirmation to that exact material summary, revision, tool, target, and arguments."},
    {"operation": "action_result", "purpose": "Record confirmed, failed, or unknown from provider readback; never replay unknown."},
)

_NATIVE_EXECUTION_CLAIM = {
    "mode": "native_gateway",
    "trigger": "matching_provider_call",
    "purpose": "After the final recheck, the native gateway atomically claims the one matching provider call.",
}

def _recipe(spec: tuple[Any, ...]) -> dict[str, Any]:
    recipe_id, title, slug, description, capabilities, transaction_paths, outcome, operations, steps = spec
    skill = f"personal-assistant:{slug}"
    return {
        "id": recipe_id,
        "recipe_id": recipe_id.lower(),
        "title": title,
        "description": description,
        "skill": skill,
        "skill_qualified_name": skill,
        "lazy": True,
        "steps": list(steps),
        "workflow": deepcopy(_WORKFLOW),
        "transaction_protocol": deepcopy(_GOVERNED_TRANSACTION_PROTOCOL) if transaction_paths else [],
        "execution_claim": deepcopy(_NATIVE_EXECUTION_CLAIM) if transaction_paths else None,
        "transaction_paths": list(transaction_paths),
        "operations": list(operations),
        "required_capabilities": list(capabilities),
        "confirmation_required": bool(transaction_paths),
        "expected_outcome": outcome,
    }


_BASE = ("status", "capabilities", "context", "recipes", "next_action", "action_upsert")
_TX = ("action_prepare", "action_confirm", "action_cancel", "action_claim", "action_result")

_SPECS = (
    ("R1", "Trip capture, change, and export", "r1-trip",
     "Import itinerary facts, apply an explicit change, and produce a bounded export.",
     ("portable_files",), (),
     "Current trip and credential-free export receipt; removed facts clear and omitted facts remain.",
     _BASE + ("trip_import", "export"),
     ("Retrieve the selected trip or source.", "Import only source facts.", "Export to a fresh directory or explicitly refresh unchanged PA-owned exports.", "Read the files back.", "Record safe proof and unresolved gaps.")),
    ("R2", "Assisted travel transaction", "r2-travel-transaction",
     "Prepare booking, check-in, ground, or reservation work with safe submit recovery.",
     ("browser",), ("booking", "check-in", "ground request", "reservation submit"),
     "Prepared or verified travel action; unknown submit remains unknown and is never replayed.",
     _BASE + _TX,
     ("Retrieve trip and action context.", "Use an existing provider integration.", "Freeze the complete exact-action scope.", "Confirm, recheck, and submit once through the native gateway.", "Read provider state and record the result.")),
    ("R3", "Refund or return request", "r3-refund-return",
     "Research policy and prepare a provider refund or return request from a known purchase.",
     ("browser",), ("refund submission", "return submission", "exchange submission"),
     "Provider receipt or durable blocker with no duplicate request.",
     _BASE + _TX,
     ("Retrieve the purchase source.", "Research policy without transaction state.", "Freeze the exact request.", "Confirm and submit once.", "Preserve provider proof or unknown state.")),
    ("R4", "Calendar conflict and meeting preparation", "r4-calendar-meeting",
     "Find conflicts and prepare private appointments or meeting packets.",
     ("calendar",), (),
     "Conflict-free proposal or meeting packet with readback; attendee sends remain outside this candidate.",
     _BASE + ("calendar_bind", "calendar_sync"),
     ("Retrieve accepted calendar scope.", "Read conflicts.", "Prepare a private packet or PA-owned event.", "Use ETag-aware sync when requested.", "Read back and record safe proof.")),
    ("R5", "Daily brief and reminders", "r5-brief-reminders",
     "Assemble a daily brief and maintain accepted reminder suggestions.",
     ("calendar", "automation"), (),
     "Current brief or reminder receipt; automations are suggestions and no job starts at install.",
     _BASE + ("automations",),
     ("Retrieve due and calendar context.", "Prioritize one next action.", "Prepare the brief.", "Read sources back.", "Suggest automation only after acceptance.")),
    ("R6", "Selected inbox and pending replies", "r6-inbox-replies",
     "Review an accepted inbox scope, save a draft, or confirm one outbound reply.",
     ("email",), ("send reply",),
     "Saved draft or confirmed provider-visible reply in the accepted scope.",
     _BASE + _TX,
     ("Retrieve the selected thread.", "Summarize and draft with action_upsert.", "Keep drafts reversible.", "Use the transaction protocol only for send.", "Read provider state before recording the outcome.")),
    ("R7", "Renewals and receipts", "r7-renewals-receipts",
     "Reconcile household renewals and receipts, then prepare an optional provider decision.",
     ("email", "browser"), ("renewal submit", "cancellation submit", "provider message"),
     "Reconciled receipt or confirmed provider decision with terms and proof.",
     _BASE + _TX,
     ("Retrieve the receipt source.", "Reconcile terms with action_upsert.", "Prepare an optional provider action.", "Confirm and submit once when requested.", "Record proof and the next due date.")),
    ("R8", "Shopping and services", "r8-shopping-services",
     "Research and prepare shopping or service requests with exact confirmation for submission.",
     ("browser",), ("order submit", "appointment submit", "service request submit"),
     "Prepared research or cart, or a verified order or service receipt with exact scope.",
     _BASE + _TX,
     ("Retrieve constraints and preferences.", "Research with ordinary tools.", "Prepare cart or request with action_upsert.", "Use the transaction protocol only for submit.", "Read provider state and record proof.")),
)


_RECIPES = {spec[0]: _recipe(spec) for spec in _SPECS}
_ALIASES: dict[str, str] = {}
for key, recipe in _RECIPES.items():
    aliases = (key.lower(), recipe["recipe_id"], recipe["skill"].split(":", 1)[1], recipe["skill"])
    for alias in aliases:
        _ALIASES[alias] = key


def _canonical_key(recipe_id: str) -> str:
    if not isinstance(recipe_id, str) or not recipe_id.strip():
        raise KeyError("recipe_id must be a non-empty string")
    raw = recipe_id.strip()
    key = _ALIASES.get(raw) or _ALIASES.get(raw.lower())
    if key is None:
        raise KeyError(f"unknown Personal Assistant recipe: {recipe_id}")
    return key


def route(recipe_id: str) -> dict[str, Any]:
    """Return a copy of one recipe by id, slug, or lazy skill name."""

    return deepcopy(_RECIPES[_canonical_key(recipe_id)])


def catalog() -> dict[str, dict[str, Any]]:
    """Return the finite catalog keyed by stable R1 through R8 ids."""

    return deepcopy(_RECIPES)


def recipe_ids() -> tuple[str, ...]:
    """Return recipe ids in user-facing order."""

    return tuple(_RECIPES)


RECIPES = _RECIPES
