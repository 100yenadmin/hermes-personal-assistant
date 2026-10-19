"""Hermes loads a native plugin under its own package name, so package modules must not import
`personal_assistant` by its top-level name (the observer did, and every offer ack failed in a gateway)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "personal_assistant"

LOADER = """
import importlib, importlib.util, sys
spec = importlib.util.spec_from_file_location("hermes_native_pa", sys.argv[1] + "/__init__.py",
                                              submodule_search_locations=[sys.argv[1]])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
failed = []
for name in sys.argv[2:]:
    try:
        importlib.import_module("hermes_native_pa." + name)
    except Exception as exc:
        failed.append(f"{name}: {type(exc).__name__}: {exc}")
print("\\n".join(failed))
raise SystemExit(1 if failed else 0)
"""


def test_every_module_imports_under_a_native_package_name(tmp_path):
    names = sorted(p.stem for p in PACKAGE.glob("*.py") if p.stem not in {"__init__", "__main__"})
    # -I and a foreign cwd keep the repository off sys.path, as in a gateway process.
    result = subprocess.run([sys.executable, "-I", "-c", LOADER, str(PACKAGE), *names],
                            cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
