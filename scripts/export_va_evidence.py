#!/usr/bin/env python3
"""Export short VA evidence from a profile root or its ledger copy, read-only."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from personal_assistant.evidence import dispatch
from personal_assistant.state import Ledger


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        ledger = Ledger(args.root.absolute(), read_only=True)
        if args.out and (args.out.resolve() == ledger.path.resolve() or
                         (args.out.exists() and ledger.path.exists() and args.out.samefile(ledger.path))):
            raise ValueError("output must not overwrite the ledger")
        result = dispatch(ledger, {"action": "export", "owner": args.owner})
        text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
