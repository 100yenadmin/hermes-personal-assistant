"""In-session command entry; the next human message starts the agent conversation."""
from . import setup
from .state import Ledger
from .modes import config_getter, cos_enabled

USAGE = "Use /pa setup, /pa setup chief-of-staff, /pa setup review, /pa status, /pa mode, /pa mode chief-of-staff on|off, or /pa help."
READY = "Setup is ready. Send me any message and I'll start — one question at a time, about 8 in all. Say pause any time."


def make_pa_command(root, get_config=None, set_config=None):
    get_config = get_config or config_getter(root)

    def modes_text():
        return "Assistant: on. Travel: on. Chief of Staff: " + ("on" if cos_enabled(get_config) else "off") + "."

    def handler(raw_args):
        try:
            parts = raw_args.split()
            if parts == ["mode"]:
                return modes_text()
            if len(parts) == 3 and parts[:2] == ["mode", "chief-of-staff"] and parts[2] in {"on", "off"}:
                from .automation_workflow import native_profile_guard, stop_cos
                ledger = Ledger(root)
                native_profile_guard(ledger)
                if not callable(set_config):
                    raise ValueError("native mode settings are unavailable")
                modes = get_config("modes", {})
                modes = dict(modes) if isinstance(modes, dict) else {}
                modes["chief_of_staff"] = parts[2] == "on"
                set_config("modes", modes)
                if parts[2] == "off":
                    stopped = stop_cos(ledger)
                    return (f"Chief of Staff: off. Paused and removed {stopped['jobs']} CoS jobs; "
                            f"dismissed {stopped['suggestions']} pending suggestions; paused {stopped['rules']} rules. "
                            "CoS schedules and follow-ups have stopped now. "
                            "The CoS skills disappear after hermes gateway restart and a new session.")
                return "Chief of Staff: on. Run hermes gateway restart to reload plugins, then start a new session for the CoS skills."
            if parts == ["status"]:
                current = setup.state(Ledger(root))
                return f"Setup: {current['status']}. Next question: {current['next_question'] or 'none'}. Answered {current['counts']['answers']} of {current['counts']['total']}. " + modes_text() + (" Changes not yet applied." if current['pending_changes'] else "")
            if parts and parts[0] == "setup":
                from .onboarding_hook import command_chat_key
                here = command_chat_key()  # Setup moves to the chat the command was said in.
            if parts == ["setup"] and setup.state(Ledger(root))["status"] in {"requested", "in_progress", "proposed"}:
                setup.continue_here(Ledger(root), active_chat=here)  # Keeps the section and progress; only the chat moves.
                return "Setup continues here. Send me any message and I'll pick up where we left off."
            if parts and parts[0] == "setup" and len(parts) <= 2:
                section = parts[1] if len(parts) == 2 else "core"
                section = "chief_of_staff" if section == "chief-of-staff" else section
                if section not in {*setup.SECTIONS, "review"}:
                    return "Unknown setup section. Use /pa setup for core setup, /pa setup chief-of-staff, or /pa setup review."
                if section == "chief_of_staff" and not cos_enabled(get_config):
                    return "Chief of Staff is off. Use /pa mode chief-of-staff on, then hermes gateway restart and a new session; run /pa setup chief-of-staff there."
                setup.request(Ledger(root), None if section == "review" else section, active_chat=here)
                if section == "chief_of_staff":
                    return f"Chief of Staff setup is ready. Send me any message and I'll start — one question at a time, {len(setup.CHIEF_OF_STAFF_QUESTIONS)} in all. Say pause any time."
                return READY
            return USAGE
        except ValueError as exc:
            return str(exc) if parts and parts[0] == "mode" else "Sorry, setup is unavailable right now. Please try again."
        except Exception:
            return "Sorry, setup is unavailable right now. Please try again."
    return handler
