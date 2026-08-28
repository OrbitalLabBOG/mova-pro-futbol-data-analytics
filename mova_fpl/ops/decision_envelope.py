"""Contrato determinista entre el engine, la estrategia y cualquier executor.

El LLM nunca construye este objeto. El engine propone candidatos tipados y este
módulo puro enlaza inputs, comparadores y gates para producir un artefacto de
replay. Un envelope bloqueado sigue siendo evidencia útil, pero no es operable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from mova_fpl.ops.schedule import private_state_cadence_seconds

SCHEMA = "mova-decision-envelope-v1"
POLICY_VERSION = "decision-envelope-1.0.0"
REQUIRED_CANDIDATES = {"do_nothing", "milp_baseline", "primary_alternative"}
IRREVERSIBLE_PHASES = {"refresh", "preflight", "freeze", "execution_window"}


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def decision_fingerprint(payload: dict) -> str:
    """Recalcula la huella pública de Decision sin importar el engine en ops."""
    body = {
        "season": str(payload["season"]),
        "gw": int(payload["gw"]),
        "squad_15": sorted(int(value) for value in payload["squad_15"]),
        "starters": sorted(int(value) for value in payload["starters"]),
        "captain": int(payload["captain"]) if payload.get("captain") is not None else None,
        "vice_captain": (
            int(payload["vice_captain"])
            if payload.get("vice_captain") is not None else None
        ),
        "bench_order": [int(value) for value in payload["bench_order"]],
        "transfers_in": sorted(int(value) for value in payload.get("transfers_in", ())),
        "transfers_out": sorted(int(value) for value in payload.get("transfers_out", ())),
        "hits": int(payload.get("hits", 0)),
        "chip": payload.get("chip"),
    }
    # Debe reproducir exactamente Decision.fingerprint(), incluido el encoding
    # estándar de json.dumps; cambiar separadores rompería huellas históricas.
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _parse_time(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp sin zona horaria")
    return parsed.astimezone(timezone.utc)


def _check(code: str, passed: bool, severity: str, summary: str, **detail) -> dict:
    if severity not in {"info", "warning", "block"}:
        raise ValueError(f"severidad inválida: {severity}")
    return {
        "code": code,
        "passed": bool(passed),
        "severity": severity,
        "summary": summary,
        "detail": detail,
    }


def validate_decision_shape(payload: dict) -> list[dict]:
    """Valida invariantes que no dependen del mercado ni de un modelo."""
    try:
        squad_values = tuple(int(value) for value in payload["squad_15"])
        starter_values = tuple(int(value) for value in payload["starters"])
        bench_values = tuple(int(value) for value in payload["bench_order"])
        captain = int(payload["captain"]) if payload.get("captain") is not None else None
        vice = int(payload["vice_captain"]) if payload.get("vice_captain") is not None else None
        transfers_in = tuple(int(value) for value in payload.get("transfers_in", ()))
        transfers_out = tuple(int(value) for value in payload.get("transfers_out", ()))
        hits = int(payload.get("hits", 0))
        expected = payload.get("fingerprint")
        if expected is not None and str(expected) != decision_fingerprint(payload):
            raise ValueError("fingerprint de Decision no coincide con su contenido")
    except (KeyError, TypeError, ValueError) as exc:
        return [{"code": "DECISION_CONTRACT_INVALID", "detail": str(exc)}]
    errors: list[dict] = []
    squad, starters, bench = set(squad_values), set(starter_values), set(bench_values)
    if len(squad_values) != 15 or len(squad) != 15:
        errors.append({"code": "SQUAD_SIZE", "detail": "se requieren 15 elementos únicos"})
    if len(starter_values) != 11 or len(starters) != 11:
        errors.append({"code": "STARTERS_COUNT", "detail": "se requieren 11 titulares únicos"})
    if len(bench_values) != 4 or len(bench) != 4:
        errors.append({"code": "BENCH_COUNT", "detail": "se requieren 4 suplentes únicos"})
    if not starters <= squad or not bench <= squad or starters & bench or starters | bench != squad:
        errors.append({"code": "LINEUP_PARTITION", "detail": "XI y banca no particionan plantilla"})
    if captain not in starters or vice not in starters:
        errors.append({"code": "CAPTAIN_NOT_STARTING", "detail": "C/V deben estar en el XI"})
    if captain == vice:
        errors.append({"code": "CAPTAIN_IS_VICE", "detail": "C y V deben ser distintos"})
    if len(transfers_in) != len(transfers_out):
        errors.append({"code": "TRANSFER_PAIRING", "detail": "entradas y salidas no cuadran"})
    if set(transfers_in) - squad:
        errors.append({"code": "TRANSFER_IN_NOT_OWNED", "detail": "entrada ausente del squad final"})
    if set(transfers_out) & squad:
        errors.append({"code": "TRANSFER_OUT_STILL_OWNED", "detail": "salida sigue en squad final"})
    if hits < 0 or hits > len(transfers_in):
        errors.append({
            "code": "HIT_COUNT_INVALID",
            "detail": "hits es el número de transferencias pagadas y no puede superar entradas",
        })
    return errors


def _selected(bundle: dict) -> dict:
    key = str(bundle.get("selected_candidate_key") or "milp_baseline")
    candidates = {str(item.get("candidate_key")): item for item in bundle.get("candidates", [])}
    if key not in candidates:
        raise ValueError(f"candidato seleccionado ausente: {key}")
    return candidates[key]


def _comparisons(candidates: list[dict]) -> list[dict]:
    by_key = {str(item["candidate_key"]): item for item in candidates}
    base = by_key["do_nothing"]["decision"]
    rows = []
    for key in ("milp_baseline", "primary_alternative"):
        decision = by_key[key]["decision"]
        rows.append({
            "candidate_key": key,
            "versus": "do_nothing",
            "expected_points_delta": round(
                float(decision["expected_points"]) - float(base["expected_points"]), 2
            ),
            "fingerprint_changed": decision_fingerprint(decision) != decision_fingerprint(base),
            "transfers": len(decision.get("transfers_in") or ()),
            "hits": int(decision.get("hits") or 0),
            "chip": decision.get("chip"),
        })
    return rows


def build_envelope(*, bundle: dict, manifest: dict, manifest_id: str,
                   manifest_sha256: str, controls: dict) -> dict:
    """Sella un envelope reproducible y aplica gates sin IO ni heurística LLM."""
    if bundle.get("schema") != "mova-live-decision-candidates-v1":
        raise ValueError("bundle de candidatos ausente o incompatible")
    selected = _selected(bundle)
    decision = selected["decision"]
    candidates = list(bundle.get("candidates") or [])
    keys = {str(item.get("candidate_key")) for item in candidates}
    checks: list[dict] = []

    cycle_ok = (
        str(bundle.get("season")) == str(manifest.get("season")) == str(decision["season"])
        and int(bundle.get("gw", 0)) == int(manifest.get("gw", 0)) == int(decision["gw"])
        and len(str(manifest_sha256)) == 64
    )
    checks.append(_check(
        "CYCLE_MANIFEST_BOUND", cycle_ok, "block",
        "bundle y decisión pertenecen al manifest sellado",
        manifest_id=manifest_id, manifest_sha256=manifest_sha256,
    ))

    checks.append(_check(
        "REQUIRED_COMPARATORS_PRESENT", keys == REQUIRED_CANDIDATES, "block",
        "existen do_nothing, baseline y alternativa principal",
        observed=sorted(keys), required=sorted(REQUIRED_CANDIDATES),
    ))

    shape_errors = validate_decision_shape(selected["decision"])
    engine_errors = list(selected.get("violations") or [])
    checks.append(_check(
        "SELECTED_DECISION_LEGAL", not shape_errors and not engine_errors, "block",
        "la decisión seleccionada cumple contrato y reglas del engine",
        contract_errors=shape_errors, engine_errors=engine_errors,
    ))

    team_bundle = dict(bundle.get("team_state") or {})
    transfers = len(decision.get("transfers_in") or ())
    free_transfers = int(team_bundle.get("free_transfers") or 0)
    expected_hits = (
        0 if decision.get("chip") in {"wildcard", "free_hit"}
        else max(0, transfers - free_transfers)
    )
    hit_accounting_ok = int(decision.get("hits") or 0) == expected_hits
    checks.append(_check(
        "TRANSFER_COST_ACCOUNTED", hit_accounting_ok, "block",
        "hits coincide con transferencias, libres y exención de chip",
        transfers=transfers, free_transfers=free_transfers,
        observed_hits=int(decision.get("hits") or 0), expected_hits=expected_hits,
        chip=decision.get("chip"),
    ))

    event_context = dict(bundle.get("event_context") or {})
    prior_ready = not bool(event_context.get("preliminary"))
    checks.append(_check(
        "PRIOR_GAMEWEEK_SETTLED", prior_ready, "block",
        "la jornada previa está finished y data_checked",
        reasons=event_context.get("readiness_reasons") or [],
        prior_gw=event_context.get("prior_gw"),
    ))

    team = dict(manifest.get("team_state") or {})
    try:
        manifest_time = _parse_time(manifest["as_of_at"])
        observed_time = _parse_time(team["observed_at"])
        age_seconds = max(0, int((manifest_time - observed_time).total_seconds()))
        max_age_seconds = private_state_cadence_seconds(manifest["deadline_at"], manifest_time)
    except (KeyError, TypeError, ValueError):
        age_seconds, max_age_seconds = None, None
    team_fresh = (
        team.get("quality_status") == "valid"
        and bool(manifest.get("team_state_id"))
        and age_seconds is not None and max_age_seconds is not None
        and age_seconds <= max_age_seconds
        and team.get("fingerprint") == (bundle.get("team_state") or {}).get("fingerprint")
    )
    checks.append(_check(
        "TEAM_STATE_FRESH", team_fresh, "block",
        "estado autenticado válido, fresco y consistente con el solve",
        team_state_id=manifest.get("team_state_id"), age_seconds=age_seconds,
        max_age_seconds=max_age_seconds,
    ))

    analytics = dict(manifest.get("analytics_manifest") or {})
    analytics_ready = (
        analytics.get("status") == "approved"
        and int(analytics.get("target_gw") or analytics.get("gw") or 0) == int(decision["gw"])
        and int(analytics.get("player_count") or 0) > 0
    )
    checks.append(_check(
        "ANALYTICS_APPROVED_CAUSAL", analytics_ready, "block",
        "hay una proyección aprobada y causal para la jornada",
        batch_id=analytics.get("batch_id"), status=analytics.get("status"),
        target_gw=analytics.get("target_gw"), cutoff_at=analytics.get("cutoff_at"),
    ))

    research = dict(manifest.get("research_summary") or {})
    conflicts = int(research.get("unresolved_conflicts") or 0)
    checks.append(_check(
        "RESEARCH_CONFLICTS_CLEAR", conflicts == 0, "block",
        "no quedan conflictos materiales de research sin resolver",
        unresolved_conflicts=conflicts,
    ))

    irreversible = bool(
        decision.get("transfers_in") or decision.get("hits") or decision.get("chip")
    )
    phase = str(manifest.get("phase") or "")
    window_ok = not irreversible or phase in IRREVERSIBLE_PHASES
    checks.append(_check(
        "IRREVERSIBLE_ACTION_WINDOW", window_ok, "block",
        "transfers, hits y chips solo maduran dentro de la ventana operativa",
        phase=phase, irreversible=irreversible, allowed_phases=sorted(IRREVERSIBLE_PHASES),
    ))

    plan_ok = bool(manifest.get("plan_id"))
    checks.append(_check(
        "SEASON_PLAN_BOUND", plan_ok or not irreversible,
        "block" if irreversible else "warning",
        "la acción irreversible está contrastada contra un plan de temporada",
        plan_id=manifest.get("plan_id"), irreversible=irreversible,
    ))

    controls_ok = (
        controls.get("mode") == "shadow"
        and controls.get("action_level") == "A0"
        and controls.get("browser_writes") is False
        and controls.get("kill_switch") is True
    )
    checks.append(_check(
        "SHADOW_CONTROLS_ENFORCED", controls_ok, "block",
        "HV1-06A permanece sin autoridad de ejecución",
        controls=controls,
    ))

    blocked = [item["code"] for item in checks if not item["passed"] and item["severity"] == "block"]
    status = "blocked" if blocked else "staged"
    body = {
        "schema": SCHEMA,
        "policy_version": POLICY_VERSION,
        "cycle_id": str(manifest["cycle_id"]),
        "season": str(decision["season"]),
        "gw": int(decision["gw"]),
        "mode": "shadow",
        "status": status,
        "manifest": {
            "manifest_id": manifest_id,
            "content_sha256": manifest_sha256,
            "revision": manifest.get("revision"),
            "as_of_at": manifest.get("as_of_at"),
        },
        "selected_candidate_key": str(bundle["selected_candidate_key"]),
        "selected_fingerprint": decision_fingerprint(decision),
        "candidates": candidates,
        "comparisons": _comparisons(candidates),
        "validation": {"status": status, "blocking_codes": blocked, "checks": checks},
        "controls": controls,
        "engine": dict(bundle.get("engine") or {}),
        "event_context": event_context,
        "team_state": dict(bundle.get("team_state") or {}),
        "report_artifact": bundle.get("report_artifact"),
    }
    # El manifest puede incorporar valores tipados por el driver de SQLite
    # (por ejemplo TIMESTAMP -> datetime). El envelope es un contrato JSON y no
    # debe depender de la representación interna del adaptador de persistencia.
    body = json.loads(canonical_json(body))
    content_sha = sha256_json(body)
    return {
        **body,
        "envelope_id": f"envelope_{content_sha[:24]}",
        "content_sha256": content_sha,
    }
