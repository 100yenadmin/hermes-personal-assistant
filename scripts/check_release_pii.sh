#!/usr/bin/env bash
# Scan the reviewed staging tree, including every UTF-8 text format.
# This is a fail-closed heuristic, not a universal PII detector.
set -euo pipefail
STAGE="${1:?staged package dir required}"
python3 - "$STAGE" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
forbidden = {"clients.json", "location.json", "daily_ops.config.json", "daily_ops.state.json"}
reserved = {"example.com", "example.org", "example.net", "invalid", "test"}
email = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
errors = []
for path in sorted(root.rglob("*")):
    if not path.is_file():
        continue
    rel = path.relative_to(root).as_posix()
    if path.is_symlink():
        errors.append(f"BLOCKED symlink in release: {rel}")
        continue
    if path.name in forbidden:
        errors.append(f"BLOCKED runtime data file in release: {rel}")
        continue
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        continue  # binary is not scanned by this text heuristic
    for match in email.finditer(text):
        domain = match.group(1).lower().rstrip(".")
        if domain not in reserved and not domain.endswith(".invalid") and not domain.endswith(".test"):
            errors.append(f"BLOCKED possible customer address in release file: {rel}")
            break
if errors:
    print("\n".join(errors), file=sys.stderr)
    print("release scan FAILED — packaging blocked (fail-closed)", file=sys.stderr)
    raise SystemExit(1)
print("release scan clean")
PY
