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


def test_watcher_turn_never_ends_the_watch():
    wake = _wake_section()
    # A respond with outcome done ends an HB2 watcher wake, so blocked checks use no_change.
    assert 'Never use `"outcome":"done"` on a watcher wake: it ends the watch.' in wake
    assert wake.count('{"action":"respond","outcome":"no_change","notify":false}') == 2
    watcher = wake.split("For a watcher wake", 1)[1].split("For flight_change", 1)[0]
    assert '"outcome":"done"' not in watcher.replace('Never use `"outcome":"done"`', "")


def test_sendable_watcher_turn_posts_the_offer_as_final_reply():
    wake = _wake_section()
    assert '{"action":"respond","outcome":"progress","notify":true,"summary":"Trip offer sent."}' in wake
    assert "then make the ONE short offer your final reply. Write no text alongside tool calls." in wake


def test_handed_back_watch_report_gets_the_offer_in_the_owner_turn():
    wake = _wake_section()
    assert 'When HeartBeat hands back a report titled `Trip "<id>": watch` in an owner turn' in wake
    assert "record `outcome=offered` and make the offer in that reply" in wake
    assert "call no `pulse` respond" in wake
    router = (ROOT / "skills/personal-assistant/SKILL.md").read_text()
    assert 'When HeartBeat hands back a report titled `Trip "<id>": watch`, load' in router


def test_arrival_flow_is_scoped_to_the_arrival_wake():
    wake = _wake_section()
    assert 'For the arrival wake (titled `Trip "<id>": arrival plan`), get trip facts from' in wake
    assert "For a message starting with HeartBeat wake text naming this skill" not in wake
