"""Gate determinista de mejora continua; registra memoria sin aplicar cambios."""

from __future__ import annotations

import json
from pathlib import Path

from mova_fpl.ops.db import OpsDB


def _required_text(payload: dict, key: str) -> None:
    if not isinstance(payload.get(key), str) or not payload[key].strip():
        raise ValueError(f"evidence.{key} debe ser texto no vacío")


def validate_transition_evidence(to_status: str, evidence: dict) -> None:
    if not isinstance(evidence, dict):
        raise ValueError("evidence debe ser un objeto JSON")
    if to_status == "testing":
        _required_text(evidence, "experiment_id")
        _required_text(evidence, "test_plan")
        return
    if to_status == "rejected":
        _required_text(evidence, "rejection_reason")
        return
    if to_status != "accepted":
        raise ValueError("to_status inválido")
    for key in ("experiment_id", "evaluated_at", "rollback_plan"):
        _required_text(evidence, key)
    if evidence.get("acceptance_passed") is not True:
        raise ValueError("evidence.acceptance_passed debe ser true")
    if not isinstance(evidence.get("baseline"), dict) or not evidence["baseline"]:
        raise ValueError("evidence.baseline debe ser un objeto no vacío")
    if not isinstance(evidence.get("candidate"), dict) or not evidence["candidate"]:
        raise ValueError("evidence.candidate debe ser un objeto no vacío")
    tests = evidence.get("test_evidence")
    if not isinstance(tests, list) or not tests or not all(
        isinstance(item, str) and item.strip() for item in tests
    ):
        raise ValueError("evidence.test_evidence requiere referencias no vacías")


class ContinuousImprovementService:
    def __init__(self, db: OpsDB):
        self.db = db

    def status(self, *, season: str | None = None, gw: int | None = None) -> dict:
        self.db.migrate()
        return self.db.improvement_status(season=season, gw=gw)

    def transition(self, *, proposal_id: str, to_status: str, evidence_path: Path,
                   actor: str, reason: str, idempotency_key: str) -> dict:
        if not all(value.strip() for value in (
            proposal_id, actor, reason, idempotency_key,
        )):
            raise ValueError("proposal_id, actor, reason e idempotency_key son obligatorios")
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("no se pudo leer evidence JSON") from exc
        validate_transition_evidence(to_status, evidence)
        self.db.migrate()
        return self.db.transition_change_proposal(
            proposal_id, to_status=to_status, evidence=evidence,
            actor=actor, reason=reason, idempotency_key=idempotency_key,
        )
