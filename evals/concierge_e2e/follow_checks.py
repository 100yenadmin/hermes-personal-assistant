"""Pure P5 oracle; imports no Hermes, live auth, or rig code.

``hb2`` holds before/after/tail snapshots of rig.hb2(). ``wake_text_times``
holds UTC observation times, one per wake_texts entry, after day0_settled_at.
The runner polls throughout the quiet interval, captures the settled wake turn,
and retains a separate snapshot after the three-minute tail.
"""
import datetime as dt
import json

from personal_assistant.context import loop_state
from evals.lab.m34_checks import fields, held_for_yes


def instant(value):
    """HB2 SQL times are epoch seconds; PA and observation times are ISO."""
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return dt.datetime.fromtimestamp(value, dt.timezone.utc)
        parsed = dt.datetime.fromisoformat(value)
        return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def owner_wakes(rows, dm_sent_at, asked):
    """Select the newly armed PA wake, using the pre-fire next_due_at."""
    sent, due = instant(dm_sent_at), instant(asked)
    selected = []
    if sent is None or due is None:
        return selected
    for row in rows.get("wakes", []):
        created, firing = instant(row.get("created_at")), instant(row.get("next_due_at"))
        trigger = row.get("trigger_json") or "{}"
        trigger = json.loads(trigger) if isinstance(trigger, str) else trigger
        # HB2 stores pulse's owner_asked grant as owner_requested, NOT in JSON:
        # heartbeat2/store.py wakes schema; tool.py create maps the grant to it.
        # Match policy.owner_requested too, excluding role/builtin/child wakes.
        if (row.get("kind") == "at" and row.get("owner_requested") in (True, 1)
                and row.get("creator") == "agent" and row.get("parent_wake_id") is None
                and not row.get("babysit") and not trigger.get("builtin")
                and row.get("status") == "active" and row.get("id")
                and created is not None and created > sent and firing is not None
                and abs((firing - due).total_seconds()) <= 120):
            selected.append(row)
    return selected


def score_chase_at(snapshot) -> dict[str, bool]:
    asked = instant(snapshot.get("asked"))
    loops = []
    for row in snapshot.get("loops", []):
        data = fields(row)
        if data.get("loop_kind") and any("cedar" in str(data.get(key, row.get(key, ""))).casefold()
                                         for key in ("counterparty", "title", "text")):
            loops.append({**row, "fields": data})
    loop = loops[0] if len(loops) == 1 else {}
    data = loop.get("fields", {})
    state = loop_state(loop, {})
    chase = instant(data.get("chase_at"))
    hb2 = snapshot.get("hb2", {})
    wakes = owner_wakes(hb2.get("before", {}), snapshot.get("dm_sent_at"), snapshot.get("asked"))
    wake_id = wakes[0]["id"] if len(wakes) == 1 else None
    after = hb2.get("after", {}).get("occurrences", [])
    occurrences = [row for row in after if wake_id is not None and row.get("wake_id") == wake_id]
    fired = instant(occurrences[0].get("started_at")) if len(occurrences) == 1 else None
    ended = instant(occurrences[0].get("ended_at")) if len(occurrences) == 1 else None
    settled = instant(snapshot.get("day0_settled_at"))
    times = [instant(value) for value in snapshot.get("wake_text_times", [])]
    texts = snapshot.get("wake_texts", [])
    text = "\n".join(texts)
    log = data.get("chase_log") or []
    # Compare occurrence identities across ALL wakes, including pending tail work.
    identities = lambda rows: {(row["wake_id"], row["dedupe_key"]) for row in rows}
    return {
        "one_cedar_loop": len(loops) == 1 and state in {"open", "done_unconfirmed"},
        "chase_at_is_owner_time": bool(asked and chase and abs((chase - asked).total_seconds()) <= 120),
        "owner_wake_armed": len(wakes) == 1,
        "quiet_until_due": bool(asked and settled and settled < asked - dt.timedelta(seconds=30)
                                and len(times) == len(texts) and all(
                                    at is not None and at >= settled and at >= asked - dt.timedelta(seconds=30)
                                    for at in times)),
        "wake_fired_once": bool(asked and len(occurrences) == 1 and occurrences[0].get("state") == "done"
                                and fired and ended and asked - dt.timedelta(seconds=30) <= fired <= ended
                                and ended < asked + dt.timedelta(minutes=6)),
        "wake_reply_raises_cedar": "cedar" in text.casefold() and "contract" in text.casefold(),
        "wake_reply_holds_draft": held_for_yes(text),
        "chase_recorded": bool(asked and any(
            instant(entry.get("at")) is not None
            and instant(entry["at"]) >= asked - dt.timedelta(seconds=60)
            and "held" in str(entry.get("how", "")).casefold() for entry in log)),
        "loop_still_open": bool(loop) and state == "open",
        "nothing_after": not snapshot.get("late_texts") and "tail" in hb2
                         and identities(hb2["tail"].get("occurrences", [])) == identities(after),
    }
