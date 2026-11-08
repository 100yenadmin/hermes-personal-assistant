"""Test-only stand-in for Hermes's ``hermes_constants`` when Hermes itself is not installed.

Package and archive CI install only PA's requirements, so ``register()``'s public
``get_hermes_home()`` import has no Hermes to resolve against there. The stand-in
follows the accessor's documented order for these tests: ``HERMES_HOME``, then
``~/.hermes``. With Hermes installed, the real module is used and this does nothing.
"""
import importlib.util
import os
from pathlib import Path
import sys
import types

if importlib.util.find_spec("hermes_constants") is None:
    _stub = types.ModuleType("hermes_constants")

    def get_hermes_home() -> Path:
        value = os.environ.get("HERMES_HOME", "").strip()
        return Path(os.path.expanduser(value)) if value else Path.home() / ".hermes"

    _stub.get_hermes_home = get_hermes_home
    _stub.PA_TEST_STAND_IN = True  # tests that load a real Hermes source drop it first
    sys.modules["hermes_constants"] = _stub
