"""Operator CLI. Dry runs only read and validate local YAML."""
import argparse
import json
import sys
from .scenario import CATALOG


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    home = sub.add_parser("home")
    for key in ("hermes", "python", "out", "pa", "hb2"):
        home.add_argument("--" + key, required=True)
    home.add_argument("--fish")
    home.add_argument("--browser", choices=("local", "browserbase"), default="local")
    run = sub.add_parser("run")
    run.add_argument("--scenario", default="all", help="all, cos, or an exact scenario id")
    run.add_argument("--scenarios", default=str(CATALOG))
    run.add_argument("--runs", type=int, default=1)
    run.add_argument("--workers", type=int, default=3)
    run.add_argument("--python", default=sys.executable)
    run.add_argument("--home-template")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--keep-home", action="store_true")
    one = sub.add_parser("run-one", help=argparse.SUPPRESS)
    for p in (run, one):
        p.add_argument("--hermes", required=p is one)
        p.add_argument("--out", required=p is one)
        p.add_argument("--judge", choices=("codex", "none"), default="codex")
    report = sub.add_parser("report")
    report.add_argument("--out", required=True)
    rejudge = sub.add_parser("rejudge", help="Recompute checks and judgments from saved runs")
    rejudge.add_argument("--out", required=True)
    rejudge.add_argument("--run", action="append")
    rejudge.add_argument("--judge", choices=("codex", "none"), default="codex")
    rejudge.add_argument("--workers", type=int, default=3)
    args = parser.parse_args(argv)
    if args.command == "home":
        from .home import build
        result = build(args)
    elif args.command == "report":
        from .report import render
        result = render(args.out)
    elif args.command == "rejudge":
        from .rejudge import rejudge
        result = rejudge(args)
    else:
        from .runner import wave, one as run_one
        result = wave(args) if args.command == "run" else run_one(args)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if isinstance(result, dict) and result.get("status") in ("error", "timeout") else 0


if __name__ == "__main__":
    raise SystemExit(main())
