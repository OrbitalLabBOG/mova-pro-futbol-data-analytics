# Odds + events ablation

Exploratory, causal experiment for the decomposed FPL points model. It changes
only the fixture context (expected goals for/against); minutes, player rates,
rules and optimizer remain the released implementation.

## Decision (2026-08-24)

- **Keep the branch; do not promote it to production.** Pre-closing odds contain
  useful out-of-sample signal, especially for clean-sheet probability.
- **Advance `odds_cs` only** to the next integration experiment. It improved the
  independent weekly squad control by 87 points (95% paired bootstrap interval
  +15 to +159) and reduced clean-sheet bias from +8.09% to +2.83%.
- **Reject the current event features.** Shots, box shots, big chances and box
  touches added no reliable signal after the odds and did not improve the
  untouched GW20-29 event test.
- **Do not switch the live model.** The legal named h=3 replay scored 2,130 with
  `odds_cs` versus 2,168 for baseline. A fixture-specific future-GW matrix and
  transfer-stability work are required before another promotion test.

The compact evidence and full interpretation are in
`evidence/2026-08-24-summary.json` and
`docs/decisions/2026-27/odds-events-ablation.md`.

Information barriers:

- only football-data.co.uk pre-closing consensus columns are read;
- market blend weight is selected on 2020/21–2023/24;
- 2024/25 and 2025/26 remain season holdouts;
- event feature set/exponent is selected on 2025/26 GW10–19;
- event results are evaluated on GW20–29;
- all matches in a GW are projected before that GW's events update state.

Run from the repository root with the provisioned Python 3.13 runtime:

```bash
export SOURCE_REPO=/home/jzuluaga/code/orbital-lab/mova-pro-futbol-data-analytics
PYTHONPATH=. /home/jzuluaga/miniconda3/bin/python experiments/odds_events/run.py \
  --fpl-db "$SOURCE_REPO/data/processed/fpl_canonical.db" \
  --odds-dir "$SOURCE_REPO/data/club-odds-mirror/data/premier-league" \
  --events-db "$SOURCE_REPO/data/mundial.db" \
  --model-root "$SOURCE_REPO/models" \
  --output-dir /tmp/mova-odds-events-results \
  --weekly-rebuild
```

The experiment must not be promoted on optimizer points alone. Match
calibration, xP component metrics and the paired temporal test must agree.
Generated player-level CSVs and SQLite traces belong in the output directory,
not in Git.
