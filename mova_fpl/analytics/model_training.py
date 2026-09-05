"""Pure analytics entrypoint for fitting an immutable candidate model pair."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from mova_fpl.models.minutes import MinutesModel
from mova_fpl.models.points import PointsModel
from mova_fpl.models.registry import save


def fit_candidate_models(frame: pd.DataFrame, *, version: str,
                         holdout: str, artifact_root: Path,
                         architecture: str = "baseline") -> dict:
    """Fit and persist minutes + points without selecting or promoting a release."""
    if architecture not in {"baseline", "participation_v2"}:
        raise ValueError("unknown minutes architecture")
    if architecture == "participation_v2":
        from mova_fpl.models.participation import ParticipationModel
        minutes = ParticipationModel(version=version, calibrar=True)
    else:
        minutes = MinutesModel(version=version, calibrar=True)
    minutes.fit(frame, calib_season=holdout)
    minutes_record = save(
        minutes, "minutes", version,
        {
            "mode": "production_candidate", "fit_through": holdout,
            "calib_season": holdout, "held_out_metrics": False,
            "dataset_rows": int(len(frame)),
            "architecture": architecture,
        },
        artifact_root=artifact_root, overwrite=False,
    )

    points = PointsModel(version=version).fit(frame)
    points_record = save(
        points, "points", version,
        {
            "mode": "production_candidate", "fit_through": holdout,
            "held_out_metrics": False, "dataset_rows": int(len(frame)),
            "defcon_sin_datos": bool(points.defcon.sin_datos),
        },
        artifact_root=artifact_root, overwrite=False,
    )
    return {"minutes": minutes_record, "points": points_record}
