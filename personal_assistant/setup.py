"""Durable guided-setup progress; records intent, never performs proposed writes."""
import hashlib
from pathlib import Path

from .state import legacy, now

CORE_QUESTIONS = ("call_and_quiet", "worth_a_message", "authority", "first_trip",
                  "arrival_help", "protect", "route", "check_in_time")
CHIEF_OF_STAFF_QUESTIONS = ("cos_priorities", "cos_radar_topics", "cos_daily_time",
                            "cos_kickoff_slot", "cos_weekly_slot", "cos_schedule_choices")
PROFILE_GROUPS = (
    ("business", ("biz_what", "biz_priorities", "biz_people", "biz_confidential")),
    ("you", ("you_role", "you_rhythm", "you_interrupt", "you_offload")),
    ("communication", ("comm_channel", "comm_rhythm", "comm_format")),
    ("decision_rights", ("rights_act", "rights_draft", "rights_ask", "rights_spend", "rights_backup")),
    ("voice", ("voice_tone", "voice_examples", "prefs_travel", "prefs_life")),
    ("calendar", ("cal_rules", "cal_protect", "cal_people")),
    ("history", ("hist_past", "hist_worries")),
    ("access", ("access_systems", "access_off_limits")),
)
PROFILE_QUESTIONS = tuple(q for _, ids in PROFILE_GROUPS for q in ids)
SECTIONS = {"core": CORE_QUESTIONS, "chief_of_staff": CHIEF_OF_STAFF_QUESTIONS, "profile": PROFILE_QUESTIONS}
EQUIVALENT_IDS = ({"biz_priorities", "cos_priorities"},)  # Exact equivalents only; a covered ID is never asked.
# A related source answers only part of its ID: the ID is still asked, for the missing part only.
RELATED_IDS = {"rights_ask": "authority", "comm_channel": "route", "comm_rhythm": "worth_a_message"}
FILE_TARGETS = {"user_memory", "soul_section", "manual_skill", "context_file"}
TARGETS = FILE_TARGETS | {"pa_preferences"}  # Via pa automations preferences; no file/readback.


def _view(fields):
    result = {"status": "not_started", "requested_section": None, "requested_mode": None,
              "asked": [], "answers": {}, "skipped": [], "proposal": {"writes": []},
              "applied": [], "applied_session_id": None, "fresh_check": {}, "pending_changes": False,
              "offer_shown_at": None, "updated_at": None, "look_around_consent": None,
              "active_platform": None, "active_sender_id": None, "active_chat": None, "sitting_group": None, **fields}
    current_ids = {q for section in SECTIONS.values() for q in section}
    result["answers"] = {q: answer for q, answer in result["answers"].items() if q in current_ids}
    for key in ("asked", "skipped"):
        result[key] = [q for q in result[key] if q in current_ids]
    result["covered"] = {q: source for ids in EQUIVALENT_IDS for q in sorted(ids)
                         if q not in result["answers"]
                         for source in sorted(ids & result["answers"].keys())[:1]}
    covered = result["answers"].keys() | result["covered"].keys()
    result["related"] = {q: source for q, source in RELATED_IDS.items()
                         if q not in result["answers"] and source in result["answers"]}
    review = result["requested_mode"] == "review"  # A review covers every section's saved answers.
    questions = (tuple(q for section in SECTIONS.values() for q in section) if review
                 else SECTIONS.get(result["requested_section"], CORE_QUESTIONS))
    result["groups"] = [{"group": group, "total": len(ids), "answered": sum(q in covered for q in ids),
                         "skipped": sum(q in result["skipped"] and q not in covered for q in ids),
                         "done": all(q in covered or q in result["skipped"] for q in ids)}
                        for group, ids in PROFILE_GROUPS]
    open_groups = [g["group"] for g in result["groups"] if not g["done"]]
    result["current_group"] = next(iter(open_groups), None)
    result["next_group"] = next(iter(open_groups[1:]), None)
    # A sitting is one group: once it is done the interview stops for review and apply (legacy rows: current group).
    result["sitting_group"] = result["sitting_group"] or result["current_group"]
    sitting = dict(PROFILE_GROUPS).get(result["sitting_group"], ())
    result["sitting_done"] = result["sitting_group"] not in open_groups
    result["sitting_fresh"] = bool(sitting) and not any(
        q in result["asked"] or q in result["skipped"] or result["answers"].get(q, {}).get("source") == "user"
        for q in sitting)
    order = sitting if result["requested_section"] == "profile" else questions
    result["next_question"] = None if review else next(
        (q for q in order if q not in covered and q not in result["skipped"]), None)
    def counts(ids):
        return {**{key: sum(q in ids for q in result[key]) for key in ("asked", "answers", "skipped", "covered")},
                "total": len(ids)}
    result["counts"] = counts(questions)
    result["sections"] = {section: counts(ids) for section, ids in SECTIONS.items()}
    return result


def state(ledger):
    return _view((ledger.get("action", "pa:setup") or {}).get("fields", {}))


def _save(ledger, status, **fields):
    return _view(ledger.put("action", "pa:setup", {**fields, "status": status, "updated_at": now()},
                            action_type="setup", status=status)["fields"])


def _section(section):
    if section not in SECTIONS:
        raise ValueError("unknown setup section")


def request(ledger, section="core", *, active_chat=None):
    """Request setup again; keeps earlier answers for the saved-answer review.

    `active_chat` reserves the chat /pa setup was said in; its next human turn binds."""
    if section is not None:  # None is the command's explicit review mode.
        _section(section)
    prior = state(ledger)
    status = "in_progress" if prior["status"] in {"in_progress", "proposed"} else "requested"
    sitting = {"sitting_group": prior["current_group"]} if section == "profile" else {}  # The first group not done.
    return _save(ledger, status, requested_section=section,
                 requested_mode="review" if section is None else None,
                 active_platform=None, active_sender_id=None, active_chat=active_chat, proposal={"writes": []}, **sitting)


def continue_here(ledger, active_chat=None):
    """Move active setup to `active_chat` (or the next human turn); section, answers and proposal stay."""
    return _save(ledger, state(ledger)["status"], active_platform=None, active_sender_id=None, active_chat=active_chat)


def start(ledger, section=None, *, active_platform=None, active_sender_id=None, active_chat=None):
    if section is not None:
        _section(section)
    prior = state(ledger)
    if prior["status"] == "proposed" and section is not None and section != prior["requested_section"]:
        raise ValueError("A setup review is waiting: apply or change it before starting another section.")
    if section == "profile" and prior["current_group"] is None and prior["status"] != "proposed":
        # Matches the /pa setup grill guard; review uses request(); a waiting last-group review still gets applied.
        raise ValueError("Your profile is complete. Use /pa setup review to change an answer.")
    # Only the hook passes a binding; the skill's plain start keeps the chat it is in.
    binding = ({"active_platform": active_platform, "active_sender_id": active_sender_id, "active_chat": active_chat}
               if active_platform is not None else {})
    reset = not binding and section is not None and prior["status"] not in {"requested", "in_progress", "proposed"}
    if reset:
        # A new interview started from chat (e.g. "grill me" after setup finished) must not stay bound to the
        # older setup's chat; the hook binds the next human turn. An active setup keeps its binding (#32).
        binding = {"active_platform": None, "active_sender_id": None, "active_chat": None}
    extra = {"requested_mode": None} if section is not None else {}  # An explicit section is an interview, not a review.
    stored = (ledger.get("action", "pa:setup") or {}).get("fields", {})
    if section == "profile" and (reset or prior["requested_section"] != "profile" or not stored.get("sitting_group")):
        extra["sitting_group"] = prior["current_group"]  # A new sitting starts at the first group not done.
    return _save(ledger, prior["status"] if prior["status"] == "proposed" else "in_progress",
                 requested_section=prior["requested_section"] if section is None else section, **binding, **extra)


def record(ledger, answers=None, skipped=None, asked=None, consent=None):
    if consent is not None and consent not in ("granted", "declined"):
        raise ValueError("consent must be granted or declined")
    answers, skipped, asked = answers or {}, skipped or [], asked or []
    questions = tuple(q for section in SECTIONS.values() for q in section)
    unknown = sorted(str(k) for k in (set(answers) | set(skipped) | set(asked)) - set(questions))
    if unknown:  # Name the valid IDs so a model can re-record every discovered fact in one retry.
        raise ValueError(f"unknown setup question {', '.join(unknown)[:120]}; use only: {', '.join(questions)}")
    normalized = {}
    for qid, answer in answers.items():
        if not isinstance(answer, dict) or answer.get("source") not in {"user", "discovered"} or not isinstance(answer.get("text"), str):
            raise ValueError("answer requires text and user/discovered source")
        normalized[qid] = {"text": answer["text"][:300], "source": answer["source"]}
    stored = (ledger.get("action", "pa:setup") or {}).get("fields", {})
    prior = {**_view(stored), **stored}
    merged = {k: v for k, v in {**prior["answers"], **normalized}.items() if k not in skipped}
    skipped = list(dict.fromkeys(q for q in prior["skipped"] + skipped if q not in normalized or q in skipped))
    completed = prior["status"] in {"applied", "checked"}
    result = _save(ledger, prior["status"] if completed else "in_progress", answers=merged, skipped=skipped,
                 pending_changes=prior["pending_changes"] or (completed and (merged != prior["answers"] or skipped != prior["skipped"])),
                 asked=list(dict.fromkeys(prior["asked"] + asked)), proposal={"writes": []},
                 look_around_consent=prior["look_around_consent"] if consent is None else consent)
    if completed and result["pending_changes"]:
        result["next_step"] = ("Saved. Setup is still in place; this setup change is not in your files yet. "
                               "Include it in the next review (/pa setup review), then propose and apply.")
    return result


def _items(items, key):
    if not isinstance(items, list):
        raise ValueError("setup items must be a list")
    for item in items:
        if not isinstance(item, dict) or set(item) != {"target", key} or item["target"] not in TARGETS or not isinstance(item[key], str) or not item[key].strip():
            raise ValueError("invalid setup item")
    return items


def propose(ledger, writes, draft=False):
    """Save the review proposal; `draft` saves deeper-answer summaries and keeps the interview going."""
    saved = {"writes": _items(writes, "summary")}
    if draft is not False:
        current = state(ledger)
        if draft is not True or current["status"] not in {"requested", "in_progress"}:
            raise ValueError("a setup draft needs draft true and an active interview")
        return _save(ledger, current["status"], proposal_draft=saved)
    return _save(ledger, "proposed", proposal=saved, proposal_draft=saved, requested_mode=None)


READBACK_MAX_BYTES = 2 * 1024 * 1024


def _readback(root, item):
    target = item["target"]
    try:
        legacy._validate_root_components(root, "profile")
        allowed = root
        if target == "user_memory":
            path = root / "memories/USER.md"
        elif target == "soul_section":
            path = root / "SOUL.md"
        elif target == "manual_skill":
            allowed = root / "skills"
            if "path" in item:
                path = Path(item["path"])
                if not path.is_absolute():
                    path = root / path
            else:
                skill = item.get("skill")
                if not isinstance(skill, str) or not skill or Path(skill).name != skill or skill in {".", ".."}:
                    raise ValueError("a skill name or path is required")
                matches = [p for p in allowed.rglob("SKILL.md") if p.parent.name == skill]
                if len(matches) != 1:
                    raise ValueError("skill must have exactly one match")
                path = matches[0]
        else:  # Context files are explicitly selected outside the profile as well.
            path = Path(item.get("path", ""))
            if not path.is_absolute():
                raise ValueError("an absolute path is required")
            allowed = path.parent.resolve(strict=True)
            path = allowed / path.name
        path.relative_to(allowed)
        path = path.resolve(strict=True)
        path.relative_to(allowed)
        if not path.is_file():
            raise ValueError("a regular file is required")
        if target == "manual_skill" and path.name != "SKILL.md":
            raise ValueError("the manual readback must be its SKILL.md")
        if path.stat().st_size > READBACK_MAX_BYTES:  # Setup files are small; never load a huge file.
            raise ValueError("file is too large for a setup readback")
        content = path.read_bytes()
        if target == "user_memory" and not content.strip():
            raise ValueError("file must be non-empty")
        if target == "soul_section":
            start, end = b"<!-- personal-assistant:start -->", b"<!-- personal-assistant:end -->"
            first = content.find(start)
            if content.count(start) != 1 or content.count(end) != 1 or content.find(end) < first + len(start):
                raise ValueError("exactly one ordered PA marker pair is required")
            content = content[first:content.find(end) + len(end)]
        return {"target": target, "sha256": hashlib.sha256(content).hexdigest(),
                "path": str(path), "bytes": len(content)}
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError(f"{target}: {exc}") from None


def applied(ledger, readbacks, session_id=None):
    current = state(ledger)
    if current["status"] != "proposed":
        raise ValueError("a current setup proposal is required")
    if not isinstance(readbacks, list):
        raise ValueError("setup readbacks must be a list")
    for item in readbacks:
        if not isinstance(item, dict) or not isinstance(item.get("target"), str) or item["target"] not in FILE_TARGETS:
            raise ValueError("invalid setup readback target")
    expected = {item["target"] for item in current["proposal"]["writes"]} & FILE_TARGETS
    if {item["target"] for item in readbacks} != expected:
        raise ValueError("readbacks must match proposed file targets")
    readbacks = [_readback(ledger.root, item) for item in readbacks]
    return _save(ledger, "applied", applied=readbacks, requested_mode=None,
                 applied_session_id=session_id, fresh_check=(current["fresh_check"] if current["requested_section"] == "profile"
                                                            else {"status": "pending", "section": current["requested_section"]}),
                 pending_changes=False)


def fresh_check(ledger, status, session_id=None):
    if status not in {"passed", "failed"}:
        raise ValueError("invalid fresh-check status")
    current = state(ledger)
    if current["status"] == "checked":
        raise ValueError("fresh check already passed")
    pending = current["fresh_check"].get("status") in {"pending", "failed"}
    if current["status"] in {"requested", "in_progress", "proposed"} and current["fresh_check"].get("status"):
        raise ValueError("setup was reopened (new review or proposal); propose and apply again before the fresh check")
    if current["status"] != "applied":
        raise ValueError("no fresh check is pending; apply setup first")
    if not pending:
        raise ValueError("no fresh check is pending")
    if not session_id or session_id == current["applied_session_id"]:
        raise ValueError("the fresh check must run in a new session (/new), not the session that applied setup")
    failed_sessions = current["fresh_check"].get("failed_sessions", [])
    if session_id in failed_sessions:
        raise ValueError("fresh check retry needs a new session (/new)")
    if status == "failed":
        failed_sessions = list(dict.fromkeys(failed_sessions + [session_id]))[-5:]
    return _save(ledger, "checked" if status == "passed" else "applied",
                 fresh_check={"status": status, "at": now(), "failed_sessions": failed_sessions,
                              **{k: v for k, v in current["fresh_check"].items() if k == "section"}})


def pause(ledger):
    return _save(ledger, "paused")


def decline(ledger):
    return _save(ledger, "declined")


def mark_offered(ledger, at=None, *, _current=None):
    prior = state(ledger) if _current is None else _current
    return _save(ledger, "offered", offer_shown_at=at or now()) if prior["status"] == "not_started" else prior


def offer_turn(ledger, current, kwargs, history):
    """Confirm delivery on a later human turn; retry one failed generation."""
    conversation = [kwargs.get(k) or "" for k in ("session_id", "platform", "sender_id")]
    pending = current.get("offer_pending_at")
    if pending:
        if conversation != current.get("offer_conversation"):
            return False
        turn = kwargs.get("turn_id")
        if (turn and turn == current.get("offer_turn_id")) or (not turn and kwargs.get("is_first_turn")):
            return False
        for m in history[current.get("offer_history_size", 0):]:
            if (not isinstance(m, dict) or m.get("role") != "assistant"
                    or m.get("tool_calls") or m.get("display_kind")):
                continue
            content = m.get("content")
            if isinstance(content, list):
                content = "\n".join(p["text"] for p in content if isinstance(p, dict)
                                    and p.get("type") in {"text", "output_text"}
                                    and isinstance(p.get("text"), str))
            if isinstance(content, str) and "/pa setup" in content:
                mark_offered(ledger, _current=current)
                return False
        if current.get("offer_attempts", 1) >= 2:
            return False
    elif not kwargs.get("is_first_turn"):
        return False
    _save(ledger, "not_started", offer_pending_at=now(), offer_conversation=conversation,
          offer_turn_id=kwargs.get("turn_id"), offer_history_size=len(history),
          offer_attempts=current.get("offer_attempts", 0) + 1)
    return True
