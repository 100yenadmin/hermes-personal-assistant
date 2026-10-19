"""Static report from immutable per-run artifacts, without external assets."""
import html
import re
import statistics
from pathlib import Path
from .checks import submit_events
from .common import read, lines, write


def render(out):
    root = Path(out)
    scenarios, capabilities, rows, skipped, incomplete = {}, {}, [], [], []
    for path in sorted(root.glob("*/run.json")):
        folder, run = path.parent, read(path)
        s, c, j = read(folder / "scenario.json"), read(folder / "checks.json", {}), read(folder / "judge.json", {})
        if run.get("status") == "skipped":
            skipped.append({"run": folder.name, "reason": run["reason"]})
            continue
        unfinished = "end" not in run
        status = "incomplete" if unfinished else run.get("status")
        if unfinished:
            incomplete.append({"run": folder.name, "reason": "run has no end"})
        hits = len(submit_events(folder))
        hard = bool(hits)
        judge_ok = j.get("pass") is True
        safe = not unfinished and status == "ok" and not hard and all(c.get("overall", {"missing": False}).values())
        passed = safe and c.get("all_pass", False) and judge_ok
        if not unfinished:
            scenarios.setdefault(s["id"], []).append(passed)
            for i, step in enumerate(s["steps"]):
                result = c.get("steps", [])
                capabilities.setdefault(step["capability"], []).append(safe and judge_ok and i < len(result) and result[i]["pass"])
        rows.append({"id": folder.name, "scenario": s["id"], "index": run.get("index", 1), "status": status, "pass": passed, "checks": c, "judge": j,
                     "capabilities": sorted({st["capability"] for st in s["steps"]}),
                     "tripwire_hits": hits, "duration": None if unfinished else run["end"] - run.get("start", 0),
                     "tokens": sum(v.get("session_total_tokens", 0) or 0 for v in run.get("usage", []))})
    rate = lambda values: {"passed": sum(values), "total": len(values), "pass_rate": sum(values) / len(values)}
    finished = [r for r in rows if r["status"] != "incomplete"]
    summary = {"scenarios": {k: rate(v) for k, v in scenarios.items()}, "capabilities": {k: rate(v) for k, v in capabilities.items()},
               "tripwire_hits": sum(r["tripwire_hits"] for r in rows), "fabricated_confirmations": sum(r["checks"].get("fabricated_confirmations", 0) for r in rows),
               "median_duration": statistics.median(r["duration"] for r in finished) if finished else None,
               "tokens": sum(r["tokens"] for r in finished), "skipped": skipped, "incomplete": incomplete, "runs": rows,
               "judge_policy": "--judge none is deterministic-only; not a judged pass", "catalog": [read(p.parent / "scenario.json")["id"] for p in sorted(root.glob("*/run.json"))]}
    for kind in ("scenarios", "capabilities"):
        for name, values in summary[kind].items():
            selected = [r for r in finished if (r["scenario"] == name if kind == "scenarios" else name in r["capabilities"])]
            observed = [r for r in rows if (r["scenario"] == name if kind == "scenarios" else name in r["capabilities"])]
            values.update(median_duration=statistics.median(r["duration"] for r in selected) if selected else None,
                          tokens=sum(r["tokens"] for r in selected), tripwire_hits=sum(r["tripwire_hits"] for r in observed),
                          fabricated_confirmations=sum(r["checks"].get("fabricated_confirmations", 0) for r in observed))
    write(root / "summary.json", summary)
    esc = lambda value: html.escape(re.sub(r"https?://[^\s\"<>]+", "[external URL omitted]", str(value)), quote=True)
    parts = ['<!doctype html><meta charset="utf-8"><title>PA Capability Lab</title><style>body{font:16px sans-serif;margin:2em}td,th{padding:.5em;border:1px solid #ccc}img{width:240px}.bar{width:200px;position:relative;background:#eee}.bar:after{content:"";position:absolute;left:80%;top:0;bottom:0;border-left:2px solid #222}.fill{background:#8bd}</style><h1>PA Capability Lab</h1><p>Bar marker: 80%. Judge-skipped runs show deterministic results only.</p><table><tr><th>Capability</th><th>Pass rate</th></tr>']
    for cap, values in summary["capabilities"].items():
        pct = 100 * values["pass_rate"]
        parts.append(f'<tr><td>{esc(cap)}</td><td><div class="bar"><div class="fill" style="width:{pct}%">{pct:.0f}%</div></div></td></tr>')
    parts.append('</table><h2>Scenario × run</h2><table>')
    indices = sorted({r["index"] for r in rows})
    parts.append('<tr><th>Scenario</th>' + ''.join(f'<th>Run {i}</th>' for i in indices) + '</tr>')
    for scenario in dict.fromkeys(r["scenario"] for r in rows):
        parts.append('<tr><td>' + esc(scenario) + '</td>')
        for i in indices:
            r = next((r for r in rows if r["scenario"] == scenario and r["index"] == i), None)
            label = "INCOMPLETE" if r and r["status"] == "incomplete" else "PASS" if r and r["pass"] else "FAIL"
            parts.append(f'<td><a href="#{esc(r["id"])}">{label}</a></td>' if r else '<td>—</td>')
        parts.append('</tr>')
    parts.append('</table>')
    for r in rows:
        parts.append(f'<details id="{esc(r["id"])}"><summary>{esc(r["id"])} ({esc(r["status"])})</summary><pre>{esc(r["checks"])}\n{esc(r["judge"])}</pre>')
        parts.append('<pre>' + esc(str(read(root / r["id"] / "transcript.json", []))[:4000]) + '</pre>')
        for p in sorted((root / r["id"]).glob("final_*.png")):
            link = esc(p.relative_to(root).as_posix())
            parts.append(f'<a href="{link}"><img src="{link}" alt="Final page"></a>')
        parts.append('</details>')
    parts.append('<h2>Skipped</h2><pre>' + esc(skipped) + '</pre>')
    parts.append('<h2>Incomplete</h2><pre>' + esc(incomplete) + '</pre>')
    (root / "report.html").write_text("\n".join(parts), encoding="utf-8")
    return summary
