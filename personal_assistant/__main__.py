"""JSON-in/JSON-out companion for Hermes script prechecks and portable exports."""
import argparse
import json
import os
from pathlib import Path
import sys

from .entry import dispatch
from .state import LedgerPermissionError

parser = argparse.ArgumentParser(description="Personal Assistant Plugin helper")
parser.add_argument("--profile-root", default=os.environ.get("HERMES_HOME"), help="Explicit active Hermes profile directory")
args = parser.parse_args()
if not args.profile_root:
    parser.error("--profile-root or HERMES_HOME is required; never guess a profile")
try:
    result = dispatch(Path(args.profile_root), json.load(sys.stdin))
    print(json.dumps(result, ensure_ascii=False))
except Exception as exc:
    # Preserve the ledger's path/permission diagnostics; mask other exception text.
    error = {"error": "RuntimeError" if isinstance(exc, LedgerPermissionError) else type(exc).__name__, "recovery": "Check operation inputs and profile access; inspect provider safely."}
    if isinstance(exc, LedgerPermissionError):
        error["message"] = str(exc)
    print(json.dumps(error))
    sys.exit(1)
