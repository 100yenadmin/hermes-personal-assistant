# Concierge proof rig

P1 checks real Hermes gateway/Telegram-loopback setup, human-only setup context,
durable progress, exact plan-to-pulse arguments, wake receipts, same-DM offer
delivery and deduplication. It is opt-in, outside `python -m pytest tests -q`.
Use the prepared `PA_E2E_PYTHON` and read-only `PA_E2E_HERMES`/`PA_E2E_HEARTBEAT2`
checkouts; install nothing. Set `PA_E2E_RESULTS` to the evidence directory.
```sh
export HERMES_DISABLE_LAZY_INSTALLS=1 PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp
"$PA_E2E_PYTHON" -m pytest evals/concierge_e2e/test_scripted.py -q -p no:cacheprovider
"$PA_E2E_PYTHON" evals/concierge_e2e/live.py --model MODEL --url BASE_URL --key-env MODEL_KEY
```
P2 forwards from the parent; the child stays loopback-only. The key is removed
from the environment before gateway startup. `--answers` replaces the synthetic
nine-entry fixture. `--toolsets` defaults to `memory file` for approved writes.
P2 arms a wake about eight minutes out and waits up to twelve minutes for an offer, capped at 40 bot turns; inspect its transcript
and ledger (no semantic judge). Runs retain requests, messages, logs and ledger;
P2 adds header-free model responses and a transcript. No results are deleted.
`--persona evals/concierge_e2e/personas/<name>.json` seeds synthetic profile files
and runs only the interview, up to its review. It answers whichever question PA's
setup record says is next, then writes `persona-result.json` with the discovered
and asked question IDs. That checks that questions answered by discovery are not asked.
A profile persona with `"sittings": 2` then applies, sends `/new` and "grill me", runs the
next group's sitting to its review, and checks that nothing is re-asked across sittings.
A persona with `"mode": "owner_memory"` (`personas/memory-corrections.json`) sends its statements in one
session: a preference, a person rule and a correction. It then checks that PA's ledger holds them, with the
corrected text active and the replaced one not. After `/new`, it checks that the first request carries PA's
owner-memory note and that the agent's replies honour the corrected preference and the person rule (phrase match).
Claim class: `local_e2e_proof` (loopback Bot API; not real Telegram or providers).
P2 proves no provider actions, live profile behavior, CI or customer readiness.

P3 is the scripted watcher proof in `test_watch.py`. It runs the real HB2
scheduled command probe against the gateway's copy of PA, using its exact
interpreter/`-I`/observer allowlist prefix. The script changes only the returned
`pulse create` trigger's `check_every` from PA's fixed `15m` to `2s`; the saved
observer `check_every` setting does not change PA's pulse arguments. HB2's probe
floor is one second. P3 has an explicit 420-second timeout; P1 keeps 240 seconds.
Run the whole directory on each prepared pin twice consecutively:
```sh
export HERMES_DISABLE_LAZY_INSTALLS=1 PYTHONDONTWRITEBYTECODE=1
export PA_E2E_HEARTBEAT2="$HB2_CHECKOUT"
PA_E2E_HERMES="$HERMES_MAIN_CHECKOUT" PA_E2E_RESULTS="$PA_E2E_RESULTS_ROOT/main-r1" \
  "$HERMES_MAIN_PYTHON" -m pytest evals/concierge_e2e -q -x -p no:cacheprovider
PA_E2E_HERMES="$HERMES_V0222_CHECKOUT" PA_E2E_RESULTS="$PA_E2E_RESULTS_ROOT/v0222-r1" \
  "$HERMES_V0222_PYTHON" -m pytest evals/concierge_e2e -q -x -p no:cacheprovider
```
Use the prepared paths from the issue's run contract for these variables. Set
`PA_E2E_RESULTS_ROOT` to the durable P3 evidence root supplied by the owner,
outside temporary storage. Repeat each command with `r2` after its first pass,
running one process at a time. Stop on a product failure and keep its evidence.
Capture the actual exit code without a shell pipe, and write a result card for
every invocation under that invocation's result root. Runtime sockets still use
short temporary paths; the rig snapshots their evidence before scoring.
Each invocation creates unique evidence subdirectories and prints their paths.
They retain gateway logs, scripted requests, visible same-DM messages, the PA
ledger and `hb2.json` (wakes, occurrences, sessions and ledger rows). Wait failures
include the gateway tail and HB2 rows. Collection without `PA_E2E_HERMES` skips
these tests before importing Hermes. No live model or provider is used.

The delay gate checks a simulated 90-minute departure delay, per-occurrence
`flight_change` routing, a single offer and acknowledgement, and at least three
further scheduled polls past the observer re-emission interval. The weather gate
uses a loopback Open-Meteo stand-in, checks `Be at the airport by` (transfer unknown) and `+45 min for snow`,
records a decline, then acknowledges a thunderstorm notice with no new message.
The unanswered gate injects three successive delays: two offers arrive, and HB2
stores the third occurrence as pending with `held_reason=held_unanswered`,
`held_since` populated and `delivered=0`. The saved `held-before-reply.json`
captures that state. One owner reply releases the held item exactly once.
Every P3 scenario checks zero HB2 watcher and director errors. The directory
also includes P1's setup-to-offer regression. Check-in and `/new` re-arm stretch
scenarios are outside this required matrix and are not implemented here.
P1 aligns its synthetic departure to the product's five-minute rounding and
chooses integer leads that place the real scheduled wake 60-120 seconds ahead.

P4 runs a direct live Codex model through the same pinned gateway, HB2 command
poller, observer and loopback Telegram/weather services. Run `test_live.py`
with `--results EVIDENCE_ROOT` after setting the prepared Hermes/HB2 paths.
It runs delay, snow/acceptance and unanswered notices twice, sequentially;
`--scenario` and `--round` select a bounded subset. It is not a pytest live test.
The parent reads only the access-token field once. Each run requires a JWT
expiry more than two hours ahead and writes the approved nested auth shape with
a nonfunctional placeholder refresh token. The child has isolated HOME and no
CODEX_HOME, with only chatgpt.com added to the loopback network boundary;
the refresh host is excluded. After stopping, it asserts the placeholder and
real Codex auth mtime are unchanged and scrubs the isolated credential/logs.
The synthetic owner arms only a watch; its test cadence is 2s rather than 15m.
No real provider actions or web tools are available. Snapshots include messages,
tool transcript, ledger, HB2 rows, gateway logs, wire model/effort/tier metadata,
per-model token accounting and `p4-result.json`. Text/list checks are mechanical;
the dispatch owner still reads both transcripts, with no model judge.
Claim class remains `local_e2e_proof`; this does not prove real Telegram,
provider completion, installed profiles, fleet/customer readiness or CI.
