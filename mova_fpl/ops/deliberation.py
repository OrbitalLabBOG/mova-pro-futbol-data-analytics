"""Deliberación acotada sobre un DecisionEnvelope inmutable.

Strategist y Critic son asesores: producen análisis estructurado y una propuesta
de ``Intervention`` en shadow. Este módulo valida el resultado sin importar el
engine ni aplicar la intervención. El MILP y los hard gates conservan toda la
autoridad sobre la decisión deportiva.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, canonical_json, sha256_json, utcnow

REQUEST_SCHEMA = "mova-decision-deliberation-request-v1"
RESULT_SCHEMA = "mova-decision-deliberation-v1"
POLICY_VERSION = "bounded-deliberation-1.0.0"
MAX_RESULT_BYTES = 1_048_576
CHIPS = {"wildcard", "free_hit", "bench_boost", "triple_captain"}
VERDICTS = {"accept", "revise", "block"}
SEVERITIES = {"info", "warning", "block"}
LIFECYCLE_BY_VERDICT = {
    "accept": "accepted", "revise": "review_required", "block": "blocked",
}


def _atomic_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (canonical_json(payload) + "\n").encode("utf-8")
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    temporary.write_bytes(encoded)
    temporary.chmod(0o640)
    temporary.replace(path)
    return hashlib.sha256(encoded).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object, *, field: str, maximum: int) -> str:
    result = re.sub(r"\s+", " ", str(value)).strip()
    if not result or len(result) > maximum:
        raise ValueError(f"{field} vacío o supera {maximum} caracteres")
    return result


def _text_list(value: object, *, field: str, maximum: int = 500,
               limit: int = 20) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{field} inválido")
    return [_text(item, field=field, maximum=maximum) for item in value]


def _time(value: object, *, field: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} inválido") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} debe incluir zona horaria")
    return parsed.astimezone(timezone.utc).isoformat()


def _usage(value: object) -> dict:
    raw = value if isinstance(value, dict) else {}
    usage = {"model": str(raw.get("model", "unknown"))[:120]}
    for key in ("input_tokens", "output_tokens", "duration_ms", "search_requests"):
        item = raw.get(key)
        usage[key] = int(item) if item is not None and int(item) >= 0 else None
    usage["estimated_cost_usd"] = None
    usage["billing"] = "chatgpt_subscription"
    return usage


def _normalize_intervention(raw: object, request: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("strategist.intervention inválida")
    allowed_fields = {
        "gw", "author", "rationale", "xp_multiplier", "allow_chips",
        "block_chips", "lock_in", "lock_out", "risk_lambda",
    }
    extras = set(raw) - allowed_fields
    if extras:
        raise ValueError(f"campos de Intervention no permitidos: {sorted(extras)}")
    gw = int(raw.get("gw"))
    if gw != int(request["gw"]):
        raise ValueError("Intervention pertenece a otra GW")
    if str(raw.get("author")) != "strategist":
        raise ValueError("Intervention.author debe ser strategist")
    allowed = {int(value) for value in request["allowed_player_elements"]}
    owned = {int(value) for value in request["owned_player_elements"]}
    multiplier_raw = raw.get("xp_multiplier") or {}
    if isinstance(multiplier_raw, list):
        multiplier_items = [
            (item.get("player_element"), item.get("factor"))
            for item in multiplier_raw if isinstance(item, dict)
        ]
        if len(multiplier_items) != len(multiplier_raw):
            raise ValueError("xp_multiplier contiene una fila inválida")
    elif isinstance(multiplier_raw, dict):
        multiplier_items = list(multiplier_raw.items())
    else:
        raise ValueError("xp_multiplier inválido")
    if len(multiplier_items) > 12:
        raise ValueError("xp_multiplier inválido o demasiado amplio")
    multipliers: dict[str, float] = {}
    for key, value in multiplier_items:
        element = int(key)
        factor = float(value)
        if element not in allowed:
            raise ValueError(f"element {element} fuera del contexto sellado")
        if not 0.0 <= factor <= 1.5:
            raise ValueError(f"factor {factor} fuera del rango shadow [0,1.5]")
        if str(element) in multipliers:
            raise ValueError(f"element {element} repetido en xp_multiplier")
        multipliers[str(element)] = factor

    def elements(name: str, *, must_be_owned: bool = False) -> list[int]:
        values = raw.get(name) or []
        if not isinstance(values, list) or len(values) > 12:
            raise ValueError(f"{name} inválido")
        result = sorted({int(value) for value in values})
        universe = owned if must_be_owned else allowed
        if set(result) - universe:
            raise ValueError(f"{name} contiene jugadores fuera del contexto permitido")
        return result

    allow_chips = sorted(set(raw.get("allow_chips") or []))
    block_chips = sorted(set(raw.get("block_chips") or []))
    if (set(allow_chips) | set(block_chips)) - CHIPS:
        raise ValueError("Intervention contiene chip desconocido")
    if set(allow_chips) & set(block_chips):
        raise ValueError("Intervention autoriza y bloquea el mismo chip")
    lock_in = elements("lock_in", must_be_owned=True)
    lock_out = elements("lock_out")
    if set(lock_in) & set(lock_out):
        raise ValueError("Intervention protege y veta el mismo jugador")
    risk_lambda = raw.get("risk_lambda")
    if risk_lambda is not None:
        risk_lambda = float(risk_lambda)
        if not 0.0 <= risk_lambda <= 1.0:
            raise ValueError("risk_lambda fuera del rango shadow [0,1]")
    nonempty = bool(
        multipliers or allow_chips or block_chips or lock_in or lock_out
        or risk_lambda is not None
    )
    rationale = str(raw.get("rationale") or "").strip()
    if nonempty:
        rationale = _text(rationale, field="intervention.rationale", maximum=2000)
    return {
        "gw": gw,
        "author": "strategist",
        "rationale": rationale,
        "xp_multiplier": dict(sorted(multipliers.items(), key=lambda item: int(item[0]))),
        "allow_chips": allow_chips,
        "block_chips": block_chips,
        "lock_in": lock_in,
        "lock_out": lock_out,
        "risk_lambda": risk_lambda,
        "policy_version": POLICY_VERSION,
        "shadow_only": True,
        "applied": False,
    }


def normalize_result(payload: dict, request: dict) -> dict:
    """Valida enlaces, cobertura y guardrails; no confía en el JSON Schema del worker."""
    if payload.get("schema") != RESULT_SCHEMA:
        raise ValueError("schema de deliberación inválido")
    for key in ("deliberation_id", "cycle_id", "envelope_id", "request_sha256"):
        if str(payload.get(key)) != str(request.get(key)):
            raise ValueError(f"{key} no coincide con la request sellada")
    candidate_keys = {
        str(item["candidate_key"]) for item in request["envelope"]["candidates"]
    }
    strategist = payload.get("strategist")
    if not isinstance(strategist, dict):
        raise ValueError("strategist ausente")
    preferred = str(strategist.get("preferred_candidate_key"))
    if preferred not in candidate_keys:
        raise ValueError("preferred_candidate_key no existe en el envelope")
    confidence = float(strategist.get("confidence"))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("strategist.confidence fuera de rango")
    tradeoffs_raw = strategist.get("tradeoffs")
    if not isinstance(tradeoffs_raw, list) or len(tradeoffs_raw) != len(candidate_keys):
        raise ValueError("tradeoffs debe cubrir todos los candidatos exactamente una vez")
    tradeoffs = []
    seen = set()
    for row in tradeoffs_raw:
        key = str(row.get("candidate_key"))
        if key not in candidate_keys or key in seen:
            raise ValueError("tradeoff referencia candidato ausente o duplicado")
        seen.add(key)
        tradeoffs.append({
            "candidate_key": key,
            "advantages": _text_list(row.get("advantages"), field="advantages", limit=10),
            "disadvantages": _text_list(
                row.get("disadvantages"), field="disadvantages", limit=10
            ),
        })
    if seen != candidate_keys:
        raise ValueError("tradeoffs incompletos")
    intervention = _normalize_intervention(strategist.get("intervention"), request)
    normalized_strategist = {
        "summary": _text(strategist.get("summary"), field="strategist.summary", maximum=3000),
        "preferred_candidate_key": preferred,
        "confidence": confidence,
        "horizon_assessment": _text_list(
            strategist.get("horizon_assessment"), field="horizon_assessment", limit=20
        ),
        "tradeoffs": sorted(tradeoffs, key=lambda item: item["candidate_key"]),
        "intervention": intervention,
    }

    critic = payload.get("critic")
    if not isinstance(critic, dict):
        raise ValueError("critic ausente")
    verdict = str(critic.get("verdict"))
    if verdict not in VERDICTS:
        raise ValueError("critic.verdict inválido")
    critic_confidence = float(critic.get("confidence"))
    if not 0.0 <= critic_confidence <= 1.0:
        raise ValueError("critic.confidence fuera de rango")
    risks_raw = critic.get("risks")
    if not isinstance(risks_raw, list) or len(risks_raw) > 40:
        raise ValueError("critic.risks inválido")
    risks = []
    risk_codes = set()
    blocking_risk_codes = set()
    for row in risks_raw:
        code = str(row.get("code") or "")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,79}", code) or code in risk_codes:
            raise ValueError("risk code inválido o duplicado")
        severity = str(row.get("severity"))
        if severity not in SEVERITIES:
            raise ValueError("risk severity inválida")
        candidate = row.get("candidate_key")
        if candidate is not None and str(candidate) not in candidate_keys:
            raise ValueError("risk referencia candidato ausente")
        risk_codes.add(code)
        if severity == "block":
            blocking_risk_codes.add(code)
        risks.append({
            "code": code,
            "severity": severity,
            "candidate_key": str(candidate) if candidate is not None else None,
            "claim": _text(row.get("claim"), field="risk.claim", maximum=1000),
            "mitigation": _text(
                row.get("mitigation"), field="risk.mitigation", maximum=1000
            ),
        })
    envelope_blockers = set(
        request["envelope"].get("validation", {}).get("blocking_codes") or []
    )
    if envelope_blockers - blocking_risk_codes:
        raise ValueError("Critic omitió blockers deterministas del envelope")
    if (envelope_blockers or blocking_risk_codes) and verdict != "block":
        raise ValueError("Critic debe bloquear cuando existe un hard blocker")
    followups = _text_list(
        critic.get("required_followups"), field="required_followups", limit=20
    )
    if verdict == "block" and not followups:
        raise ValueError("un verdict block exige required_followups")
    normalized_critic = {
        "verdict": verdict,
        "summary": _text(critic.get("summary"), field="critic.summary", maximum=3000),
        "confidence": critic_confidence,
        "risks": sorted(risks, key=lambda item: item["code"]),
        "challenged_assumptions": _text_list(
            critic.get("challenged_assumptions"), field="challenged_assumptions", limit=20
        ),
        "required_followups": followups,
    }
    body = {
        "schema": RESULT_SCHEMA,
        "policy_version": POLICY_VERSION,
        "deliberation_id": request["deliberation_id"],
        "cycle_id": request["cycle_id"],
        "envelope_id": request["envelope_id"],
        "manifest_id": request["manifest_id"],
        "request_sha256": request["request_sha256"],
        "generated_at": _time(payload.get("generated_at"), field="generated_at"),
        "status": LIFECYCLE_BY_VERDICT[verdict],
        "strategist": normalized_strategist,
        "critic": normalized_critic,
        "limitations": _text_list(payload.get("limitations"), field="limitations", limit=20),
        "usage": _usage(payload.get("usage")),
    }
    return {**body, "content_sha256": sha256_json(body)}


class DecisionDeliberationService:
    def __init__(self, config: RuntimeConfig, db: OpsDB):
        self.config = config
        self.db = db

    def enqueue(self) -> dict:
        self.db.migrate()
        source = self.db.deliberation_source()
        if not source:
            return {"status": "skipped", "reason": "no_current_decision_envelope"}
        existing = self.db.decision_deliberation_for_envelope(source["envelope_id"])
        if existing:
            return {**existing, "reused": True}
        artifact = Path(source["artifact_path"])
        if not artifact.is_file() or artifact.stat().st_size > MAX_RESULT_BYTES:
            raise ValueError("artefacto DecisionEnvelope ausente o demasiado grande")
        if _sha_file(artifact) != source["artifact_sha256"]:
            raise ValueError("SHA del DecisionEnvelope no coincide")
        envelope = json.loads(artifact.read_text(encoding="utf-8"))
        if (envelope.get("envelope_id") != source["envelope_id"]
                or envelope.get("content_sha256") != source["content_sha256"]
                or envelope.get("manifest", {}).get("content_sha256")
                != source["manifest_sha256"]):
            raise ValueError("artefacto DecisionEnvelope no coincide con ops.db")
        manifest = self.db.latest_cycle_manifest(source["cycle_id"])
        if not manifest or manifest["manifest_id"] != source["manifest_id"]:
            raise ValueError("CycleManifest del envelope no está disponible")
        plan = self.db.active_season_plan(source["season"])
        candidate_elements = {
            int(element)
            for candidate in envelope["candidates"]
            for element in candidate["decision"]["squad_15"]
        }
        embedded_signals = manifest.get("research_summary", {}).get(
            "previous_active_signals", []
        )
        signal_elements = {
            int(item["player_element"]) for item in embedded_signals
            if item.get("player_element") is not None
        }
        do_nothing = next(
            item["decision"] for item in envelope["candidates"]
            if item["candidate_key"] == "do_nothing"
        )
        deliberation_id = "deliberation_" + hashlib.sha256(
            source["envelope_id"].encode("utf-8")
        ).hexdigest()[:32]
        request = {
            "schema": REQUEST_SCHEMA,
            "deliberation_id": deliberation_id,
            "cycle_id": source["cycle_id"],
            "season": source["season"],
            "gw": int(source["gw"]),
            "envelope_id": source["envelope_id"],
            "manifest_id": source["manifest_id"],
            "manifest_sha256": source["manifest_sha256"],
            "requested_at": utcnow(),
            "provider": self.config.research_provider,
            "envelope": envelope,
            "cycle_context": {
                "phase": manifest["phase"],
                "deadline_at": manifest["deadline_at"],
                "analytics_manifest": manifest["analytics_manifest"],
                "research_summary": manifest["research_summary"],
                "strategic_memory": manifest.get("memory_summary", {}),
                "season_plan": plan,
            },
            "owned_player_elements": sorted(int(value) for value in do_nothing["squad_15"]),
            "allowed_player_elements": sorted(candidate_elements | signal_elements),
            "guardrails": {
                "advisory_only": True,
                "intervention_shadow_only": True,
                "no_decision_mutation": True,
                "no_external_actions": True,
                "no_new_facts": True,
                "critic_must_preserve_hard_blockers": True,
                "agent_budget": self.config.agent_budget_policy(),
            },
        }
        request_sha = sha256_json(request)
        request["request_sha256"] = request_sha
        path = self.config.research_root / "inbox" / f"{deliberation_id}.request.json"
        file_sha = _atomic_json(path, request)
        queued = self.db.queue_decision_deliberation({
            "deliberation_id": deliberation_id,
            "cycle_id": source["cycle_id"],
            "envelope_id": source["envelope_id"],
            "manifest_id": source["manifest_id"],
            "provider": self.config.research_provider,
            "request_path": str(path),
            "request_sha256": request_sha,
            "budget_policy": self.config.agent_budget_policy(),
        })
        if queued.get("status") == "blocked":
            path.unlink(missing_ok=True)
            return {**queued, "request_path": None, "request_file_sha256": None}
        return {**queued, "request_path": str(path), "request_file_sha256": file_sha}

    def import_ready(self) -> dict:
        self.db.migrate()
        outbox = self.config.research_root / "outbox"
        results = []
        for path in sorted(outbox.glob("deliberation_*.result.json")):
            try:
                results.append(self._import_one(path))
            except Exception as exc:  # cada output no confiable se aísla
                quarantine = self.config.research_root / "quarantine" / path.name
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                path.replace(quarantine)
                candidate_id = path.name.removesuffix(".result.json")
                if re.fullmatch(r"deliberation_[0-9a-f]{32}", candidate_id):
                    self.db.reject_decision_deliberation(
                        candidate_id, error_code=type(exc).__name__, error_detail=str(exc)
                    )
                results.append({
                    "status": "rejected", "path": str(quarantine),
                    "error_code": type(exc).__name__, "error": str(exc)[:500],
                })
        return {"status": "completed", "processed": len(results), "results": results}

    def _import_one(self, path: Path) -> dict:
        if path.stat().st_size > MAX_RESULT_BYTES:
            raise ValueError("resultado de deliberación excede 1 MiB")
        raw = path.read_bytes()
        payload = json.loads(raw)
        deliberation_id = str(payload.get("deliberation_id") or "")
        if not re.fullmatch(r"deliberation_[0-9a-f]{32}", deliberation_id):
            raise ValueError("deliberation_id inválido")
        run = self.db.decision_deliberation(deliberation_id)
        if not run:
            raise ValueError("deliberación no registrada")
        request_path = Path(run["request_path"])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if sha256_json({key: value for key, value in request.items()
                        if key != "request_sha256"}) != run["request_sha256"]:
            raise ValueError("request sellada no coincide")
        normalized = normalize_result(payload, request)
        archive = self.config.research_root / "archive" / path.name
        archive.parent.mkdir(parents=True, exist_ok=True)
        imported = self.db.import_decision_deliberation(
            deliberation_id, normalized, result_path=str(archive),
            result_sha256=hashlib.sha256(raw).hexdigest(),
        )
        path.replace(archive)
        if request_path.is_file():
            request_path.replace(archive.with_name(request_path.name))
        return {
            **imported, "archive_path": str(archive),
            "content_sha256": normalized["content_sha256"],
        }
