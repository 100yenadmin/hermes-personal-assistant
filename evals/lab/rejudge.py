"""Recompute judgments using only saved run artifacts and the optional Codex judge."""
import concurrent.futures
import shutil
from pathlib import Path
from . import checks, judge, report
from .common import read, write


def rejudge(args):
    if args.workers < 1:
        raise ValueError("workers: must be positive")
    out = Path(args.out)
    folders = {path.parent.name: path.parent for path in sorted(out.glob("*/run.json"))}
    selected = set(args.run) if args.run else set(folders)
    missing = selected - folders.keys()
    if missing:
        raise ValueError("unknown runs: " + ", ".join(sorted(missing)))
    completed, incomplete, skipped = [], [], []
    for name, root in folders.items():
        if name not in selected:
            continue
        meta = read(root / "run.json")
        if meta.get("status") == "skipped":
            skipped.append(name)
        elif "end" not in meta:
            incomplete.append(name)
        else:
            completed.append(root)

    def replace(root, name, value):
        path, previous = root / f"{name}.json", root / f"{name}.prev.json"
        if path.exists() and not previous.exists():
            shutil.copyfile(path, previous)
        write(path, value)

    kept = {}

    def job(root):
        # The run's own result: checks.prev.json once a rejudge has replaced checks.json.
        original = read(root / "checks.prev.json", None) or read(root / "checks.json", None)
        result = checks.evaluate(root, read(root / "scenario.json"), previous=original)
        names = sorted({n for s in result["steps"] for n in s.get("kept_from_run", [])})
        if names:
            kept[root.name] = names
        replace(root, "checks", result)
        try:
            verdict = judge.run(root) if args.judge != "none" else {"skipped": True, "reason": "--judge none"}
        except Exception as exc:
            verdict = {"pass": False, "error": type(exc).__name__}
        replace(root, "judge", verdict)
        return root.name

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        rejudged = list(pool.map(job, completed))
    report.render(out)
    # Checks kept from the run's own result because its home was removed (#150).
    return {"rejudged": rejudged, "incomplete": incomplete, "skipped": skipped, "kept_from_run": dict(sorted(kept.items()))}
