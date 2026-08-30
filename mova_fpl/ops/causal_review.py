"""Reviewer causal determinista; nunca aprende de una GW preliminar."""

from __future__ import annotations

import hashlib
from pathlib import Path

from mova_fpl.ops.analytics_store import AnalyticsStore, read_status
from mova_fpl.ops.collector.contracts import canonical_bytes, write_atomic
from mova_fpl.ops.db import OpsDB, sha256_json, utcnow


class CausalReviewerService:
    CATEGORIES = ("data/freshness", "model/calibration", "optimizer",
                  "research/context", "strategy", "execution", "variance")

    def __init__(self, config, db: OpsDB):
        self.config = config
        self.db = db

    def run(self, *, gw: int, actor: str, reason: str,
            idempotency_key: str, analytics_state: dict | None = None) -> dict:
        if not actor.strip() or not reason.strip() or not idempotency_key.strip():
            raise ValueError("actor, reason e idempotency_key son obligatorios")
        self.db.migrate()
        source = self.db.causal_review_source(self.config.season, gw)
        if not source:
            return {"status": "not_ready", "reason": "settlement_not_closed",
                    "season": self.config.season, "gw": gw}
        official = source["official"]
        if not official.get("finished") or not official.get("data_checked"):
            return {"status": "not_ready", "reason": "official_data_not_checked",
                    "season": self.config.season, "gw": gw}
        state = analytics_state or self._analytics()
        scorecards = [row for row in state.get("latest_scorecards", [])
                      if row.get("season") == self.config.season
                      and int(row.get("gw") or 0) == gw]
        baseline = next((row for row in scorecards if row.get("variant") == "baseline"), None)
        if not baseline:
            return {"status": "not_ready", "reason": "baseline_scorecard_missing",
                    "season": self.config.season, "gw": gw}
        correlation_id = "corr_" + hashlib.sha256(
            f"{idempotency_key}:causal".encode("utf-8")
        ).hexdigest()[:24]
        job_id, reused = self.db.start_job(
            "causal_review", idempotency_key, correlation_id,
            cycle_id=source["cycle_id"], input_sha256=sha256_json({
                "source_review_id": source["review_id"], "scorecards": scorecards,
            }),
        )
        if reused:
            return {"status": "reused", "job_id": job_id}
        try:
            context = self.db.causal_review_context(source["cycle_id"])
            findings = self.classify(source, baseline, context)
            proposals = self._proposals(findings, source)
            created_at = utcnow()
            review_id = "causalreview_" + hashlib.sha256(
                idempotency_key.encode("utf-8")
            ).hexdigest()[:24]
            metrics = {
                "schema": "mova-causal-review-v1", "source_review_id": source["review_id"],
                "scorecard": baseline, "context": context,
                "single_gw_optimization_forbidden": True,
                "proposal_count": len(proposals),
            }
            artifact = {
                "schema": "mova-causal-review-artifact-v1", "review_id": review_id,
                "season": self.config.season, "gw": gw, "created_at": created_at,
                "metrics": metrics, "findings": findings, "proposals": proposals,
            }
            body = canonical_bytes(artifact)
            artifact_sha = hashlib.sha256(body).hexdigest()
            path = (self.config.artifact_root / "reviews" / self.config.season
                    / f"gw{gw:02d}" / f"causal-{artifact_sha}.json")
            write_atomic(path, body)
            result = self.db.record_causal_review({
                "review_id": review_id, "job_id": job_id, "actor": actor,
                "reason": reason, "correlation_id": correlation_id,
                "source": source, "metrics": metrics, "findings": findings,
                "proposals": proposals, "artifact_path": str(path),
                "artifact_sha256": artifact_sha, "created_at": created_at,
            })
        except Exception as exc:
            self.db.finish_job(job_id, "failed", error_code=type(exc).__name__,
                               error_detail=str(exc)[:2000])
            raise
        output = {"status": "completed", "job_id": job_id, **result,
                  "findings": findings, "proposals": len(proposals),
                  "artifact_path": str(path), "artifact_sha256": artifact_sha}
        self.db.finish_job(job_id, "completed", output_sha256=sha256_json(output),
                           metrics={"gw": gw, "findings": len(findings),
                                    "proposals": len(proposals)})
        return output

    def _analytics(self) -> dict:
        try:
            return (AnalyticsStore(self.config).status(limit=100)
                    if self.config.postgres_credential_file.is_file()
                    else read_status(self.config))
        except (OSError, RuntimeError, ValueError):
            return {"latest_scorecards": []}

    def classify(self, source: dict, scorecard: dict, context: dict) -> list[dict]:
        findings = []

        def add(category: str, code: str, summary: str, actionable: bool) -> None:
            findings.append({"category": category, "code": code, "summary": summary,
                             "actionable": actionable,
                             "prior_occurrences": context["category_occurrences"].get(
                                 category, 0)})

        drift = scorecard.get("drift_status")
        if drift == "alert":
            add("model/calibration", "MODEL_DRIFT_ALERT",
                "El scorecard causal marcó drift; requiere experimento multi-GW.", True)
        if context["unresolved_research_conflicts"]:
            add("research/context", "UNRESOLVED_RESEARCH_CONFLICTS",
                f"Persistieron {context['unresolved_research_conflicts']} conflictos.", True)
        if context["failed_validation_checks"]:
            add("optimizer", "DECISION_VALIDATION_FAILURES",
                f"Hubo {context['failed_validation_checks']} checks deterministas fallidos.", True)
        if context["execution_failures"]:
            add("execution", "EXECUTION_FAILURES",
                f"Hubo {context['execution_failures']} fallos/ambigüedades de ejecución.", True)
        realized = source.get("realized_delta")
        if realized is not None and int(realized) <= -4:
            add("strategy", "NEGATIVE_REALIZED_DELTA",
                f"La alternativa elegida perdió {abs(int(realized))} puntos vs comparador.", True)
        expected = float(source["expected_points"])
        actual = int(source["actual_points"])
        add("variance", "REALIZED_VS_EXPECTED",
            f"Resultado {actual} vs {expected:.2f} esperado; una GW no prueba causalidad.", False)
        return findings

    def _proposals(self, findings: list[dict], source: dict) -> list[dict]:
        proposals = []
        for finding in findings:
            # La tercera ocurrencia histórica permite proponer; nunca la primera observación.
            if not finding["actionable"] or finding["prior_occurrences"] < 2:
                continue
            category = finding["category"]
            proposals.append({
                "proposal_id": "proposal_" + hashlib.sha256(
                    f"{source['settlement_id']}:{category}".encode("utf-8")
                ).hexdigest()[:24],
                "category": category, "change_level": "experiment", "priority": "medium",
                "title": f"Evaluar patrón repetido: {category}",
                "hypothesis": finding["summary"],
                "evidence": {"finding": finding, "review_id": source["review_id"]},
                "acceptance": {"minimum_gameweeks": 3, "requires_baseline": True,
                               "requires_rollback": True},
                "status": "proposed",
            })
        return proposals
