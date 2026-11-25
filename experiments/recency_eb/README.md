---
type: experiment
id: EXP-RECENCY-EB-2026-001
status: active
branch: exp/recency-eb
---

# EXP-RECENCY-EB-2026-001 — Two-Stage Empirical Bayes Recency (`points-1.2.0-eb`)

Offline experiment comparing candidate `points-1.2.0-eb` (2-stage empirical Bayes recency inside `PointsModel`, opt-in via `recency_mode="eb2"` / `RecencyEBConfig`) against production `points-1.1.0` (`player_recency_half_life=None`). `MinutesModel` 1.1.0 is frozen and identical across both arms.

## Usage

```bash
/workspace/mova-fpl/.venv/bin/python -m experiments.recency_eb.run all
```

Subcommands:
- `tune`: grid search on 2023-24 & 2024-25 (Poisson deviance conditional on `minutes > 0`), freezes winner to `tune-winner.json`.
- `verify`: verification on 2025-26 (walk-forward prediction + legal MILP decision replay, cold-start GW1).
- `evaluate`: single evaluation on 2026-27 GW2–11 predictions (including GW8–11 vs `ep_next` and sealed batch).
- `replay`: legal MILP decision replay on 2026-27 GW1–11 starting from Julian's real GW1 squad (entry 3609854, GW1 prices = 100.0M, bank = 0.0, GW1 XI/captain only, separate ledgers from GW2).

Artifacts are written to `/workspace/mova-fpl-notes/mlops/exp-recency-eb/`.
