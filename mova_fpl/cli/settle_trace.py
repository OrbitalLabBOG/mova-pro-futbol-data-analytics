"""Exporta un review ya calculado hacia trace.db sin cruzar la frontera ops."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from mova_fpl.agent.attribution import Attribution
from mova_fpl.engine.state import Decision, GwOutcome
from mova_fpl.trace import TraceWriter


@dataclass(frozen=True)
class ManualOverride:
    gw: int
    author: str
    rationale: str
    payload: dict

    def to_dict(self) -> dict:
        return self.payload


def _package(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "mova-fpl-manual-closeout-v1":
        raise ValueError("package de cierre inválido")
    return payload


def _decision(spec: dict, season: str, gw: int) -> Decision:
    players = spec["players"]
    return Decision(
        season=season, gw=gw,
        squad_15=tuple(int(row["element"]) for row in players),
        starters=tuple(int(row["element"]) for row in players if row["role"] == "starter"),
        captain=int(spec["captain"]), vice_captain=int(spec["vice_captain"]),
        bench_order=tuple(int(value) for value in spec["bench_order"]),
        expected_points=float(spec["expected_points"]), total_cost=float(spec["total_cost"]),
        bank_after=float(spec.get("bank_after", 0)), policy=str(spec["policy_version"]),
    )


def export(package_path: Path, review_path: Path, trace_db: Path) -> dict:
    package = _package(package_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    metrics = review["metrics"]
    selected = _decision(package["selected"], package["season"], int(package["gw"]))
    comparator = _decision(package["comparator"], package["season"], int(package["gw"]))
    score = metrics["selected"]
    outcome = GwOutcome(
        gw=int(package["gw"]), points=int(score["points"]),
        points_before_hits=int(score["points_before_hits"]), hits=0,
        captain_points=int(score["captain_points"]),
        auto_subs=tuple(tuple(item) for item in score["auto_subs"]),
        effective_captain=score["effective_captain"],
        players_played=int(score["players_played"]),
    )
    run_id = package["trace_run_id"]
    writer = TraceWriter(trace_db)
    writer.start_run(run_id, package["season"], "named", "human-reviewed", 3, 0, {
        "schema": package["schema"], "review": "retrospective", "causal_scorecard": False,
    })
    writer.record_gw(run_id, selected, outcome, state="reconciled")
    writer.record_baselines(run_id, int(package["gw"]), {
        "pure_model_v1.1.0": int(metrics["comparator"]["points"]),
        "same_squad_hindsight_oracle": int(metrics["same_squad_oracle_free_captain"]),
    })
    attribution = Attribution(
        gw=int(package["gw"]), author="julian+orbix",
        rationale=package["intervention"]["rationale"],
        expected_delta=round(selected.expected_points - comparator.expected_points, 3),
        realized_delta=int(metrics["intervention"]["realized_delta"]),
        points_with=int(metrics["selected"]["points"]),
        points_without=int(metrics["comparator"]["points"]), changed=True,
        detail={"fingerprint_with": selected.fingerprint(),
                "fingerprint_without": comparator.fingerprint(),
                "captain_with": selected.captain, "captain_without": comparator.captain,
                "causal_scope": "paired_decision_same_official_results"},
    )
    writer.record_intervention(
        run_id, int(package["gw"]), ManualOverride(
            int(package["gw"]), "julian+orbix", package["intervention"]["rationale"],
            package["intervention"],
        ), attribution,
    )
    writer.finish_run(run_id, int(metrics["selected"]["points"]))
    return {"run_id": run_id, "points": metrics["selected"]["points"],
            "comparator_points": metrics["comparator"]["points"],
            "oracle_points": metrics["same_squad_oracle_free_captain"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--review-artifact", required=True)
    parser.add_argument("--trace-db", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(export(Path(args.package), Path(args.review_artifact), Path(args.trace_db))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
