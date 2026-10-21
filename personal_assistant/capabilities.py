"""Read-only integration discovery using registrations, CLI and credential presence."""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Iterable


_SPECS = (
    ("portable_files", (), "PA's local ICS and Markdown import/export path"),
    ("calendar", ("calendar", "gcal"), "the profile's existing calendar integration"),
    ("email", ("gmail", "email", "mail"), "the profile's existing mail integration"),
    ("browser", ("browser", "browse", "computer"), "the profile's existing browser integration"),
    ("messaging", ("send_message", "message"), "the profile's existing messaging integration"),
    ("kanban", ("kanban_show",), "native Hermes Kanban"),
    ("automation", ("cronjob_manage",), "native Hermes scheduling"),
    ("secure_access", ("secure_access", "credential", "vault"), "an optional existing secret broker"),
)


def _matches(name: str, hints: Iterable[str]) -> bool:
    lowered = name.lower()
    return any(lowered == hint or hint in lowered for hint in hints)


def _native_entries() -> tuple[list[Any], Callable[[Callable[..., Any]], bool | None]]:
    """Return registry entries and the non-probing cached-check reader."""

    from tools.registry import get_cached_check_fn_result, registry

    return registry.get_all_entries(), get_cached_check_fn_result


def _recovery(status: str, capability: str) -> str:
    if capability == "portable_files":
        return "Verify the PA archive loaded, then retry the local import or export."
    if status == "available":
        return "Run one read-only list or readback before relying on account authentication."
    if status == "unverified":
        return "Use one read-only call through the existing integration, then rerun capability discovery."
    if status == "needs-setup":
        return "Complete that integration's existing profile setup, then rerun capability discovery."
    return "Enable an existing Hermes integration for this profile, then rerun capability discovery."


def discover(entries: Iterable[Any] | None = None,
             cached_check: Callable[[Callable[..., Any]], bool | None] | None = None,
             profile_root=None, *, secret_present=None, which=None) -> dict[str, Any]:
    """Describe registrations and CLI/Browserbase credential presence without probing.

    A registered tool with no check is available. A cached successful check is also
    available; cached failure means setup is needed. A registration whose check has
    never run is unverified. Absence is unavailable. None of these states proves that
    a provider account is authenticated.
    """

    native = entries is None
    discovery_error = None
    if entries is None:
        try:
            entries, cached_check = _native_entries()
        except Exception as exc:  # Hermes-free tests and damaged runtime installs.
            entries, cached_check = (), None
            discovery_error = type(exc).__name__
    entries = list(entries)
    which = which or shutil.which
    gog = os.environ.get("GOG_PATH") or which("gog")
    rows = []
    for capability, hints, reuse in _SPECS:
        matched = [entry for entry in entries if _matches(str(getattr(entry, "name", "")), hints)]
        if capability == "portable_files" and not matched:
            # The operation is implemented by this plugin even in a narrow registry fixture.
            status, evidence = "available", "plugin-native import/export"
            tool_names = ["pa"]
        elif capability == "calendar" and profile_root is not None and not matched:
            present = (Path(profile_root) / "google_token.json").is_file()
            status = "unverified" if present else "needs-setup"
            evidence = "native PA Google helper; existing profile authorization file present, scopes and account require readback" if present else "native PA Google helper; use an existing integration or configure missing Google access"
            tool_names = sorted({"pa", *(str(entry.name) for entry in matched)})
        elif not matched:
            status, evidence, tool_names = "unavailable", "no matching active tool registration", []
        else:
            verdicts = []
            for entry in matched:
                check = getattr(entry, "check_fn", None)
                verdicts.append(True if check is None else (cached_check(check) if cached_check else None))
            if any(verdict is True for verdict in verdicts):
                status, evidence = "available", "active tool registration with satisfied availability check"
            elif any(verdict is None for verdict in verdicts):
                status, evidence = "unverified", "active registration; availability check has no current cached result"
            else:
                status, evidence = "needs-setup", "active registration; current cached availability check failed"
            tool_names = sorted({str(entry.name) for entry in matched})
        if gog and capability in {"calendar", "email"}:
            status = "available" if matched and status == "available" else "unverified"
            tool_names = ["gog", *(name for name in tool_names if name != "gog")]
            evidence += "; gog CLI present; account authorisation is unverified"
            reuse += " or the gog CLI"
        rows.append({
            "id": capability,
            "status": status,
            "tools": tool_names,
            "reuse": reuse,
            "evidence": evidence,
            "authentication": "unverified",
            "recovery_action": _recovery(status, capability),
        })
    from .browserbase import secret
    present = secret_present or ((lambda name: bool(secret(name))) if native else (lambda name: False))
    try:
        configured = all(present(name) for name in ("BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"))
    except Exception:
        configured = False
    status = "available" if configured else "needs-setup"
    missing_cli = configured and which("agent-browser") is None
    if missing_cli:
        status = "needs-setup"
    rows.append({"id": "remote_browser", "status": status, "tools": ["pa"],
                 "reuse": "PA Browserbase live-view handoff", "authentication": "unverified",
                 "evidence": "Browserbase key and project present; agent-browser CLI not found on PATH" if missing_cli else
                 "browser_session operation; credentials present" if configured else
                 "add BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID to the profile's secrets",
                 "recovery_action": "Install agent-browser on this host, then rerun capability discovery." if missing_cli else
                 _recovery(status, "remote_browser")})
    counts = Counter(row["status"] for row in rows)
    result = {
        "capabilities": rows,
        "setup_skill": "personal-assistant:personal-assistant",
        "summary": {state: counts.get(state, 0) for state in
                    ("available", "needs-setup", "unverified", "unavailable")},
        "authentication": "Capability discovery does not prove provider authentication.",
        "jobs_started": False,
    }
    if discovery_error:
        result["discovery_error"] = discovery_error
    return result
