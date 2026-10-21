"""Portable Markdown scorecards without local paths or external links."""
import re

from ._portable import scrub_paths


def _text(value):
    text = str(value)
    text = re.sub(r"(?:[A-Za-z][A-Za-z0-9+.-]*://|www\.)\S+", "[URL omitted]", text, flags=re.I)
    text = scrub_paths(text)
    return text.replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def headline(card):
    counts = card["counts"]["lab"]
    partial = card["counts"]["partial"]
    return (f"Lab: {counts['pass']} pass · {partial['pass']} partial checks passing · "
            f"{partial['fail']} partial checks failing · "
            f"{counts['fail']} fail · {counts['unproven']} unproven · "
            f"{counts['not_exercised']} not exercised")


def markdown(card):
    lines = [f"# PA {_text(card['version'])} VA scorecard", "",
             f"Commit: {_text(card['commit'])} · As of: {_text(card['as_of'])}", "", headline(card), "",
             "| Area | Lab | Partial checks | Real work | Facts | Parity | Closes in |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for area in card["areas"]:
        cells = [area["title"], area["lab"], area["partial"]["state"], area["real_work"]["state"],
                 area["facts"]["state"], area["parity"], area["closes_in"]]
        lines.append("| " + " | ".join(_text(c) for c in cells) + " |")
    lines += ["", "## Day-30", "", f"State: {card['day30']['state']}"]
    for owner, result in card["day30"]["owners"].items():
        detail = (f"; saving {result['saving']:.3f}; first-pass task types {result['types']}"
                  if "saving" in result else "")
        lines.append(f"- {_text(owner)}: {result['state']}{detail}")
    lines += ["", "## Excluded runs", "", f"Count: {len(card['excluded'])}"]
    for run in card["excluded"]:
        lines.append(f"- {_text(run['run'])} ({_text(run['scenario'])}): {_text(run['reason'])}")
    lines += ["", "## Unexercised duties"]
    for area in card["areas"]:
        lines += ["", f"### {_text(area['title'])}", ""]
        lines += [f"- {_text(duty)}" for duty in area["uncovered_duties"]]
    return "\n".join(lines) + "\n"
