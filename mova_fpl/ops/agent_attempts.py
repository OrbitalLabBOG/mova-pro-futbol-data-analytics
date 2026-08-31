"""Importa recibos inmutables del worker aislado y limita sus replays."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, canonical_json, sha256_json

MAX_RECEIPT_BYTES = 65_536
MAX_AUTOMATIC_ATTEMPTS = 2
TERMINAL = {
    "research": {"imported", "rejected", "failed"},
    "deliberation": {"accepted", "review_required", "blocked", "rejected", "failed"},
}
RECEIPT_NAME = re.compile(
    r"^(research|deliberation)_[0-9a-f]{32}\."
    r"(attempt_[0-9a-f]{32})\.(started|finished)\.json$"
)


class AgentAttemptService:
    def __init__(self, config: RuntimeConfig, db: OpsDB):
        self.config = config
        self.db = db

    @property
    def receipts(self) -> Path:
        return self.config.research_root / "receipts"

    @property
    def permits(self) -> Path:
        return self.config.research_root / "permits"

    def authorize_next(self, *, now: datetime | None = None) -> dict:
        """Seal one short-lived host permit; without it the worker cannot call Codex."""
        self.db.migrate()
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.permits.mkdir(parents=True, exist_ok=True)
        blocked = []
        for subject in self.db.pending_agent_subjects():
            try:
                request_path = Path(subject["request_path"])
                inbox = (self.config.research_root / "inbox").resolve()
                expected = f"{subject['subject_id']}.request.json"
                if (request_path.name != expected or request_path.is_symlink()
                        or not request_path.is_file()
                        or request_path.resolve().parent != inbox):
                    raise ValueError("request pendiente fuera del inbox permitido")
                request = json.loads(request_path.read_text(encoding="utf-8"))
                embedded_sha = request.pop("request_sha256", None)
                if (embedded_sha != subject["request_sha256"]
                        or sha256_json(request) != subject["request_sha256"]):
                    raise ValueError("request pendiente no coincide con hash durable")
                prepared = self.db.prepare_agent_attempt_authorization(
                    subject_type=subject["subject_type"], subject_id=subject["subject_id"],
                    permit_dir=str(self.permits), now=current, permit_ttl_seconds=600,
                    final_cutoff_seconds=self.config.research_final_cutoff_seconds,
                )
                if prepared["status"] in {"blocked", "skipped"}:
                    blocked.append(prepared)
                    continue
                budget = prepared.get("budget_snapshot") or json.loads(
                    prepared["budget_snapshot_json"]
                )
                permit_path = Path(prepared["permit_path"])
                permit = {
                    "schema": "mova-agent-attempt-permit-v1",
                    "authorization_id": prepared["authorization_id"],
                    "subject_type": prepared["subject_type"],
                    "subject_id": prepared["subject_id"],
                    "request_sha256": prepared["request_sha256"],
                    "attempt_number": int(prepared["attempt_number"]),
                    "deadline_at": prepared["deadline_at"],
                    "expires_at": prepared["expires_at"],
                    "budget_snapshot_sha256": sha256_json(budget),
                }
                raw = (canonical_json(permit) + "\n").encode("utf-8")
                tmp = permit_path.with_name(f"{permit_path.name}.tmp")
                tmp.write_bytes(raw)
                tmp.chmod(0o660)
                tmp.replace(permit_path)
                digest = hashlib.sha256(raw).hexdigest()
                sealed = self.db.seal_agent_attempt_authorization(
                    prepared["authorization_id"], permit_sha256=digest
                )
                return {
                    "status": "authorized", "authorization_id": sealed["authorization_id"],
                    "subject_type": prepared["subject_type"],
                    "subject_id": prepared["subject_id"],
                    "attempt_number": int(prepared["attempt_number"]),
                    "expires_at": prepared["expires_at"], "permit_path": str(permit_path),
                    "permit_sha256": digest, "reused": bool(sealed.get("reused")),
                    "blocked_candidates": blocked,
                }
            except Exception as exc:  # noqa: BLE001 - candidato aislado, no autoriza IO
                blocked.append({"status": "blocked", "subject_type": subject["subject_type"],
                                "subject_id": subject["subject_id"],
                                "reason": type(exc).__name__, "detail": str(exc)[:300]})
        return {"status": "skipped" if not blocked else "blocked",
                "reason": "no_authorized_subject", "blocked_candidates": blocked}

    def import_ready(self) -> dict:
        self.db.migrate()
        self.receipts.mkdir(parents=True, exist_ok=True)
        candidates: list[tuple[int, str, Path, dict, str]] = []
        rejected = []
        for path in sorted(self.receipts.glob("*.json")):
            try:
                payload, digest = self._validate(path)
                phase = 0 if payload["event_type"] == "started" else 1
                candidates.append((phase, payload["occurred_at"], path, payload, digest))
            except Exception as exc:  # noqa: BLE001 - cada receipt se aísla
                target = self._quarantine(path)
                rejected.append({"path": str(target), "error_code": type(exc).__name__,
                                 "error": str(exc)[:300]})
        imported = []
        for _, _, path, payload, digest in sorted(candidates):
            try:
                if payload["event_type"] == "finished" and not self._started_exists(
                    payload["attempt_id"], candidates
                ):
                    raise ValueError("finished receipt sin started receipt")
                imported.append(self.db.record_agent_worker_attempt_event(
                    payload, receipt_path=str(path), receipt_sha256=digest
                ))
            except Exception as exc:  # noqa: BLE001 - replay alterado queda aislado
                target = self._quarantine(path)
                rejected.append({"path": str(target), "error_code": type(exc).__name__,
                                 "error": str(exc)[:300]})
        exhausted = self._terminalize_exhausted()
        return {
            "status": "completed", "processed": len(imported), "results": imported,
            "rejected": rejected, "exhausted": exhausted,
            "max_automatic_attempts": MAX_AUTOMATIC_ATTEMPTS,
        }

    def status(self) -> dict:
        self.db.migrate()
        return self.db.agent_worker_attempt_status()

    def _started_exists(self, attempt_id: str, batch: list[tuple]) -> bool:
        if any(item[3]["attempt_id"] == attempt_id
               and item[3]["event_type"] == "started" for item in batch):
            return True
        with self.db.connect(readonly=True) as con:
            return con.execute(
                "SELECT 1 FROM agent_worker_attempt_events "
                "WHERE attempt_id=? AND event_type='started'", (attempt_id,)
            ).fetchone() is not None

    def _validate(self, path: Path) -> tuple[dict, str]:
        match = RECEIPT_NAME.fullmatch(path.name)
        if not match or not path.is_file() or path.is_symlink():
            raise ValueError("nombre o tipo de receipt inválido")
        if path.stat().st_size > MAX_RECEIPT_BYTES:
            raise ValueError("receipt excede 64 KiB")
        raw = path.read_bytes()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("receipt debe ser objeto JSON")
        base_keys = {
            "schema", "attempt_id", "subject_type", "subject_id", "request_sha256",
            "event_type", "status", "model", "input_tokens", "output_tokens",
            "duration_ms", "error_code", "output_present", "occurred_at",
        }
        schema = payload.get("schema")
        expected_keys = (base_keys if schema == "mova-agent-attempt-v1"
                         else base_keys | {"authorization_id"})
        if (schema not in {"mova-agent-attempt-v1", "mova-agent-attempt-v2"}
                or set(payload) != expected_keys):
            raise ValueError("schema de receipt inválido")
        if schema == "mova-agent-attempt-v2" and not re.fullmatch(
            r"agentauth_[0-9a-f]{32}", str(payload.get("authorization_id") or "")
        ):
            raise ValueError("authorization_id inválido")
        if schema == "mova-agent-attempt-v2":
            authorization = self.db.agent_attempt_authorization(payload["authorization_id"])
            if not authorization:
                raise ValueError("receipt sin autorización durable")
            permit = Path(authorization["permit_path"])
            permit_root = self.permits.resolve()
            if (permit.is_symlink() or not permit.is_file()
                    or permit.resolve().parent != permit_root):
                raise ValueError("permiso durable ausente o fuera de allowlist")
            digest = hashlib.sha256(permit.read_bytes()).hexdigest()
            if digest != authorization["permit_sha256"]:
                raise ValueError("permiso durable alterado")
        prefix, attempt_id, phase = match.groups()
        subject_id = path.name.split(".", 1)[0]
        subject_type = "research" if prefix == "research" else "deliberation"
        if (payload["attempt_id"] != attempt_id or payload["event_type"] != phase
                or payload["subject_id"] != subject_id
                or payload["subject_type"] != subject_type):
            raise ValueError("identidad del receipt no coincide")
        if not re.fullmatch(r"[0-9a-f]{64}", str(payload["request_sha256"])):
            raise ValueError("request_sha256 inválido")
        subject = self.db.agent_subject(subject_type, subject_id)
        if not subject or subject.get("request_sha256") != payload["request_sha256"]:
            raise ValueError("receipt no corresponde a request durable")
        expected_status = {"started": {"running"}, "finished": {"succeeded", "failed"}}
        if payload["status"] not in expected_status[phase]:
            raise ValueError("status del receipt inválido")
        if not isinstance(payload["model"], str) or not payload["model"][:1]:
            raise ValueError("model inválido")
        for key in ("input_tokens", "output_tokens", "duration_ms"):
            value = payload[key]
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"{key} inválido")
        if payload["output_present"] is not None and not isinstance(
            payload["output_present"], bool
        ):
            raise ValueError("output_present inválido")
        if phase == "started" and any(payload[key] is not None for key in (
            "input_tokens", "output_tokens", "duration_ms", "error_code", "output_present"
        )):
            raise ValueError("started receipt contiene campos terminales")
        if payload["status"] == "failed" and not re.fullmatch(
            r"[a-z][a-z0-9_]{2,79}", str(payload["error_code"] or "")
        ):
            raise ValueError("error_code inválido")
        if payload["status"] == "succeeded" and payload["error_code"] is not None:
            raise ValueError("success receipt contiene error")
        observed = datetime.fromisoformat(str(payload["occurred_at"]).replace("Z", "+00:00"))
        if observed.tzinfo is None or observed > datetime.now(timezone.utc):
            raise ValueError("occurred_at inválido")
        return payload, hashlib.sha256(raw).hexdigest()

    def _terminalize_exhausted(self) -> list[dict]:
        status = self.db.agent_worker_attempt_status()
        exhausted = []
        for item in status["subjects"]:
            if int(item["attempts"]) < MAX_AUTOMATIC_ATTEMPTS or int(item["successes"]):
                continue
            subject_type, subject_id = item["subject_type"], item["subject_id"]
            subject = self.db.agent_subject(subject_type, subject_id)
            if not subject or subject["status"] in TERMINAL[subject_type]:
                continue
            detail = f"agotados {item['attempts']} intentos automáticos; failures={item['failures']}"
            if subject_type == "research":
                self.db.reject_research_run(
                    subject_id, error_code="agent_attempts_exhausted", error_detail=detail
                )
            else:
                self.db.reject_decision_deliberation(
                    subject_id, error_code="agent_attempts_exhausted", error_detail=detail
                )
            request = Path(subject["request_path"])
            target = None
            if request.is_file():
                inbox = (self.config.research_root / "inbox").resolve()
                if request.is_symlink() or request.resolve().parent != inbox:
                    raise ValueError("request_path agotado fuera del inbox permitido")
                target = self._quarantine(request)
            exhausted.append({"subject_type": subject_type, "subject_id": subject_id,
                              "attempts": int(item["attempts"]),
                              "request_path": str(target) if target else None})
        return exhausted

    def _quarantine(self, source: Path) -> Path:
        root = self.config.research_root / "quarantine"
        root.mkdir(parents=True, exist_ok=True)
        target = root / source.name
        if target.exists():
            digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
            target = root / f"{source.stem}-{digest}{source.suffix}"
        source.replace(target)
        return target
