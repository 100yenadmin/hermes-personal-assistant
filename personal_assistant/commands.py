"""In-session command entry; the next human message starts the agent conversation."""
from . import setup
from .state import Ledger

USAGE = "Use /pa setup, /pa setup review, /pa status, or /pa help."
READY = "Setup is ready. Send me any message and I'll start — one question at a time, about 8 in all. Say pause any time."


def make_pa_command(root):
    def handler(raw_args):
        try:
            parts = raw_args.split()
            if parts == ["status"]:
                current = setup.state(Ledger(root))
                return f"Setup: {current['status']}. Next question: {current['next_question'] or 'none'}. Answered {current['counts']['answers']} of {len(setup.CORE_QUESTIONS)}."
            if parts and parts[0] == "setup" and len(parts) <= 2:
                section = parts[1] if len(parts) == 2 else "core"
                if section not in {*setup.SECTIONS, "review"}:
                    return "Unknown setup section. Use /pa setup for core setup, or /pa setup review."
                setup.request(Ledger(root), None if section == "review" else section)
                return READY
            return USAGE
        except Exception:
            return "Sorry, setup is unavailable right now. Please try again."
    return handler
