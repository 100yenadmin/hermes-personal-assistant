"""Read-only preflight for customer-confirmed daily-ops registration."""
from __future__ import annotations

import json
import os
import shutil
import sys
import datetime as dt
from pathlib import Path

from ..automation import canonical_notification_payload, notification_receipt
from ..state import Ledger, stable_id
from .config import load_config, profile_root, validate_config
from .gog_collector import DailyOpsError, auth_check, gog_binary

BROAD_JUNK = ("cloud-platform", "pubsub", "ediscovery")


def check_config(cfg: dict):
    errors = validate_config(cfg, require_profile=True)
    return (not errors, "; ".join(errors) if errors else "config valid")


def _delivery_receipt(cfg: dict):
    """Resolve delivery proof through the existing PA rule/receipt lifecycle."""
    try:
        root = profile_root()
    except DailyOpsError:
        return None
    candidate = root / "state" / "travel-ledger" / "travel.sqlite"
    if not candidate.is_file() or candidate.is_symlink():
        return None
    delivery = cfg.get("delivery") or {}
    verification = delivery.get("verification")
    if not isinstance(verification, dict):
        return None
    tenant = cfg.get("tenant") or {}
    accounts = cfg.get("accounts") or {}
    target = delivery.get("target")
    timezone = cfg.get("timezone")
    profile_id = tenant.get("profile_id")
    occurrence_id = verification.get("occurrence_id", verification.get("notification_occurrence_id"))
    expected_rule_id = verification.get("rule_id")
    expected_revision = verification.get("rule_revision", verification.get("revision"))
    expected_action_id = verification.get("action_id")
    if not all(isinstance(value, str) and value.strip() for value in
               (target, timezone, profile_id, occurrence_id, expected_rule_id, expected_revision)):
        return None

    def aware(value):
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

    try:
        ledger = Ledger(root)
        rules = []
        for action in ledger.list("action"):
            if action.get("action_type") != "automation_rule":
                continue
            fields = action.get("fields") if isinstance(action.get("fields"), dict) else {}
            rule = dict(fields)
            if isinstance(fields.get("automation_rule"), dict):
                rule.update(fields["automation_rule"])
            if str(rule.get("automation_rule_id", rule.get("rule_id", ""))) != expected_rule_id:
                continue
            rules.append((action, rule))
        if len(rules) != 1:
            return None
        action, rule = rules[0]
        account = rule.get("account")
        revision = rule.get("rule_revision", rule.get("revision"))
        if (rule.get("accepted") is not True or rule.get("destination_verified") is not True
                or rule.get("destination") != target or rule.get("profile_id") != profile_id
                or rule.get("timezone") != timezone or not isinstance(account, str)
                or account not in {accounts.get("work"), accounts.get("personal")}
                or revision != expected_revision):
            return None
        accepted_at, verified_at = aware(rule.get("accepted_at")), aware(rule.get("verified_at"))
        if accepted_at is None or verified_at is None or verified_at < accepted_at:
            return None
        payload = canonical_notification_payload(
            profile_id=profile_id, account=account, timezone=timezone,
            destination=target, rule_id=expected_rule_id, rule_revision=expected_revision,
        )
        payload_digest = stable_id(payload)
        if verification.get("payload_digest") is not None and verification.get("payload_digest") != payload_digest:
            return None
        receipt = notification_receipt(ledger, occurrence_id)
        if not isinstance(receipt, dict) or receipt.get("occurrence_id") != occurrence_id:
            return None
        if expected_action_id is not None and receipt.get("action_id") != expected_action_id:
            return None
        if (receipt.get("state") != "delivered" or receipt.get("rule_id") != expected_rule_id
                or receipt.get("payload_digest") != payload_digest):
            return None
        proof = receipt.get("provider_proof")
        if not isinstance(proof, dict) or not isinstance(proof.get("provider"), str) or not proof["provider"].strip():
            return None
        reference = proof.get("receipt_reference") or proof.get("receipt_id")
        if not isinstance(reference, str) or not reference.strip():
            return None
        expected_reference = verification.get("receipt_reference") or verification.get("receipt_id")
        if expected_reference is not None and expected_reference != reference:
            return None
        observed_at = aware(proof.get("observed_at"))
        if observed_at is None or observed_at < verified_at:
            return None
        return {"action_id": action.get("action_id"), "kind": rule.get("kind"),
                "accepted_at": rule["accepted_at"], "verified_at": rule["verified_at"],
                "notification_action_id": receipt["action_id"], "receipt_reference": reference,
                "provider": proof["provider"], "observed_at": proof["observed_at"]}
    except (DailyOpsError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def check_delivery(cfg: dict):
    delivery = cfg.get("delivery") or {}
    if delivery.get("verified") is not True:
        return False, "delivery.verified must be the JSON boolean true"
    receipt = _delivery_receipt(cfg)
    if not isinstance(receipt, dict):
        return False, "no matching accepted PA automation rule; customer must verify the destination through pa automations"
    return True, f"delivery target and PA automation receipt match ({receipt['kind']})"


def check_gog(cfg=None):
    try:
        return True, f"gog found: {gog_binary()}"
    except DailyOpsError as exc:
        if isinstance(cfg, dict) and (cfg.get("calendar") or {}).get("provider") == "profile_google":
            return True, "gog mail collector unavailable; calendar-only packets will report incomplete mail coverage"
        return False, str(exc)


def _scope_names(scopes):
    exact = {
        "https://www.googleapis.com/auth/gmail.readonly": "gmail",
        "https://www.googleapis.com/auth/calendar.readonly": "calendar",
    }
    identity = {"openid", "email", "https://www.googleapis.com/auth/userinfo.email"}
    values = set()
    for raw in scopes:
        if raw in exact:
            values.add(exact[raw])
        elif raw in identity:
            values.add("email" if raw == "https://www.googleapis.com/auth/userinfo.email" else raw)
        else:
            values.add(raw)
    return values


def check_scopes(cfg: dict):
    accounts = cfg.get("accounts") or {}
    calendar_first = (cfg.get("calendar") or {}).get("provider") == "profile_google"
    requested = [(accounts.get("work"), {"gmail"} if calendar_first else {"gmail", "calendar"}), (accounts.get("personal"), {"gmail"})]
    requested = [(account, required) for account, required in requested if account]
    try:
        binary = gog_binary()
    except DailyOpsError as exc:
        if calendar_first:
            return True, "gog mail auth unavailable; calendar-only packets will report incomplete mail coverage"
        return False, str(exc)
    failures = []
    try:
        data = auth_check()
        if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
            raise ValueError
    except (DailyOpsError, ValueError, TypeError):
        if calendar_first:
            return True, "gog mail auth unverified; calendar-only packets will report incomplete mail coverage"
        return False, "gog auth check failed; customer must reauthenticate"
    entries = data["accounts"]
    for index, (account, required) in enumerate(requested, 1):
        entry = next((item for item in entries if isinstance(item, dict) and item.get("email") == account), None)
        if not entry:
            failures.append(f"account-{index}: not authenticated")
            continue
        scopes = entry.get("scopes")
        if entry.get("valid") is not True:
            failures.append(f"account-{index}: auth check did not prove a valid refresh token")
            continue
        if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
            failures.append(f"account-{index}: auth scope response invalid")
            continue
        names = _scope_names(scopes)
        missing = required - names
        junk = [scope for scope in names if any(token in scope for token in BROAD_JUNK)]
        unsupported = names - required - {"openid", "userinfo", "email"}
        if missing:
            failures.append(f"account-{index}: missing required scopes ({', '.join(sorted(missing))})")
        if junk:
            failures.append(f"account-{index}: broad scopes present")
        if unsupported and not junk:
            failures.append(f"account-{index}: unsupported extra scopes present")
    if failures and calendar_first:
        return True, "gog mail scope unavailable or unverified; calendar-only packets will report incomplete mail coverage"
    return (not failures, "; ".join(failures) if failures else "required least-privilege scopes present")


def check_optional_clis(cfg: dict):
    messages, ok = [], True
    connector = (((cfg.get("priority") or {}).get("connectors") or {}).get("clients_sync")) or {}
    if isinstance(connector, dict) and connector.get("enabled") is True:
        for name, needed in (("stripe", bool(connector.get("stripe_account"))), ("supabase", bool(connector.get("supabase_ref")))):
            if needed:
                found = bool(shutil.which(name))
                ok = ok and found
                messages.append(f"{name}: {'found' if found else 'MISSING'}")
    if (cfg.get("travel") or {}).get("leave_by") is True:
        found = bool(shutil.which("curl"))
        ok = ok and found
        messages.append(f"curl: {'found' if found else 'MISSING'}")
    return ok, "; ".join(messages) if messages else "no optional dependencies required"


CHECKS = (check_config, check_delivery, check_gog, check_scopes, check_optional_clis)


def main() -> None:
    try:
        cfg = load_config()
    except DailyOpsError:
        print("❌ doctor: cannot load configuration; repair the profile config")
        raise SystemExit(1)
    all_ok = True
    for check in CHECKS:
        try:
            ok, message = check(cfg)
        except Exception:
            ok, message = False, "check failed; inspect the redacted configuration and profile"
        all_ok = all_ok and ok
        print(f"{'✅' if ok else '❌'} {check.__name__.replace('check_', '')}: {message}")
    if not all_ok:
        print("\ndoctor FAILED — fix the items above; no jobs were registered")
        raise SystemExit(1)
    print("\ndoctor OK — registration remains a customer-confirmed agent action")


if __name__ == "__main__":
    main()
