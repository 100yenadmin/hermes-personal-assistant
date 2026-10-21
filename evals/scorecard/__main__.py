"""Write JSON and Markdown scorecards; failing evidence never gates the CLI."""
import argparse
import json
from pathlib import Path

from .build import build
from .render import headline, markdown


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--lab", required=True, action="append")
    parser.add_argument("--live", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        live = json.loads(args.live.read_text(encoding="utf-8")) if args.live else None
        card = build(args.version, args.commit, args.lab, live, as_of=args.as_of)
        text = markdown(card)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "scorecard.json").write_text(json.dumps(card, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (args.out / "scorecard.md").write_text(text, encoding="utf-8")
    except (ValueError, OSError, TypeError) as exc:
        parser.error(str(exc))
    print(headline(card))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
