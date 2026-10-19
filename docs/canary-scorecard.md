# Daily-ops canary scorecard (5-day, single customer)

Run this after the first consented customer profile is live, before any broader
rollout. One row per day; note exceptions in the last column.

| Day | Brief delivered on time? | Watchdog false positives | Watchdog missed (real priority missed)? | Autoclean regret (read something owner wanted)? | Owner actions taken from brief/alerts |
|-----|--------------------------|--------------------------|------------------------------------------|--------------------------------------------------|----------------------------------------|
| 1   |                          |                          |                                          |                                                  |                                        |
| 2   |                          |                          |                                          |                                                  |                                        |
| 3   |                          |                          |                                          |                                                  |                                        |
| 4   |                          |                          |                                          |                                                  |                                        |
| 5   |                          |                          |                                          |                                                  |                                        |

**Rollout gate (all must hold):**
- ≥4/5 briefs delivered on time; zero unexplained silent failures
- ≤1 false-positive priority alert total; zero missed real priorities
- zero unattended mailbox mutations (daily-ops autoclean is unsupported and must remain disabled)
- owner took ≥1 action from briefs/alerts on ≥3 days (evidence of value)

Failure on any gate → tune config (terms, windows, caps), re-canary. Do not
expand the cohort on a partial pass.
