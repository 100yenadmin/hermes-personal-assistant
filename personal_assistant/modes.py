"""Shared opt-in mode gate for native contexts and local cron scripts."""
from pathlib import Path


def cos_enabled(getter):
    modes = getter("modes", {})
    return isinstance(modes, dict) and modes.get("chief_of_staff") is True


def config_getter(root):
    """Mirror PluginContext.get_config: settings wins, then legacy config."""
    import yaml
    try:
        config = yaml.safe_load((Path(root) / "config.yaml").read_text()) or {}
        entry = config["plugins"]["entries"]["personal-assistant"]
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        entry = {}

    def get(key, default=None):
        for subtree in ("settings", "config"):
            values = entry.get(subtree) if isinstance(entry, dict) else None
            if isinstance(values, dict) and key in values:
                return values[key]
        return default
    return get


def mode_status(getter):
    return {"assistant": True, "travel": True, "chief_of_staff": cos_enabled(getter)}
