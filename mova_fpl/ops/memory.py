"""Memoria del modelo copiloto (ADR-021): notas por GW y lectura consolidada.

`strategy_notes` es append-only. Una nota `decision` registra lo que el owner
aprobó para una GW (XI/C/VC/transfers/chip y razones) aunque no exista paquete
`record-manual` v2 (p. ej. sesión FPL privada rota). No concede autoridad ni
sustituye la evidencia verificada; es memoria para el siguiente brief y la review.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from mova_fpl.ops.db import OpsDB

NOTE_SCHEMA = "mova-strategy-note-v1"
MEMORY_SCHEMA = "mova-memory-v1"
NOTE_KINDS = ("reason", "owner_preference", "hypothesis", "constraint",
              "post_mortem", "decision")
NOTE_SOURCES = ("owner", "assistant")
MAX_TEXT = 2000
MAX_PLAYERS_BYTES = 16_384
DECISION_KEYS = frozenset({
    "xi", "bench", "captain", "vice_captain", "transfers_in", "transfers_out",
    "hits", "chip", "squad", "notes",
})

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_URL_QUERY = re.compile(r"(https?://[^\s?#]+)[?#][^\s]*", re.IGNORECASE)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{8,}")
_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|passw(?:or)?d|pwd|cookie|"
    r"session(?:id)?|csrf\w*)\s*[:=]\s*\S+"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}(?:\.[A-Za-z0-9_\-]+)?")
_PREFIXED = re.compile(r"\b(?:sk|pk|ghp|gho|xox[abp])[-_][A-Za-z0-9_\-]{12,}")
_OPAQUE = re.compile(r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{40,}\b")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(value: str) -> tuple[str, int]:
    """Redacta emails, credenciales y query strings; devuelve (texto, redacciones)."""
    text = _CONTROL.sub("", str(value)).strip()
    total = 0
    for pattern, replacement in (
        (_BEARER, "[redacted-credential]"),
        (_ASSIGNMENT, r"\1=[redacted]"),
        (_JWT, "[redacted-credential]"),
        (_PREFIXED, "[redacted-credential]"),
        (_EMAIL, "[redacted-email]"),
        (_URL_QUERY, r"\1"),
        (_OPAQUE, "[redacted-opaque]"),
    ):
        text, count = pattern.subn(replacement, text)
        total += count
    return text, total


def _sanitize_json(value, counter: list[int]):
    if isinstance(value, str):
        clean, count = sanitize_text(value)
        counter[0] += count
        return clean
    if isinstance(value, list):
        return [_sanitize_json(item, counter) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_json(item, counter) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError("players_json solo admite JSON plano")


def _validate_decision_players(players) -> None:
    if not isinstance(players, dict):
        raise ValueError("una nota decision exige players_json objeto (xi, captain, ...)")
    unknown = set(players) - DECISION_KEYS
    if unknown:
        raise ValueError(f"claves desconocidas en decision: {sorted(unknown)}")
    xi = players.get("xi")
    if xi is not None and (not isinstance(xi, list) or len(xi) != 11):
        raise ValueError("decision.xi debe listar 11 jugadores")
    bench = players.get("bench")
    if bench is not None and (not isinstance(bench, list) or len(bench) != 4):
        raise ValueError("decision.bench debe listar 4 jugadores")
    if not any(players.get(key) is not None for key in ("xi", "captain", "transfers_in", "chip")):
        raise ValueError("decision exige al menos xi, captain, transfers_in o chip")
    captain, vice = players.get("captain"), players.get("vice_captain")
    if captain is not None and vice is not None and captain == vice:
        raise ValueError("capitán y vicecapitán deben ser distintos")
    if xi is not None:
        for role, player in (("captain", captain), ("vice_captain", vice)):
            if player is not None and player not in xi:
                raise ValueError(f"{role} debe ser titular del xi declarado")
    for key in ("transfers_in", "transfers_out"):
        if players.get(key) is not None and not isinstance(players[key], list):
            raise ValueError(f"decision.{key} debe ser lista")
    if len(players.get("transfers_in") or ()) != len(players.get("transfers_out") or ()):
        raise ValueError("transfers_in/transfers_out desbalanceados")
    hits = players.get("hits", 0)
    if not isinstance(hits, int) or hits < 0 or hits % 4:
        raise ValueError("hits debe ser coste no negativo múltiplo de cuatro")
    chip = players.get("chip")
    if chip is not None and chip not in {"wildcard", "freehit", "bboost", "3xc"}:
        raise ValueError("chip desconocido (wildcard|freehit|bboost|3xc)")


def parse_players(raw: str | None):
    if raw is None or raw == "":
        return []
    candidate = Path(raw[1:]) if raw.startswith("@") else None
    text = candidate.read_text(encoding="utf-8") if candidate else raw
    if len(text.encode("utf-8")) > MAX_PLAYERS_BYTES:
        raise ValueError("players_json excede 16 KiB")
    return json.loads(text)


def add_note(db: OpsDB, *, season: str, gw: int, kind: str, text: str, players,
             source: str, actor: str, reason: str, idempotency_key: str,
             supersedes_note_id: str | None = None) -> dict:
    if kind not in NOTE_KINDS:
        raise ValueError(f"kind inválido: {kind}")
    if source not in NOTE_SOURCES:
        raise ValueError(f"source inválido: {source}")
    if not 1 <= int(gw) <= 38:
        raise ValueError("gw debe estar entre 1 y 38")
    for name, value in (("actor", actor), ("reason", reason),
                        ("idempotency_key", idempotency_key)):
        if not str(value or "").strip():
            raise ValueError(f"{name} es obligatorio")
    clean_text, redactions = sanitize_text(text)
    if not clean_text:
        raise ValueError("text vacío")
    if len(clean_text) > MAX_TEXT:
        raise ValueError(f"text excede {MAX_TEXT} caracteres")
    counter = [0]
    clean_players = _sanitize_json(players, counter)
    if kind == "decision":
        _validate_decision_players(clean_players)
    clean_reason, reason_redactions = sanitize_text(reason)
    db.migrate()
    result = db.add_strategy_note(
        season=season, gw=int(gw), kind=kind, text=clean_text, players=clean_players,
        source=source, actor=actor.strip(), reason=clean_reason,
        idempotency_key=idempotency_key.strip(), supersedes_note_id=supersedes_note_id,
    )
    return {"schema": NOTE_SCHEMA, **result,
            "redactions": redactions + counter[0] + reason_redactions,
            "runtime_mutated": False, "fpl_mutated": False}


def list_notes(db: OpsDB, *, season: str, gw: int | None = None,
               kinds: tuple[str, ...] = (), limit: int = 200) -> dict:
    if not db.path.is_file():
        return {"schema": NOTE_SCHEMA, "status": "missing", "needs_vps": True,
                "notes": [], "detail": "ops.db no existe en esta máquina"}
    try:
        notes = db.strategy_notes(season=season, gw=gw, kinds=kinds, limit=limit)
    except sqlite3.OperationalError as exc:
        return {"schema": NOTE_SCHEMA, "status": "missing", "needs_vps": True,
                "notes": [], "detail": f"ops.db sin migración strategy_notes ({exc})"[:300]}
    return {"schema": NOTE_SCHEMA, "status": "ok", "needs_vps": False,
            "filters": {"season": season, "gw": gw, "kinds": list(kinds)},
            "notes": notes}


def _section(fn):
    try:
        data = fn()
    except sqlite3.OperationalError as exc:
        return {"status": "missing", "needs_vps": True,
                "detail": f"tabla ausente o esquema antiguo: {exc}"[:300], "data": None}
    except Exception as exc:  # noqa: BLE001 - una sección rota no derriba la memoria
        return {"status": "error", "needs_vps": False,
                "detail": f"{type(exc).__name__}: {exc}"[:300], "data": None}
    empty = data in (None, [], {}) or (isinstance(data, dict) and not any(data.values()))
    return {"status": "missing" if empty else "ok", "needs_vps": False, "data": data}


def lessons_for(db: OpsDB, season: str, gw: int) -> list[dict]:
    # db.improvement_status es read-only; el servicio migra y aquí no se escribe.
    payload = db.improvement_status(season=season, gw=gw)
    return [
        {key: item.get(key) for key in ("lesson_id", "category", "statement",
                                        "status", "created_at")}
        for item in payload.get("lessons") or () if item.get("status") == "validated"
    ]


def deliberation_for(db: OpsDB, cycle_id: str) -> dict | None:
    envelope = db.latest_decision_envelope(cycle_id)
    if not envelope:
        return None
    deliberation = db.decision_deliberation_for_envelope(envelope["envelope_id"])
    return {
        "envelope_id": envelope["envelope_id"],
        "envelope_status": envelope.get("status"),
        "selected_candidate_key": envelope.get("selected_candidate_key"),
        "deliberation": None if not deliberation else {
            "deliberation_id": deliberation.get("deliberation_id"),
            "status": deliberation.get("status"),
            "preferred_candidate_key": deliberation.get("preferred_candidate_key"),
            "critic_verdict": deliberation.get("critic_verdict"),
            "strategist": _json_or_none(deliberation.get("strategist_json")),
            "critic": _json_or_none(deliberation.get("critic_json")),
            "error_code": deliberation.get("error_code"),
        },
    }


def _json_or_none(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def read_memory(db: OpsDB, *, season: str, gw: int) -> dict:
    """Agrega notas, lecciones, deliberación, intervenciones y ejecuciones manuales."""
    cycle_id = f"{season}-gw{int(gw):02d}"
    base = {"schema": MEMORY_SCHEMA, "season": season, "gw": int(gw), "cycle_id": cycle_id,
            "runtime_mutated": False}
    if not db.path.is_file():
        sections = {name: {"status": "missing", "needs_vps": True,
                           "detail": "ops.db no existe en esta máquina", "data": None}
                    for name in ("notes", "previous_notes", "lessons", "deliberation",
                                 "interventions", "manual_executions")}
        return {**base, "status": "empty", "sections": sections,
                "missing_on_vps": sorted(sections)}
    sections = {
        "notes": _section(lambda: db.strategy_notes(season=season, gw=gw)),
        "previous_notes": _section(lambda: [
            note for note in db.strategy_notes(season=season, through_gw=gw - 1, limit=50)
            if not note["superseded"] and note["kind"] in {
                "owner_preference", "constraint", "post_mortem", "decision", "hypothesis"}
        ] if gw > 1 else []),
        "lessons": _section(lambda: lessons_for(db, season, gw - 1) if gw > 1 else []),
        "deliberation": _section(lambda: deliberation_for(db, cycle_id)),
        "interventions": _section(lambda: db.interventions_for_cycle(cycle_id)),
        "manual_executions": _section(lambda: db.manual_executions_for_cycle(cycle_id)),
    }
    statuses = {section["status"] for section in sections.values()}
    return {**base,
            "status": "ok" if "ok" in statuses else "empty",
            "sections": sections,
            "missing_on_vps": sorted(name for name, section in sections.items()
                                     if section["needs_vps"])}
