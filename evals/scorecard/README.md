# VA scorecard

Run `python -m evals.scorecard --version V --commit SHA --lab DIR --as-of YYYY-MM-DD --out DIR`, optionally repeating `--lab` and adding `--live FILE`. The JSON stores lab directory basenames only and names runs as `<lab basename>/<run folder>` in test run IDs, exclusions and fact errors; local paths are omitted. The Markdown omits paths and URLs. Only completed runs pinned to the full PA commit count (PA's `plugin-refs.json` entry is found by name, then by source, then first position; hand-built lab homes list heartbeat2 first), and partial checks never establish a full-area pass. Live task dates are ISO dates: the observed window runs from the first start to the earlier of the last due date and `--as-of` (the export has no completion timestamp; tasks starting after `--as-of` are ignored), counting both endpoint days, and pending tasks count as failures only after their due date. Missing owner baseline/day-30 records leave day-30 unproven; first-pass task types count distinctly. The command reports failures with exit 0 and rejects bad input with exit 2. Synthetic tests prove scoring rules, not real lab quality, publication, runtime activation or customer parity. Related issue: #48.

Catalogue tests may declare `covers`, a list of zero-based indices into their area's `duties`; it defaults to `[]` for every existing test. Only tests in state `pass` cover a duty. Each JSON area includes `uncovered_duties`, and the Markdown's "Unexercised duties" section lists those duties for every area, including areas with passing full tests. The headline always includes both passing and failing partial-check counts (`· N partial checks failing`, even at zero), and never a parity percentage.

Fail-closed input rules:
- A counted run needs a non-empty `overall` check map whose values are all `true`, and `all_pass` and the judge's `pass` must be the boolean `true`.
- Lab factual errors count from `fabricated_confirmations` and, where a fixture writes it, `factual_errors` (a number or a list).
- A run's identity is its scenario, `run_id` and `start` from `run.json`, so a renamed or copied folder is a duplicate. A `run.json` without `start` is excluded as `malformed_run`.
- Live task ids must be unique per owner, text fields must not be blank, and every fact needs a non-empty `item` and `source`, internal facts included.
- Tasks starting after `--as-of` count for neither real work, facts nor the day-30 cohort.
- An area's parity stays `unproven` while any of its duties lacks a passing lab test.
- A damaged copy of a run never hides a valid one, because only counted runs reserve a run identity.
- Markdown neutralises HTML, URLs (including protocol-relative and `mailto:`-style ones), link and image syntax, and local paths in values and JSON keys.
