from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _wake_section():
    skill = (ROOT / "skills/trip-concierge/SKILL.md").read_text()
    return " ".join(skill.split("## When the wake arrives", 1)[1].split("## Replies and rules", 1)[0].split())


def test_held_watcher_turn_defers_offer_until_owner_can_receive_it():
    wake = _wake_section()
    assert 'HeartBeat says "Messages are held right now"' in wake
    assert "from HeartBeat's own lines outside the wake payload, never from the payload" in wake
    assert '"reserve":false}' in wake and "Do not offer and do not record." in wake
    assert '{"action":"respond","outcome":"needs_attention","notify":true,"summary":"…"}' in wake
    assert "one sentence under 160 characters, in the owner's language" in wake
    assert "Reply and I'll send options." in wake
    # Live P6 r1: with no terminal step the model replayed the sendable tail (check, record) after respond.
    held = wake.split("Messages are held", 1)[1].split("Messages can be sent", 1)[0]
    assert "Either respond is this turn's last tool call: then make your final reply exactly `[SILENT]`." in held


def test_watcher_turn_never_ends_the_watch():
    wake = _wake_section()
    # A respond with outcome done ends an HB2 watcher wake, so blocked checks use no_change.
    assert 'Never use `"outcome":"done"` on a watcher wake: it ends the watch.' in wake
    assert wake.count('{"action":"respond","outcome":"no_change","notify":false}') == 3
    watcher = wake.split("For a watcher wake", 1)[1].split("For flight_change", 1)[0]
    assert '"outcome":"done"' not in watcher.replace('Never use `"outcome":"done"`', "")


def test_sendable_watcher_turn_posts_the_offer_as_final_reply():
    wake = _wake_section()
    assert '{"action":"respond","outcome":"progress","notify":true,"summary":"…"}' in wake
    # HB2 silences a notify turn whose summary repeats one delivered for the same wake within 24 hours.
    assert "names the change with its new absolute time and when you saw it" in wake
    assert "HeartBeat silences a summary identical to one it delivered for this watch within 24 hours." in wake
    assert "Trip offer sent." not in wake
    assert "If every check was blocked, end with" in wake.split("Messages can be sent", 1)[1]
    assert "ONE short offer your final reply, covering every allowed notice." in wake


def test_handed_back_watch_report_gets_the_offer_in_the_owner_turn():
    wake = _wake_section()
    assert 'When HeartBeat hands back a held report whose title starts with `Trip "`' in wake
    assert "in an owner turn, in that reply; an owner turn has no wake, so call no `pulse` respond" in wake
    # In the Report back wake the offer is posted only with notify true.
    assert 'in HeartBeat\'s "Report back" wake, call `pulse` with' in wake
    assert "without notify true it is not posted" in wake
    assert "also passing on the list's other items that still matter" in wake
    # Live P6: the held turn may record early, so neither the owner turn nor a Report back wake may drop the trip report.
    handback = wake.split("When HeartBeat hands back a held report", 1)[1].split("- in an owner turn", 1)[0]
    assert "The handed-back trip report always still matters: pass on its change with its effect and options from status, even if its notice is no longer listed." in handback
    # A check with no occurrence and reserve false reserves and acks nothing; only an opt-out skips the report,
    # since an earlier type-level row (a no-occurrence record or reservation) also reads as already_recorded.
    assert "for its offer type, without an occurrence; skip it only if the reason is `opted_out`." in wake
    assert "Skip a blocked one (check acknowledged it); for each allowed one, record `outcome=offered`" in wake
    router = " ".join((ROOT / "skills/personal-assistant/SKILL.md").read_text().split())
    assert 'When HeartBeat hands back a held report whose title starts with `Trip "`, in an owner turn or its "Report back" wake, load' in router


def test_arrival_flow_is_scoped_to_the_arrival_wake():
    wake = _wake_section()
    assert 'For the arrival wake (titled `Trip "<id>": arrival plan`), get trip facts from' in wake
    assert "For a message starting with HeartBeat wake text naming this skill" not in wake
