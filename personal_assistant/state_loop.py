"""Generic, account-agnostic event-to-projection state loops."""
import datetime as dt
import json
import uuid

from .privacy import clean
from .state import now, stable_id

TERMINAL_PROJECTION_STATES = {"confirmed", "not_applicable"}
ATTENTION_PROJECTION_STATES = {"failed", "unknown"}
RESULT_STATES = TERMINAL_PROJECTION_STATES | ATTENTION_PROJECTION_STATES


def _timestamp(value=None):
    if value is None:
        return now()
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _json(value):
    return json.dumps(clean(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class StateLoop:
    """Persist deterministic events and their required projection receipts."""

    def __init__(self, ledger):
        self.ledger = ledger
        self._ensure_schema()

    def _ensure_schema(self):
        with self.ledger.connect() as conn:
            conn.executescript(
                """
                create table if not exists pa_events(
                    event_id text primary key,
                    source_type text not null,
                    source_id text not null,
                    source_revision text not null,
                    occurred_at text,
                    payload_json text not null,
                    status text not null,
                    created_at text not null,
                    updated_at text not null,
                    unique(source_type, source_id)
                );
                create table if not exists pa_event_revisions(
                    event_id text not null,
                    source_revision text not null,
                    occurred_at text,
                    payload_json text not null,
                    observed_at text not null,
                    primary key(event_id, source_revision),
                    foreign key(event_id) references pa_events(event_id)
                );
                create table if not exists pa_projections(
                    event_id text not null,
                    projection_key text not null,
                    source_revision text not null,
                    target_type text not null,
                    target_id text not null,
                    expected_revision text,
                    status text not null,
                    claim_token text,
                    claimed_by text,
                    claimed_at text,
                    lease_until text,
                    result_json text,
                    updated_at text not null,
                    primary key(event_id, projection_key),
                    foreign key(event_id) references pa_events(event_id)
                );
                create table if not exists pa_projection_freshness(
                    event_id text not null,
                    projection_key text not null,
                    source_revision text not null,
                    freshness_seconds integer not null,
                    fresh_until text,
                    primary key(event_id, projection_key)
                );
                create table if not exists pa_projection_history(
                    event_id text not null,
                    source_revision text not null,
                    projection_key text not null,
                    target_type text not null,
                    target_id text not null,
                    expected_revision text,
                    status text not null,
                    claim_token text,
                    claimed_by text,
                    claimed_at text,
                    lease_until text,
                    result_json text,
                    archived_at text not null,
                    primary key(event_id, source_revision, projection_key)
                );
                create table if not exists pa_projection_freshness_history(
                    event_id text not null,
                    source_revision text not null,
                    projection_key text not null,
                    freshness_seconds integer not null,
                    fresh_until text,
                    archived_at text not null,
                    primary key(event_id, source_revision, projection_key),
                    foreign key(event_id, source_revision, projection_key)
                        references pa_projection_history(event_id, source_revision, projection_key)
                );
                create table if not exists pa_projection_attempts(
                    claim_token text not null,
                    event_id text not null,
                    source_revision text not null,
                    projection_key text not null,
                    claimed_by text not null,
                    claimed_at text not null,
                    lease_until text not null,
                    outcome text not null,
                    proof_json text,
                    recorded_at text not null,
                    primary key(claim_token, outcome)
                );
                insert or ignore into pa_projection_freshness_history(
                    event_id,source_revision,projection_key,freshness_seconds,fresh_until,archived_at)
                select f.event_id,f.source_revision,f.projection_key,f.freshness_seconds,f.fresh_until,h.archived_at
                from pa_projection_freshness f join pa_projection_history h
                  on h.event_id=f.event_id and h.source_revision=f.source_revision
                 and h.projection_key=f.projection_key
                where not exists(
                    select 1 from pa_projections p
                    where p.event_id=f.event_id and p.source_revision=f.source_revision
                      and p.projection_key=f.projection_key
                );
                delete from pa_projection_freshness
                where not exists(
                    select 1 from pa_projections p
                    where p.event_id=pa_projection_freshness.event_id
                      and p.source_revision=pa_projection_freshness.source_revision
                      and p.projection_key=pa_projection_freshness.projection_key
                );
                """
            )

    @staticmethod
    def _projections(items):
        if not isinstance(items, list) or not items:
            raise ValueError("at least one required projection is required")
        result = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("each projection must be an object")
            row = {name: item.get(name) for name in (
                "projection_key", "target_type", "target_id", "expected_revision", "freshness_seconds"
            )}
            if not row["projection_key"] or not row["target_type"] or not row["target_id"]:
                raise ValueError("projection_key, target_type and target_id are required")
            if row["projection_key"] in seen:
                raise ValueError("projection_key must be unique within an event")
            freshness = row["freshness_seconds"]
            if freshness is not None and (
                isinstance(freshness, bool) or not isinstance(freshness, int) or freshness < 1 or freshness > 315360000
            ):
                raise ValueError("freshness_seconds must be an integer from 1 to 315360000")
            seen.add(row["projection_key"])
            result.append(row)
        return sorted(result, key=lambda row: row["projection_key"])

    def event_upsert(self, *, source_type, source_id, source_revision, projections, payload=None, occurred_at=None):
        if not source_type or not source_id or not source_revision:
            raise ValueError("source_type, source_id and source_revision are required")
        event_id = stable_id("pa-state-loop-event", source_type, source_id)
        projection_rows = self._projections(projections)
        payload_json = _json(payload or {})
        occurred_at = _timestamp(occurred_at) if occurred_at else None
        stamp = now()
        replayed = False
        with self.ledger.connect() as conn:
            conn.execute("begin immediate")
            event = conn.execute("select * from pa_events where event_id=?", (event_id,)).fetchone()
            current = conn.execute(
                """select p.projection_key,p.target_type,p.target_id,p.expected_revision,f.freshness_seconds
                   from pa_projections p left join pa_projection_freshness f
                     on f.event_id=p.event_id and f.projection_key=p.projection_key
                    and f.source_revision=p.source_revision
                   where p.event_id=? order by p.projection_key""",
                (event_id,),
            ).fetchall()
            current_def = [dict(row) for row in current]
            if event and event["source_revision"] == source_revision:
                if event["payload_json"] != payload_json or current_def != projection_rows or event["occurred_at"] != occurred_at:
                    raise ValueError("event content changed without a new source_revision")
                replayed = True
            else:
                if event:
                    known_revision = conn.execute(
                        "select 1 from pa_event_revisions where event_id=? and source_revision=?",
                        (event_id, source_revision),
                    ).fetchone()
                    if known_revision:
                        raise ValueError("source_revision was already processed and is no longer current")
                    unresolved_unknown = conn.execute(
                        "select 1 from pa_projections where event_id=? and status='unknown' limit 1",
                        (event_id,),
                    ).fetchone()
                    if unresolved_unknown:
                        raise ValueError("resolve unknown projection outcome before accepting a new source revision")
                    active_claim = conn.execute(
                        "select 1 from pa_projections where event_id=? and status='claimed' and lease_until>? limit 1",
                        (event_id, stamp),
                    ).fetchone()
                    if active_claim:
                        raise ValueError("active projection claim must finish or expire before accepting a new source revision")
                    conn.execute(
                        """insert or replace into pa_projection_history
                           select event_id,source_revision,projection_key,target_type,target_id,expected_revision,status,
                                  claim_token,claimed_by,claimed_at,lease_until,result_json,?
                           from pa_projections where event_id=?""",
                        (stamp, event_id),
                    )
                    conn.execute(
                        """insert or replace into pa_projection_freshness_history(
                               event_id,source_revision,projection_key,freshness_seconds,fresh_until,archived_at)
                           select f.event_id,f.source_revision,f.projection_key,f.freshness_seconds,f.fresh_until,?
                           from pa_projection_freshness f join pa_projections p
                             on p.event_id=f.event_id and p.projection_key=f.projection_key
                            and p.source_revision=f.source_revision
                           where f.event_id=?""",
                        (stamp, event_id),
                    )
                    conn.execute("delete from pa_projection_freshness where event_id=?", (event_id,))
                    conn.execute("delete from pa_projections where event_id=?", (event_id,))
                    conn.execute(
                        "update pa_events set source_revision=?,occurred_at=?,payload_json=?,status='pending',updated_at=? where event_id=?",
                        (source_revision, occurred_at, payload_json, stamp, event_id),
                    )
                else:
                    conn.execute(
                        "insert into pa_events values(?,?,?,?,?,?,?,?,?)",
                        (event_id, source_type, source_id, source_revision, occurred_at, payload_json, "pending", stamp, stamp),
                    )
                conn.execute(
                    "insert into pa_event_revisions values(?,?,?,?,?)",
                    (event_id, source_revision, occurred_at, payload_json, stamp),
                )
                for row in projection_rows:
                    conn.execute(
                        """insert into pa_projections(
                               event_id,projection_key,source_revision,target_type,target_id,expected_revision,
                               status,claim_token,claimed_by,claimed_at,lease_until,result_json,updated_at)
                           values(?,?,?,?,?,?,'pending',null,null,null,null,null,?)""",
                        (event_id, row["projection_key"], source_revision, row["target_type"], row["target_id"], row["expected_revision"], stamp),
                    )
                    if row["freshness_seconds"] is not None:
                        conn.execute(
                            """insert into pa_projection_freshness(
                                   event_id,projection_key,source_revision,freshness_seconds,fresh_until)
                               values(?,?,?,?,null)""",
                            (event_id, row["projection_key"], source_revision, row["freshness_seconds"]),
                        )
        result = self.get_event(event_id)
        result["replayed"] = replayed
        return result

    def get_event(self, event_id):
        with self.ledger.connect() as conn:
            event = conn.execute("select * from pa_events where event_id=?", (event_id,)).fetchone()
            if not event:
                raise ValueError("unknown event_id")
            projections = conn.execute(
                """select p.*,f.freshness_seconds,f.fresh_until
                   from pa_projections p left join pa_projection_freshness f
                     on f.event_id=p.event_id and f.projection_key=p.projection_key
                    and f.source_revision=p.source_revision
                   where p.event_id=? order by p.projection_key""",
                (event_id,),
            ).fetchall()
        data = dict(event)
        data["payload"] = json.loads(data.pop("payload_json"))
        data["projections"] = []
        for row in projections:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json")) if item["result_json"] else None
            data["projections"].append(item)
        return data

    def projection_claim(self, *, event_id, projection_key, claimed_by, lease_seconds=300, at=None):
        if not claimed_by:
            raise ValueError("claimed_by is required")
        if not isinstance(lease_seconds, int) or lease_seconds < 1 or lease_seconds > 86400:
            raise ValueError("lease_seconds must be an integer from 1 to 86400")
        claimed_at = _timestamp(at)
        lease_until = (dt.datetime.fromisoformat(claimed_at) + dt.timedelta(seconds=lease_seconds)).isoformat()
        token = uuid.uuid4().hex
        with self.ledger.connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                "select * from pa_projections where event_id=? and projection_key=?", (event_id, projection_key)
            ).fetchone()
            if not row:
                raise ValueError("unknown event projection")
            expired = row["status"] == "claimed" and row["lease_until"] and row["lease_until"] <= claimed_at
            if row["status"] not in {"pending", "failed"} and not expired:
                raise ValueError("projection state does not permit claim")
            conn.execute(
                """update pa_projections set status='claimed',claim_token=?,claimed_by=?,claimed_at=?,lease_until=?,
                   result_json=null,updated_at=? where event_id=? and projection_key=?""",
                (token, claimed_by, claimed_at, lease_until, claimed_at, event_id, projection_key),
            )
            self._refresh_event(conn, event_id, claimed_at)
        return {"event_id": event_id, "projection_key": projection_key, "claim_token": token, "lease_until": lease_until}

    def projection_result(self, *, event_id, projection_key, claim_token, outcome, proof=None, at=None):
        if outcome not in RESULT_STATES:
            raise ValueError("invalid projection outcome")
        safe_proof = clean(proof)
        if outcome in TERMINAL_PROJECTION_STATES and not safe_proof:
            raise ValueError("readback evidence required for terminal projection outcome")
        stamp = _timestamp(at)
        proof_json = _json(safe_proof) if safe_proof else None
        result_json = _json({"outcome": outcome, "proof": safe_proof, "recorded_at": stamp})
        replayed = False
        with self.ledger.connect() as conn:
            conn.execute("begin immediate")
            attempt = conn.execute(
                "select * from pa_projection_attempts where claim_token=? and outcome=?", (claim_token, outcome)
            ).fetchone()
            if attempt:
                if (attempt["event_id"], attempt["projection_key"], attempt["outcome"], attempt["proof_json"]) != (
                    event_id, projection_key, outcome, proof_json
                ):
                    raise ValueError("claim result replay does not match the recorded result")
                replayed = True
            row = conn.execute(
                """select p.*,f.freshness_seconds,f.fresh_until
                   from pa_projections p left join pa_projection_freshness f
                     on f.event_id=p.event_id and f.projection_key=p.projection_key
                    and f.source_revision=p.source_revision
                   where p.event_id=? and p.projection_key=?""",
                (event_id, projection_key),
            ).fetchone()
            if replayed:
                pass
            elif not row or row["claim_token"] != claim_token or not (
                row["status"] == "claimed" or (row["status"] == "unknown" and outcome != "unknown")
            ):
                raise ValueError("projection claim does not permit result")
            elif row["status"] == "claimed" and row["lease_until"] <= stamp:
                raise ValueError("projection claim lease expired")
            else:
                fresh_until = None
                if outcome == "confirmed" and row["freshness_seconds"]:
                    fresh_until = (
                        dt.datetime.fromisoformat(stamp) + dt.timedelta(seconds=row["freshness_seconds"])
                    ).isoformat()
                conn.execute(
                    "insert into pa_projection_attempts values(?,?,?,?,?,?,?,?,?,?)",
                    (claim_token, event_id, row["source_revision"], projection_key, row["claimed_by"],
                     row["claimed_at"], row["lease_until"], outcome, proof_json, stamp),
                )
                conn.execute(
                    "update pa_projections set status=?,result_json=?,updated_at=? where event_id=? and projection_key=?",
                    (outcome, result_json, stamp, event_id, projection_key),
                )
                if row["freshness_seconds"]:
                    conn.execute(
                        """update pa_projection_freshness set fresh_until=?
                           where event_id=? and projection_key=?""",
                        (fresh_until, event_id, projection_key),
                    )
                self._refresh_event(conn, event_id, stamp)
        result = self.get_event(event_id)
        result["result_replayed"] = replayed
        return result

    @staticmethod
    def _refresh_event(conn, event_id, stamp):
        states = [row[0] for row in conn.execute("select status from pa_projections where event_id=?", (event_id,))]
        if states and all(state in TERMINAL_PROJECTION_STATES for state in states):
            status = "complete"
        elif any(state in ATTENTION_PROJECTION_STATES for state in states):
            status = "attention"
        elif any(state == "claimed" for state in states):
            status = "processing"
        else:
            status = "pending"
        conn.execute("update pa_events set status=?,updated_at=? where event_id=?", (status, stamp, event_id))

    def reconcile(self, *, event_id=None):
        params = []
        query = """select e.source_type,e.source_id,e.source_revision,e.status as event_status,
                          p.event_id,p.projection_key,p.target_type,p.target_id,p.status,p.claimed_by,p.lease_until,p.result_json
                   from pa_projections p join pa_events e on e.event_id=p.event_id
                   where p.status not in ('confirmed','not_applicable')"""
        if event_id:
            query += " and p.event_id=?"
            params.append(event_id)
        query += " order by e.updated_at,p.projection_key"
        with self.ledger.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        issues = []
        for row in rows:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json")) if item["result_json"] else None
            issues.append(item)
        return {"issues": issues, "count": len(issues)}

    def freshness(self, *, event_id=None, at=None):
        if at is None:
            raise ValueError("freshness requires an explicit at timestamp")
        evaluated_at = _timestamp(at)
        params = []
        query = """select e.source_type,e.source_id,e.source_revision,e.status as event_status,
                          p.event_id,p.projection_key,p.target_type,p.target_id,p.status,p.claimed_by,
                          p.lease_until,f.freshness_seconds,f.fresh_until
                   from pa_projections p join pa_events e on e.event_id=p.event_id
                   left join pa_projection_freshness f
                     on f.event_id=p.event_id and f.projection_key=p.projection_key
                    and f.source_revision=p.source_revision"""
        if event_id:
            query += " where p.event_id=?"
            params.append(event_id)
        query += " order by e.updated_at,p.projection_key"
        with self.ledger.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        issues = []
        for row in rows:
            item = dict(row)
            status = item["status"]
            reason = None
            if status == "pending":
                reason = "never_processed"
            elif status == "claimed" and item["lease_until"] and item["lease_until"] <= evaluated_at:
                reason = "overdue_projection"
            elif status == "failed":
                reason = "failed_projection"
            elif status == "unknown":
                reason = "unknown_projection"
            elif status == "confirmed" and item["fresh_until"] and item["fresh_until"] <= evaluated_at:
                reason = "freshness_expired"
            if reason:
                item["reason"] = reason
                issues.append(item)
        return {"issues": issues, "count": len(issues), "evaluated_at": evaluated_at}
