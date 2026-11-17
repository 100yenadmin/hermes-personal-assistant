from pathlib import Path


def test_held_watcher_turn_defers_offer_until_owner_can_receive_it():
    skill = (Path(__file__).resolve().parents[1] / "skills/trip-concierge/SKILL.md").read_text()
    wake = " ".join(skill.split("## When the wake arrives", 1)[1].split())
    assert 'If the wake text says "Messages are held right now"' in wake
    assert 'Do not offer and do not record. Run each check with `"reserve": false`' in wake
    assert '{"action":"respond","outcome":"needs_attention","notify":true,"summary":"..."}' in wake
    assert "one plain sentence under 160 characters" in wake
    assert 'If every check was blocked, respond with `"outcome":"done"` and `"notify":false` instead.' in wake
    assert "Unrecorded notices stay in status. On the next turn that can reach the owner" in wake
    assert "read status and make the offer for each notice still listed, as above." in wake
