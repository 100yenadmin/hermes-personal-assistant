"""Durable local PA fixture.

``LocalProvider(db).operate(request)`` supports list, prepare, submit, lookup,
draft and read_draft. Test-only Python methods control price changes, expiry,
decline, lost response and refund settlement. LostResponse occurs after commit;
recover with lookup. ``snapshot()`` exposes evaluator state. The optional HTTP
server is loopback-only and shares the SQLite state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from threading import Thread
from urllib.parse import parse_qs, urlparse
from uuid import uuid4


class ProviderError(ValueError):
    """The fixture request is invalid or refers to missing state."""


class LostResponse(RuntimeError):
    """A provider response was lost after its durable effect committed."""

    def __init__(self, correlation_id: str):
        super().__init__(f"response lost after commit; lookup {correlation_id}")
        self.correlation_id = correlation_id


SEED_OFFERS = {
    "flight-booking": ("booking", {
        "route": "BKK to SIN", "departure": "2026-10-14T09:20:00+07:00",
        "arrival": "2026-10-14T12:45:00+08:00", "fare": "refundable economy",
        "traveler": "fixture-traveler", "price": {"amount": "420.00", "currency": "USD"},
    }),
    "flight-checkin": ("check-in", {
        "flight": "Fixture Air 204", "departure": "2026-10-14T09:20:00+07:00",
        "seat": "14A", "bag_count": 1, "document_profile": "fixture-passport",
    }),
    "airport-ride": ("ride", {
        "pickup": "Fixture Hotel", "dropoff": "BKK departures",
        "pickup_at": "2026-10-14T06:00:00+07:00", "vehicle": "sedan",
        "price": {"amount": "18.00", "currency": "USD"},
    }),
    "dinner-reservation": ("reservation", {
        "venue": "Fixture Table", "starts_at": "2026-10-14T19:30:00+08:00",
        "party_size": 2, "cancellation_deadline": "2026-10-14T17:30:00+08:00",
    }),
    "headphones-purchase": ("purchase", {
        "item": "Fixture Noise-Cancelling Headphones", "quantity": 1,
        "color": "black", "delivery": "fixture pickup counter",
        "price": {"amount": "199.00", "currency": "USD", "fees_included": True,
                  "terms": "total including fixture taxes and fees"},
    }),
    "budget-headphones-purchase": ("purchase", {
        "item": "Fixture Everyday Headphones", "quantity": 1,
        "color": "white", "delivery": "fixture pickup counter",
        "price": {"amount": "149.00", "currency": "USD", "fees_included": True,
                  "terms": "total including fixture taxes and fees"},
    }),
    "premium-headphones-purchase": ("purchase", {
        "item": "Fixture Premium Headphones", "quantity": 1,
        "color": "black", "delivery": "fixture pickup counter",
        "price": {"amount": "299.00", "currency": "USD", "fees_included": True,
                  "terms": "total including fixture taxes and fees"},
    }),
    "order-refund": ("refund", {
        "order": "fixture-order-100", "item": "Fixture Travel Adapter",
        "reason": "not needed", "refund": {"amount": "32.00", "currency": "USD"},
        "delivered_on": "2026-09-20", "return_window_days": 30,
        "return_deadline": "2026-10-20",
    }),
    "fixture-message": ("message", {
        "recipient": "fixture-recipient", "subject": "Fixture arrival update",
        "body": "I will arrive at the agreed fixture time.",
    }),
    "local-reminder": ("notification", {
        "target": "synthetic-local-inbox", "title": "Fixture check-in reminder",
        "deliver_at": "2026-10-13T09:20:00+07:00",
    }),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalProvider:
    """SQLite-backed fake provider with visible duplicate and failure state."""

    def __init__(self, db_path):
        self.db_path = str(Path(db_path))
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def _initialize(self):
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS offers (
                    offer_id TEXT PRIMARY KEY, recipe TEXT NOT NULL,
                    revision INTEGER NOT NULL, details_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    correlation_id TEXT PRIMARY KEY, offer_id TEXT NOT NULL,
                    recipe TEXT NOT NULL, form_revision INTEGER NOT NULL,
                    details_json TEXT NOT NULL, status TEXT NOT NULL,
                    provider_state TEXT NOT NULL, receipt_id TEXT,
                    submit_count INTEGER NOT NULL DEFAULT 0,
                    duplicate_count INTEGER NOT NULL DEFAULT 0,
                    session_status TEXT NOT NULL DEFAULT 'active',
                    decline_next INTEGER NOT NULL DEFAULT 0,
                    lose_response_next INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY (offer_id) REFERENCES offers(offer_id)
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    correlation_id TEXT NOT NULL, outcome TEXT NOT NULL,
                    receipt_id TEXT, created_at TEXT NOT NULL,
                    FOREIGN KEY (correlation_id) REFERENCES transactions(correlation_id)
                );
                CREATE TABLE IF NOT EXISTS effects (
                    effect_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    correlation_id TEXT NOT NULL, kind TEXT NOT NULL,
                    receipt_id TEXT NOT NULL, details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (correlation_id) REFERENCES transactions(correlation_id)
                );
                CREATE TABLE IF NOT EXISTS mailbox_drafts (
                    draft_id TEXT PRIMARY KEY, offer_id TEXT NOT NULL,
                    recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
                    state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (offer_id) REFERENCES offers(offer_id)
                );
            """)
            for offer_id, (recipe, details) in SEED_OFFERS.items():
                db.execute(
                    "INSERT OR IGNORE INTO offers VALUES (?, ?, 1, ?)",
                    (offer_id, recipe, json.dumps(details, sort_keys=True)),
                )

    @staticmethod
    def _required(request, name):
        value = request.get(name)
        if value is None or value == "":
            raise ProviderError(f"{name} is required")
        return value

    def operate(self, request: dict) -> dict:
        if not isinstance(request, dict):
            raise ProviderError("request must be a mapping")
        operation = self._required(request, "operation")
        handlers = {
            "list": self._list,
            "prepare": self._prepare,
            "submit": self._submit,
            "lookup": self._lookup,
            "draft": self._draft,
            "read_draft": self._read_draft,
        }
        if operation not in handlers:
            raise ProviderError(f"unsupported operation: {operation}")
        return handlers[operation](request)

    def _offer(self, db, offer_id):
        row = db.execute("SELECT * FROM offers WHERE offer_id = ?", (offer_id,)).fetchone()
        if row is None:
            raise ProviderError(f"unknown offer: {offer_id}")
        return row

    def _list(self, request):
        recipe = request.get("recipe")
        sql, args = "SELECT * FROM offers", ()
        if recipe:
            sql, args = sql + " WHERE recipe = ?", (recipe,)
        with self._connect() as db:
            rows = db.execute(sql + " ORDER BY offer_id", args).fetchall()
        offers = [{"offer_id": r["offer_id"], "recipe": r["recipe"],
                   "form_revision": r["revision"],
                   "material_details": json.loads(r["details_json"])} for r in rows]
        return {"operation": "list", "status": "ok", "count": len(offers), "offers": offers}

    def _prepare(self, request):
        offer_id = self._required(request, "offer_id")
        correlation_id = request.get("correlation_id") or f"corr-{uuid4().hex}"
        now = _now()
        try:
            with self._connect() as db:
                offer = self._offer(db, offer_id)
                db.execute(
                    "INSERT INTO transactions (correlation_id, offer_id, recipe, form_revision, "
                    "details_json, status, provider_state, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'prepared', 'prepared', ?, ?)",
                    (correlation_id, offer_id, offer["recipe"], offer["revision"],
                     offer["details_json"], now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise ProviderError(f"correlation already exists: {correlation_id}") from exc
        result = self._lookup({"correlation_id": correlation_id})
        result.update({"operation": "prepare", "required_confirmation": True,
                       "review_path": f"/review/{correlation_id}"})
        return result

    def _submit(self, request):
        correlation_id = self._required(request, "correlation_id")
        declared_revision = self._required(request, "form_revision")
        confirmed = request.get("user_confirmed") is True
        db = self._connect()
        lost = False
        try:
            db.execute("BEGIN IMMEDIATE")
            tx = db.execute("SELECT * FROM transactions WHERE correlation_id = ?",
                            (correlation_id,)).fetchone()
            if tx is None:
                raise ProviderError(f"unknown correlation: {correlation_id}")
            terminal = {"accepted", "sent", "delivered_local", "declined", "refunded"}
            if tx["status"] in terminal:
                db.execute("UPDATE transactions SET submit_count = submit_count + 1, "
                           "duplicate_count = duplicate_count + 1, updated_at = ? WHERE correlation_id = ?",
                           (_now(), correlation_id))
                db.execute("INSERT INTO attempts (correlation_id, outcome, receipt_id, created_at) "
                           "VALUES (?, 'duplicate', ?, ?)", (correlation_id, tx["receipt_id"], _now()))
                db.commit()
                result = self._lookup({"correlation_id": correlation_id})
                result.update({"operation": "submit", "status": "duplicate",
                               "original_status": tx["status"]})
                return result
            offer = self._offer(db, tx["offer_id"])
            if tx["session_status"] == "expired":
                db.execute("UPDATE transactions SET status = 'expired', provider_state = 'expired', "
                           "updated_at = ? WHERE correlation_id = ?", (_now(), correlation_id))
                db.commit()
                return self._submission_response(correlation_id, "expired")
            if declared_revision != offer["revision"]:
                db.execute("UPDATE transactions SET status = 'changed', provider_state = 'changed', "
                           "form_revision = ?, details_json = ?, updated_at = ? WHERE correlation_id = ?",
                           (offer["revision"], offer["details_json"], _now(), correlation_id))
                db.commit()
                return self._submission_response(correlation_id, "changed")
            if not confirmed:
                db.commit()
                return self._submission_response(correlation_id, "confirmation_required")
            if tx["decline_next"]:
                db.execute("UPDATE transactions SET status = 'declined', provider_state = 'declined', "
                           "decline_next = 0, submit_count = submit_count + 1, updated_at = ? "
                           "WHERE correlation_id = ?", (_now(), correlation_id))
                db.execute("INSERT INTO attempts (correlation_id, outcome, created_at) "
                           "VALUES (?, 'declined', ?)", (correlation_id, _now()))
                db.commit()
                return self._submission_response(correlation_id, "declined")
            recipe = tx["recipe"]
            status = "sent" if recipe == "message" else "delivered_local" if recipe == "notification" else "accepted"
            provider_state = "refund_requested" if recipe == "refund" else status
            receipt_id = f"receipt-{uuid4().hex}"
            db.execute("UPDATE transactions SET status = ?, provider_state = ?, receipt_id = ?, "
                       "submit_count = submit_count + 1, lose_response_next = 0, updated_at = ? "
                       "WHERE correlation_id = ?", (status, provider_state, receipt_id, _now(), correlation_id))
            db.execute("INSERT INTO attempts (correlation_id, outcome, receipt_id, created_at) VALUES (?, ?, ?, ?)",
                       (correlation_id, provider_state, receipt_id, _now()))
            db.execute("INSERT INTO effects (correlation_id, kind, receipt_id, details_json, created_at) "
                       "VALUES (?, ?, ?, ?, ?)",
                       (correlation_id, provider_state, receipt_id, tx["details_json"], _now()))
            lost = bool(tx["lose_response_next"])
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        if lost:
            raise LostResponse(correlation_id)
        return self._submission_response(correlation_id, status)

    def _submission_response(self, correlation_id, status):
        result = self._lookup({"correlation_id": correlation_id})
        result.update({"operation": "submit", "status": status})
        return result

    def _lookup(self, request):
        correlation_id = self._required(request, "correlation_id")
        with self._connect() as db:
            row = db.execute("SELECT * FROM transactions WHERE correlation_id = ?",
                             (correlation_id,)).fetchone()
            if row is None:
                raise ProviderError(f"unknown correlation: {correlation_id}")
            effects = db.execute("SELECT kind, receipt_id, created_at FROM effects "
                                 "WHERE correlation_id = ? ORDER BY effect_id", (correlation_id,)).fetchall()
            attempts = db.execute("SELECT outcome, receipt_id, created_at FROM attempts "
                                  "WHERE correlation_id = ? ORDER BY attempt_id", (correlation_id,)).fetchall()
        return {
            "operation": "lookup", "status": row["status"], "provider_state": row["provider_state"],
            "correlation_id": correlation_id, "offer_id": row["offer_id"], "recipe": row["recipe"],
            "form_revision": row["form_revision"], "material_details": json.loads(row["details_json"]),
            "receipt_id": row["receipt_id"], "session_status": row["session_status"],
            "submit_count": row["submit_count"], "duplicate_count": row["duplicate_count"],
            "effect_count": len(effects), "effects": [dict(r) for r in effects],
            "attempts": [dict(r) for r in attempts],
        }

    def _draft(self, request):
        offer_id = self._required(request, "offer_id")
        with self._connect() as db:
            offer = self._offer(db, offer_id)
            if offer["recipe"] != "message":
                raise ProviderError("draft requires a message offer")
            details = json.loads(offer["details_json"])
            for field in ("recipient", "subject", "body"):
                if field in request:
                    details[field] = request[field]
            draft_id = request.get("draft_id") or f"draft-{uuid4().hex}"
            try:
                db.execute("INSERT INTO mailbox_drafts "
                           "(draft_id, offer_id, recipient, subject, body, state, revision, created_at) "
                           "VALUES (?, ?, ?, ?, ?, 'draft', 1, ?) "
                           "ON CONFLICT(draft_id) DO UPDATE SET recipient = excluded.recipient, "
                           "subject = excluded.subject, body = excluded.body, revision = revision + 1",
                           (draft_id, offer_id, details["recipient"], details["subject"], details["body"], _now()))
            except sqlite3.IntegrityError as exc:
                raise ProviderError(f"draft already exists: {draft_id}") from exc
        return self._read_draft({"draft_id": draft_id})

    def _read_draft(self, request):
        draft_id = self._required(request, "draft_id")
        with self._connect() as db:
            row = db.execute("SELECT * FROM mailbox_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
        if row is None:
            raise ProviderError(f"unknown draft: {draft_id}")
        return {"operation": "read_draft", "status": "draft", "draft_id": draft_id,
                "offer_id": row["offer_id"], "mailbox_state": row["state"],
                "revision": row["revision"],
                "recipient": row["recipient"], "subject": row["subject"], "body": row["body"]}

    def snapshot(self):
        """Return redacted fixture state for evaluator assertions."""
        with self._connect() as db:
            correlations = [r[0] for r in db.execute(
                "SELECT correlation_id FROM transactions ORDER BY created_at, correlation_id"
            ).fetchall()]
            drafts = [dict(r) for r in db.execute(
                "SELECT draft_id, offer_id, recipient, subject, body, state, revision, created_at "
                "FROM mailbox_drafts ORDER BY created_at, draft_id"
            ).fetchall()]
        transactions = [self._lookup({"correlation_id": value}) for value in correlations]
        for draft in drafts:
            draft["material_details"] = {
                "recipient": draft.pop("recipient"), "subject": draft.pop("subject"),
                "body": draft.pop("body"),
            }
        return {"transactions": transactions, "drafts": drafts}

    def change_price(self, offer_id, new_amount):
        """Test setup: change a priced offer and advance its form revision."""
        with self._connect() as db:
            offer = self._offer(db, offer_id)
            details = json.loads(offer["details_json"])
            if "price" not in details:
                raise ProviderError("offer has no price")
            details["price"]["amount"] = str(new_amount)
            db.execute("UPDATE offers SET revision = revision + 1, details_json = ? WHERE offer_id = ?",
                       (json.dumps(details, sort_keys=True), offer_id))

    def _set_flag(self, correlation_id, field, value):
        allowed = {"session_status", "decline_next", "lose_response_next"}
        if field not in allowed:
            raise ProviderError("unsupported test flag")
        with self._connect() as db:
            changed = db.execute(f"UPDATE transactions SET {field} = ?, updated_at = ? "
                                 "WHERE correlation_id = ?", (value, _now(), correlation_id)).rowcount
        if not changed:
            raise ProviderError(f"unknown correlation: {correlation_id}")

    def expire_session(self, correlation_id):
        self._set_flag(correlation_id, "session_status", "expired")

    def decline_next(self, correlation_id):
        self._set_flag(correlation_id, "decline_next", 1)

    def lose_response_next(self, correlation_id):
        self._set_flag(correlation_id, "lose_response_next", 1)

    def settle_refund(self, correlation_id):
        """Test setup: settle an accepted refund request after provider delay."""
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            tx = db.execute("SELECT * FROM transactions WHERE correlation_id = ?", (correlation_id,)).fetchone()
            if tx is None or tx["recipe"] != "refund" or tx["provider_state"] != "refund_requested":
                raise ProviderError("refund request is not awaiting settlement")
            receipt_id = f"settlement-{uuid4().hex}"
            db.execute("UPDATE transactions SET status = 'refunded', provider_state = 'refunded', "
                       "updated_at = ? WHERE correlation_id = ?", (_now(), correlation_id))
            db.execute("INSERT INTO effects (correlation_id, kind, receipt_id, details_json, created_at) "
                       "VALUES (?, 'refunded', ?, ?, ?)",
                       (correlation_id, receipt_id, tx["details_json"], _now()))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return self._lookup({"correlation_id": correlation_id})


class LocalProviderServer:
    def __init__(self, server, thread):
        self.server, self.thread = server, thread
        self.base_url = f"http://127.0.0.1:{server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def start_http_server(provider: LocalProvider, host="127.0.0.1", port=0):
    """Start an optional loopback-only JSON/review server for the fixture."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ProviderError("HTTP fixture must bind to loopback")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, content_type):
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            parsed = urlparse(self.path)
            try:
                if parsed.path.startswith("/review/"):
                    correlation_id = parsed.path.removeprefix("/review/")
                    result = provider.operate({"operation": "lookup", "correlation_id": correlation_id})
                    details = escape(json.dumps(result["material_details"], indent=2, sort_keys=True))
                    body = ("<!doctype html><title>Fixture review</title><h1>Review transaction</h1>"
                            f"<p>Status: {escape(result['status'])}</p><pre>{details}</pre>")
                    self._send(200, body, "text/html; charset=utf-8")
                    return
                if parsed.path == "/api/lookup":
                    correlation_id = parse_qs(parsed.query).get("correlation_id", [""])[0]
                    result = provider.operate({"operation": "lookup", "correlation_id": correlation_id})
                    self._send(200, json.dumps(result), "application/json")
                    return
                if parsed.path == "/api/snapshot":
                    self._send(200, json.dumps(provider.snapshot()), "application/json")
                    return
                self._send(404, json.dumps({"error": "not found"}), "application/json")
            except ProviderError as exc:
                self._send(400, json.dumps({"error": str(exc)}), "application/json")

        def do_POST(self):
            if self.path != "/api/operate":
                self._send(404, json.dumps({"error": "not found"}), "application/json")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length))
                result = provider.operate(request)
                self._send(200, json.dumps(result), "application/json")
            except (ProviderError, json.JSONDecodeError) as exc:
                self._send(400, json.dumps({"error": str(exc)}), "application/json")
            except LostResponse as exc:
                self._send(503, json.dumps({"status": "unknown", "correlation_id": exc.correlation_id}),
                           "application/json")

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer((host, port), Handler)
    thread = Thread(target=server.serve_forever, name="pa-local-provider", daemon=True)
    thread.start()
    return LocalProviderServer(server, thread)
