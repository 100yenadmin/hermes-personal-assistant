"""Adapted from heartbeat2/tests/e2e/conftest.py at HB2 commit 3ed7a21."""
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items):
    for item in items:
        if HERE in item.path.parents:
            if not os.getenv("PA_E2E_HERMES"):
                item.add_marker(pytest.mark.skip(reason="set PA_E2E_HERMES to opt in"))
            elif item.get_closest_marker("timeout") is None:
                item.add_marker(pytest.mark.timeout(240, method="signal"))


@pytest.fixture
def rig(monkeypatch, request):
    monkeypatch.syspath_prepend(str(HERE))
    from loopback import install
    install(lambda obj, name, value: monkeypatch.setattr(obj, name, value))
    import tempfile
    parent = tempfile.mkdtemp(prefix="pa-parent-")
    monkeypatch.setenv("HOME", parent)
    monkeypatch.setenv("HERMES_HOME", parent + "/.hermes")
    sys.dont_write_bytecode = True
    pin = Path(os.environ["PA_E2E_HERMES"]).resolve()
    monkeypatch.syspath_prepend(str(pin))
    from harness import ConciergeRig
    instance = ConciergeRig(pin, **getattr(request, "param", {}))
    try:
        instance.start()
        yield instance
    finally:
        instance.close()
