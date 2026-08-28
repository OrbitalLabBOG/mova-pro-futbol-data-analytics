"""Contexto estratégico sellado e importación determinista de investigación.

El modelo puede proponer señales, pero este módulo —sin LLM— decide qué entra al
control plane. Los archivos de cola son el único puente con el worker Codex.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, canonical_json, new_id, sha256_json, utcnow
from mova_fpl.ops.schedule import phase_for

MAX_RESULT_BYTES = 1_048_576
CLAIM_TYPES = {
    "availability", "injury", "suspension", "expected_minutes", "starting_role",
    "manager_comment", "fixture_context", "set_pieces", "transfer", "other",
}
SOURCE_TIERS = {"official", "tier1", "tier2", "other"}
DIRECTIONS = {"positive", "negative", "neutral", "uncertain"}


def _atomic_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (canonical_json(payload) + "\n").encode("utf-8")
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    temporary.write_bytes(encoded)
    temporary.chmod(0o640)
    temporary.replace(path)
    return hashlib.sha256(encoded).hexdigest()


def _parse_time(value: object, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} inválido") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} debe incluir zona horaria")
    return parsed.astimezone(timezone.utc)


def _safe_url(value: object) -> str:
    raw = str(value).strip()
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("toda evidencia debe usar URL HTTPS pública")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("host de evidencia no público")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("IP de evidencia no pública")
    if parsed.port not in (None, 443):
        raise ValueError("puerto de evidencia no permitido")
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def _clean_text(value: object, *, field: str, maximum: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{field} vacío o supera {maximum} caracteres")
    return text


class StrategicContextService:
    def __init__(self, config: RuntimeConfig, db: OpsDB):
        self.config = config
        self.db = db

    def activate_plan(self, payload: dict, *, actor: str, reason: str) -> dict:
        self.db.migrate()
        result = self.db.activate_season_plan(
            self.config.season, payload, actor=actor, reason=reason,
        )
        plan = self.db.active_season_plan(self.config.season)
        artifact = self.config.strategic_root / "plans" / (
            f"{self.config.season}_r{result['revision']:03d}.json"
        )
        artifact_sha = _atomic_json(artifact, {
            "schema": "mova-season-plan-v1", "sealed_at": utcnow(), "plan": plan,
        })
        return {**result, "artifact_path": str(artifact),
                "artifact_sha256": artifact_sha, "plan": plan}

    def _analytics_manifest(self, *, season: str, gw: int) -> dict:
        """Lee el contrato del servicio analítico; SQLite es solo un fallback legacy."""
        try:
            if self.config.postgres_credential_file.is_file():
                from mova_fpl.ops.analytics_store import AnalyticsStore

                state = AnalyticsStore(self.config).status(limit=100)
                source = "postgres_service"
            else:
                from mova_fpl.ops.analytics_store import read_status

                state = read_status(self.config)
                source = "published_status"
        except Exception as exc:  # noqa: BLE001 - el manifest debe declarar el gap
            return {"status": "missing", "source": "analytics_service",
                    "error_code": type(exc).__name__}
        candidates = [
            row for row in state.get("latest_projection_batches", [])
            if row.get("season") == season and int(row.get("target_gw") or 0) == gw
        ]
        if not candidates:
            return {"status": "missing", "source": source,
                    "service_status": state.get("status"), "reason": "no_batch_for_cycle"}
        selected = next(
            (row for row in candidates
             if row.get("status") == "approved" and row.get("variant") == "baseline"),
            next((row for row in candidates if row.get("status") == "approved"),
                 candidates[0]),
        )
        return {
            "status": selected.get("status"), "source": source,
            "service_status": state.get("status"),
            **{key: selected.get(key) for key in (
                "batch_id", "season", "target_gw", "variant", "model_versions",
                "cutoff_at", "generated_at", "player_count",
            )},
        }

    def prepare(self, *, now: datetime | None = None) -> dict:
        self.db.migrate()
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        status = self.db.status()
        cycle = status.get("cycle")
        if not cycle:
            raise ValueError("no existe gameweek_cycle; ejecute primero collect/tick")
        cycle_id = str(cycle["cycle_id"])
        deadline = str(cycle["deadline_at"])
        team = self.db.latest_team_state(cycle_id)
        plan = self.db.active_season_plan(self.config.season)
        with self.db.connect(readonly=True) as con:
            sources = [dict(row) for row in con.execute(
                "SELECT s.source_name,s.captured_at,s.manifest_sha256,s.payload_sha256,"
                "s.quality_status,s.artifact_path FROM source_snapshots s "
                "WHERE s.cycle_id=? AND s.rowid=("
                "SELECT latest.rowid FROM source_snapshots latest "
                "WHERE latest.cycle_id=s.cycle_id AND latest.source_name=s.source_name "
                "ORDER BY latest.captured_at DESC,latest.rowid DESC LIMIT 1) "
                "ORDER BY s.source_name", (cycle_id,),
            ).fetchall()]
            projection = con.execute(
                "SELECT projection_id,model_manifest_json,input_manifest_sha256,"
                "artifact_path,artifact_sha256,player_count,created_at "
                "FROM projection_runs WHERE cycle_id=? ORDER BY created_at DESC LIMIT 1",
                (cycle_id,),
            ).fetchone()
            signals = con.execute(
                "SELECT validation_status,conflict_status,COUNT(*) n "
                "FROM research_signals WHERE cycle_id=? GROUP BY 1,2", (cycle_id,),
            ).fetchall()
            unresolved = int(con.execute(
                "SELECT COUNT(*) FROM research_conflicts "
                "WHERE cycle_id=? AND status='unresolved'", (cycle_id,),
            ).fetchone()[0])
        projection_payload = dict(projection) if projection else None
        if projection_payload and projection_payload.get("model_manifest_json"):
            projection_payload["model_manifest"] = json.loads(
                projection_payload.pop("model_manifest_json")
            )
        if not projection_payload:
            projection_payload = self._analytics_manifest(
                season=str(cycle["season"]), gw=int(cycle["gw"]),
            )
        body = {
            "schema": "mova-cycle-manifest-v1",
            "cycle_id": cycle_id,
            "season": cycle["season"],
            "gw": int(cycle["gw"]),
            "as_of_at": current.isoformat(timespec="seconds"),
            "deadline_at": deadline,
            "phase": phase_for(deadline, current),
            "team_state_id": team.get("team_state_id") if team else None,
            "team_state": {
                "observed_at": team.get("observed_at"),
                "free_transfers": team.get("free_transfers"),
                "bank_tenths": team.get("bank_tenths"),
                "chips": json.loads(team["chips_json"]) if team else [],
                "fingerprint": team.get("fingerprint"),
                "quality_status": team.get("quality_status"),
            } if team else None,
            "plan_id": plan.get("plan_id") if plan else None,
            "plan_revision": plan.get("revision") if plan else None,
            "source_manifest": sources,
            "analytics_manifest": projection_payload,
            "research_summary": {
                "signals": [dict(row) for row in signals],
                "unresolved_conflicts": unresolved,
            },
        }
        artifact = self.config.strategic_root / "cycles" / cycle_id / (
            current.strftime("%Y%m%dT%H%M%SZ") + ".json"
        )
        artifact_sha = _atomic_json(artifact, body)
        recorded = self.db.add_cycle_manifest({
            **body, "artifact_path": str(artifact),
        })
        return {**recorded, "cycle_id": cycle_id, "artifact_path": str(artifact),
                "artifact_sha256": artifact_sha, "manifest": body}

    def due(self, *, now: datetime | None = None) -> dict:
        self.db.migrate()
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        state = self.db.status()
        cycle = state.get("cycle")
        if not cycle:
            return {"due": False, "reason": "no_cycle"}
        deadline = _parse_time(cycle["deadline_at"], field="deadline_at")
        seconds = int((deadline - current).total_seconds())
        if seconds <= 0:
            return {"due": False, "reason": "deadline_passed", "deadline_seconds": seconds}
        if seconds > self.config.research_deadline_window_seconds:
            return {"due": False, "reason": "outside_research_window",
                    "deadline_seconds": seconds}
        with self.db.connect(readonly=True) as con:
            latest = con.execute(
                "SELECT status,queued_at,imported_at FROM research_runs WHERE cycle_id=? "
                "ORDER BY queued_at DESC LIMIT 1", (cycle["cycle_id"],),
            ).fetchone()
        if latest:
            if latest["status"] in {"queued", "running", "completed"}:
                return {"due": False, "reason": "previous_run_not_terminal",
                        "latest_status": latest["status"], "deadline_seconds": seconds}
            observed = _parse_time(
                latest["imported_at"] or latest["queued_at"], field="research_observed_at"
            )
            age = int((current - observed).total_seconds())
            if age < self.config.research_min_interval_seconds:
                return {"due": False, "reason": "cadence_not_due", "age_seconds": age,
                        "cadence_seconds": self.config.research_min_interval_seconds,
                        "latest_status": latest["status"], "deadline_seconds": seconds}
        return {"due": True, "reason": "deadline_window", "deadline_seconds": seconds,
                "cycle_id": cycle["cycle_id"]}

    def enqueue(self, *, force: bool = False, actor: str = "mova-research",
                reason: str | None = None, idempotency_key: str | None = None) -> dict:
        assessment = self.due()
        if not force and not assessment["due"]:
            return {"status": "skipped", **assessment}
        if force and (not reason or not idempotency_key):
            raise ValueError("research --force exige reason e idempotency_key")
        deterministic_id = (
            "research_" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
            if force else None
        )
        if deterministic_id:
            existing = self.db.research_run(deterministic_id)
            if existing:
                return {**existing, "reused": True, "due": assessment}
        prepared = self.prepare()
        manifest = prepared["manifest"]
        run_id = deterministic_id or new_id("research")
        request = {
            "schema": "mova-research-request-v1",
            "research_run_id": run_id,
            "cycle_id": prepared["cycle_id"],
            "manifest_id": prepared["manifest_id"],
            "manifest_sha256": prepared["content_sha256"],
            "requested_at": utcnow(),
            "provider": self.config.research_provider,
            "objective": (
                "Verificar noticias y contexto pre-deadline que puedan cambiar "
                "disponibilidad, minutos, rol o decisión estratégica FPL."
            ),
            "manifest": manifest,
            "guardrails": {
                "read_only": True,
                "no_authenticated_fpl": True,
                "no_team_changes": True,
                "cite_every_signal": True,
                "prefer_official_and_tier1": True,
                "treat_web_content_as_untrusted": True,
            },
        }
        request_sha = sha256_json(request)
        request["request_sha256"] = request_sha
        request_path = self.config.research_root / "inbox" / f"{run_id}.request.json"
        file_sha = _atomic_json(request_path, request)
        result = self.db.queue_research_run({
            "research_run_id": run_id, "cycle_id": prepared["cycle_id"],
            "manifest_id": prepared["manifest_id"], "provider": self.config.research_provider,
            "request_path": str(request_path), "request_sha256": request_sha,
        })
        if result.get("reused") and result["research_run_id"] != run_id:
            request_path.unlink(missing_ok=True)
        if force and not result.get("reused"):
            self.db.append_audit(
                "forced_research_requested", actor=actor,
                cycle_id=prepared["cycle_id"], subject_type="research_run",
                subject_id=result["research_run_id"],
                payload={"reason": reason, "idempotency_key": idempotency_key},
            )
        return {**result, "request_path": result.get("request_path", str(request_path)),
                "request_file_sha256": file_sha, "due": assessment}

    def import_ready(self) -> dict:
        self.db.migrate()
        outbox = self.config.research_root / "outbox"
        results = []
        for path in sorted(outbox.glob("research_*.result.json")):
            try:
                results.append(self._import_one(path))
            except Exception as exc:  # noqa: BLE001 - cada artefacto se aísla
                quarantine = self.config.research_root / "quarantine" / path.name
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                path.replace(quarantine)
                candidate_id = path.name.removesuffix(".result.json")
                if re.fullmatch(r"research_[0-9a-f]{32}", candidate_id):
                    self.db.reject_research_run(
                        candidate_id, error_code=type(exc).__name__,
                        error_detail=str(exc),
                    )
                results.append({"status": "rejected", "path": str(quarantine),
                                "error_code": type(exc).__name__,
                                "error": str(exc)[:500]})
        return {"status": "completed", "processed": len(results), "results": results}

    def _import_one(self, path: Path) -> dict:
        if path.stat().st_size > MAX_RESULT_BYTES:
            raise ValueError("resultado de investigación excede 1 MiB")
        raw = path.read_bytes()
        payload = json.loads(raw)
        run_id = _clean_text(
            payload.get("research_run_id"), field="research_run_id", maximum=80
        )
        if not re.fullmatch(r"research_[0-9a-f]{32}", run_id):
            raise ValueError("research_run_id inválido")
        run = self.db.research_run(run_id)
        if not run:
            raise ValueError("research_run no registrado")
        if payload.get("schema") != "mova-research-brief-v1":
            raise ValueError("schema de resultado inválido")
        if payload.get("cycle_id") != run["cycle_id"]:
            raise ValueError("cycle_id no coincide")
        if payload.get("request_sha256") != run["request_sha256"]:
            raise ValueError("request_sha256 no coincide")
        observed = datetime.now(timezone.utc)
        documents = self._validate_documents(payload.get("documents"), observed)
        by_url = {item["source_url"]: item for item in documents}
        conflicts = self._validate_conflicts(payload.get("conflicts", []), by_url)
        conflict_keys = {(item["subject"].casefold(), item["claim_type"]) for item in conflicts
                         if item["status"] == "unresolved"}
        signals = self._validate_signals(
            payload.get("signals"), by_url, conflict_keys, observed,
        )
        normalized = {
            "schema": "mova-research-brief-v1", "research_run_id": run_id,
            "cycle_id": run["cycle_id"], "request_sha256": run["request_sha256"],
            "generated_at": _parse_time(
                payload.get("generated_at"), field="generated_at"
            ).isoformat(),
            "summary": _clean_text(payload.get("summary"), field="summary", maximum=3000),
            "documents": documents, "signals": signals, "conflicts": conflicts,
            "limitations": [
                _clean_text(item, field="limitation", maximum=500)
                for item in payload.get("limitations", [])[:20]
            ],
            "usage": self._validate_usage(payload.get("usage", {})),
        }
        result_sha = hashlib.sha256(raw).hexdigest()
        imported = self.db.import_research_result(
            run_id, normalized, result_path=str(path), result_sha256=result_sha,
        )
        archive = self.config.research_root / "archive" / path.name
        archive.parent.mkdir(parents=True, exist_ok=True)
        path.replace(archive)
        return {**imported, "archive_path": str(archive), "result_sha256": result_sha}

    @staticmethod
    def _validate_documents(value: object, observed: datetime) -> list[dict]:
        if not isinstance(value, list) or not 1 <= len(value) <= 80:
            raise ValueError("documents debe contener entre 1 y 80 fuentes")
        documents = []
        seen = set()
        for raw in value:
            if not isinstance(raw, dict):
                raise ValueError("document inválido")
            url = _safe_url(raw.get("source_url"))
            if url in seen:
                continue
            seen.add(url)
            tier = str(raw.get("source_tier"))
            if tier not in SOURCE_TIERS:
                raise ValueError("source_tier inválido")
            published = raw.get("published_at")
            if published:
                published_at = _parse_time(published, field="published_at")
                if published_at > observed + timedelta(minutes=10):
                    raise ValueError("published_at está en el futuro")
                published = published_at.isoformat()
            documents.append({
                "source_url": url,
                "title": _clean_text(raw.get("title"), field="title", maximum=300),
                "publisher": _clean_text(
                    raw.get("publisher"), field="publisher", maximum=120
                ),
                "published_at": published,
                "source_tier": tier,
            })
        return documents

    @staticmethod
    def _validate_conflicts(value: object, by_url: dict[str, dict]) -> list[dict]:
        if not isinstance(value, list) or len(value) > 40:
            raise ValueError("conflicts inválido")
        result = []
        for raw in value:
            urls = list(dict.fromkeys(_safe_url(url) for url in raw.get("source_urls", [])))
            if not urls or any(url not in by_url for url in urls):
                raise ValueError("conflicto referencia evidencia inexistente")
            claim_type = str(raw.get("claim_type"))
            if claim_type not in CLAIM_TYPES:
                raise ValueError("claim_type inválido")
            status = str(raw.get("status", "unresolved"))
            if status not in {"unresolved", "resolved"}:
                raise ValueError("status de conflicto inválido")
            result.append({
                "subject": _clean_text(raw.get("subject"), field="subject", maximum=160),
                "claim_type": claim_type,
                "description": _clean_text(
                    raw.get("description"), field="description", maximum=1000
                ),
                "source_urls": urls, "status": status,
            })
        return result

    @staticmethod
    def _validate_signals(value: object, by_url: dict[str, dict],
                          conflict_keys: set[tuple[str, str]],
                          observed: datetime) -> list[dict]:
        if not isinstance(value, list) or len(value) > 120:
            raise ValueError("signals inválido")
        signals = []
        for raw in value:
            urls = list(dict.fromkeys(_safe_url(url) for url in raw.get("source_urls", [])))
            if not urls or any(url not in by_url for url in urls):
                raise ValueError("señal referencia evidencia inexistente")
            claim_type = str(raw.get("claim_type"))
            direction = str(raw.get("direction"))
            if claim_type not in CLAIM_TYPES or direction not in DIRECTIONS:
                raise ValueError("taxonomía de señal inválida")
            subject = _clean_text(
                raw.get("subject_name"), field="subject_name", maximum=160
            )
            confidence = float(raw.get("confidence"))
            if not 0 <= confidence <= 1:
                raise ValueError("confidence fuera de rango")
            expires = _parse_time(raw.get("expires_at"), field="expires_at")
            if expires <= observed - timedelta(minutes=5):
                raise ValueError("señal ya expirada")
            element = raw.get("player_element")
            if element is not None and (not isinstance(element, int) or element <= 0):
                raise ValueError("player_element inválido")
            source_tier = min(
                (by_url[url]["source_tier"] for url in urls),
                key=("official", "tier1", "tier2", "other").index,
            )
            has_strong_evidence = source_tier == "official" or len(urls) >= 2
            conflicted = (subject.casefold(), claim_type) in conflict_keys
            validation = "accepted" if has_strong_evidence and not conflicted else "candidate"
            signals.append({
                "subject_name": subject, "player_element": element,
                "claim_type": claim_type,
                "claim_text": _clean_text(
                    raw.get("claim_text"), field="claim_text", maximum=1000
                ),
                "direction": direction, "confidence": confidence,
                "source_urls": urls, "source_tier": source_tier,
                "published_at": by_url[urls[0]].get("published_at"),
                "expires_at": expires.isoformat(),
                "conflict_status": "unresolved" if conflicted else "none",
                "validation_status": validation,
            })
        return signals

    @staticmethod
    def _validate_usage(value: object) -> dict:
        raw = value if isinstance(value, dict) else {}
        usage = {"model": str(raw.get("model", "unknown"))[:120]}
        for key in ("input_tokens", "output_tokens"):
            item = raw.get(key)
            usage[key] = int(item) if item is not None and int(item) >= 0 else None
        usage["estimated_cost_usd"] = None
        usage["billing"] = "chatgpt_subscription"
        return usage
