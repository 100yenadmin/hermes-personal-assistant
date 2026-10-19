# PA Capability Lab (#95)

The lab exercises real Hermes v0.22.2 and real public websites using gpt-6.1-sol,
low reasoning effort. Unit tests and `--dry-run` use no model or network.
Use a Hermes venv with the plugins' declared dependencies already installed.
The lab itself needs only the standard library and PyYAML.

Set `HERMES`, `PYTHON`, `PA`, `HB2`, and `LAB` to your runtime tree, venv Python,
plugin Git sources, and a new artifact directory. Set `PA_SHA` and `HB2_SHA` to
full immutable 40-character commits. Local Git paths are supported and converted
to file URLs. Never point the template at an ordinary live profile.

```sh
"$PYTHON" -m evals.lab home --hermes "$HERMES" --python "$PYTHON" \
  --out "$LAB/template" --pa "$PA@$PA_SHA" --hb2 "$HB2@$HB2_SHA"
"$PYTHON" -m evals.lab run --dry-run --scenario all
"$PYTHON" -m evals.lab run --hermes "$HERMES" --python "$PYTHON" \
  --home-template "$LAB/template" --scenario s01_seoul_tokyo_en \
  --runs 1 --workers 1 --out "$LAB/smoke"
"$PYTHON" -m evals.lab report --out "$LAB/smoke"
"$PYTHON" -m evals.lab run --hermes "$HERMES" --python "$PYTHON" \
  --home-template "$LAB/template" --scenario all --runs 3 --workers 3 --out "$LAB/wave"
"$PYTHON" -m evals.lab report --out "$LAB/wave"
```

Optional `home --fish source@SHA` installs Fish Audio for voice; the call simulator ships inside PA.
Browser tools appear only when Hermes finds Chromium: set `AGENT_BROWSER_EXECUTABLE_PATH` to a standalone
Chromium or Chrome for Testing binary (never a personal browser profile; agent-browser starts a fresh profile). Installation
uses the chosen Python, `--no-deps --no-enable`, then writes lab-only config.
It never runs Hermes from PATH, creates auth, registers jobs or starts a gateway.
Installer scan/dependency refusals are operator gates; no bypass is applied.

Read `report.html` for capability bars (80% marker), scenario/run results,
checks, judge notes, transcript excerpts and relative screenshot thumbnails.
`summary.json` preserves denominators, skips, duration and token counts.
The judge digest includes bounded `claim_evidence` mapping figures from the full assistant transcript to same-step browser/web result lines (kept up to 40,000 scrubbed characters per call); `seen: null` means no match in the retained text.
A capability counts each of its steps once per run. Whole-run safety failures
and judge failure fail every capability; a step evidence failure affects only
that step's capability. `--judge none` retains deterministic checks but cannot
produce a judged pass. Gateway concierge is skipped; missing installed call_sim
also skips. Calls use installed persona files and the codex backend; tests use
fixtures, never start a server. Failure-site conditions on the real web are not
injected: absent sold-out/deposit/CAPTCHA conditions are not evidence of recovery.

Safety: fresh homes, no payment methods or logins, synthetic `.invalid` contact
information, no real calls, no final effects. The simulated traveller never
approves; its consent guard is deliberately conservative in all three languages.
The directory lab plugin blocks recognized final buttons, maps refs from current
snapshots and observes Enter. Every tripwire hit is a hard failure. Unknown refs,
JavaScript, changing labels and unfocused Enter are not fully fenced: this is a
measurement harness, not a universal transaction sandbox. Supervise first runs.
Hermes destroys headless sessions before returning a turn, so the observer saves
the latest page during tool completion. Screenshot failure records a snapshot-only
deviation. Homes are removed after runs unless `--keep-home`; never publish homes.

Costs: assistant and simulated-user tokens appear separately in `run.json` and
`cost.json`. Dollar cost is unknown rather than guessed; judge CLI usage is billed
separately. The default wave makes 36 jobs, including explicit skips; each live
job has its scenario's dialogue budget (`budget_seconds`: 900, or 1,500–1,800 for
multi-errand scenarios) plus 120 seconds of subprocess grace. Reports
are local exploratory results until the operator creates the required result
card and publishes approved evidence. Source/unit proof establishes no live task,
booking, publication, runtime or customer success.
