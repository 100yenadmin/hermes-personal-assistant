"""Stable invocation-path handling for the isolated native check."""
from pathlib import Path


_PATH_ARGUMENTS = ("hermes", "ics", "guide", "receipt", "archive")


def resolve_cli_paths(args, cwd=None):
    """Resolve supplied path arguments before the check changes directory."""
    base = Path.cwd() if cwd is None else Path(cwd)
    for name in _PATH_ARGUMENTS:
        value = getattr(args, name, None)
        if value:
            path = Path(value)
            if not path.is_absolute():
                path = base / path
            setattr(args, name, str(path.resolve()))
    return args
