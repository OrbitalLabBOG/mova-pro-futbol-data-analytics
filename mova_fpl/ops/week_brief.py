"""Brief semanal del modelo copiloto (ADR-021): `mova week brief|acta`.

Agrega en una sola lectura lo que el asistente necesita para armar la GW con el
owner. Nunca lanza por datos faltantes: cada sección declara
`status ∈ {ok, missing, degraded, error, skipped}` y `needs_vps`. No migra ni
crea `ops.db`; la red se limita a GET públicos vía `data.sources`. El acta MILP
se obtiene por subprocess de `mova_fpl.cli.live --dry-run --json-out` y se lee
únicamente el JSON escrito, nunca stdout.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB
from mova_fpl.ops.interventions import write_doc
from mova_fpl.ops.memory import deliberation_for, lessons_for, sanitize_text

SCHEMA = "mova-week-brief-v1"
ACTA_SCHEMA = "mova-acta-dry-run-v1"
CANDIDATES_SCHEMA = "mova-live-decision-candidates-v1"
ROOT = Path(__file__).resolve().parents[2]
SECTIONS = ("cycle", "authority", "squad", "acta", "flags", "projections",
            "strategy_reasons", "research_signals", "lessons", "execution",
            "open_decisions")
CORE_SECTIONS = ("cycle", "squad", "acta", "flags")
POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
CAPTAIN_MARGIN_XP = 0.5
#: CBC puede tardar hasta 600 s en `cli.live` (time_limit); el wrapper no debe cortar antes
ACTA_TIMEOUT_SECONDS = 600


def _utc(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _json(value, default=None):
    if value is None:
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def section(status: str, source: str | None, *, needs_vps: bool = False,
            detail: str | None = None, data=None) -> dict:
    out = {"status": status, "source": source, "needs_vps": bool(needs_vps), "data": data}
    if detail:
        out["detail"] = sanitize_text(detail)[0][:500]
    return out


def _guard(fn: Callable[[], dict], source: str) -> dict:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - el brief nunca cae por una sección
        return section("error", source, detail=f"{type(exc).__name__}: {exc}")


class PublicFPL:
    """Lecturas públicas FPL. Solo GET a través de la primitiva de `data.sources`."""

    def bootstrap(self) -> dict:
        from mova_fpl.data.sources import fetch_bootstrap
        return json.loads(fetch_bootstrap(retries=2))

    def history(self, team_id: int) -> dict:
        from mova_fpl.data.sources import fetch_team_history
        return json.loads(fetch_team_history(team_id))

    def picks(self, team_id: int, gw: int) -> dict:
        from mova_fpl.data.sources import fetch_team_picks
        return json.loads(fetch_team_picks(team_id, gw))

    def event_live(self, gw: int) -> dict:
        from mova_fpl.data.sources import fetch_event_live
        return json.loads(fetch_event_live(gw))


# --- acta MILP (dry-run) ------------------------------------------------------

def _default_runner(argv: list[str], *, env: dict, cwd: Path, timeout: int):
    """Corre `cli.live` en su propio grupo de procesos y lo mata entero al vencer.

    `subprocess.run(timeout=)` solo mata al hijo directo; un `cbc` nieto quedaba
    huérfano consumiendo CPU después del timeout.
    """
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL ya cerró los pipes
            pass
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def _model_versions(config: RuntimeConfig, db: OpsDB | None) -> tuple[dict, str]:
    if db is not None:
        try:
            from mova_fpl.ops.model_release import resolve_active_model_bundle

            bundle = resolve_active_model_bundle(config, db)
            return ({name: bundle["models"][name]["version"] for name in ("minutes", "points")},
                    str(bundle.get("source") or "active_bundle"))
        except Exception:  # noqa: BLE001 - se informa abajo como artefacto faltante
            pass
    return ({"minutes": config.analytics_minutes_version,
             "points": config.analytics_points_version}, "runtime_config")


def acta_prerequisites(config: RuntimeConfig, versions: dict) -> list[str]:
    """Rutas que `cli.live` necesita y no existen en esta máquina."""
    model_root = config.artifact_root / "models"
    required = [config.canonical_db] + [
        model_root / name / f"{name}-{version}.joblib" for name, version in versions.items()
    ]
    return [str(path) for path in required if not path.is_file()]


def _acta_out_dir(config: RuntimeConfig, gw: int, now: datetime) -> Path:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    root = config.artifact_root
    if root.is_dir() and os.access(root, os.W_OK):
        target = root / "copilot" / f"gw{gw:02d}" / stamp
        target.mkdir(parents=True, exist_ok=True)
        return target
    return Path(tempfile.mkdtemp(prefix=f"mova-acta-gw{gw:02d}-{stamp}-"))


def fresh_private_state(config: RuntimeConfig, db: OpsDB | None, cycle_id: str,
                        now: datetime) -> dict | None:
    """Mismo criterio que el tick: snapshot válido y dentro de la cadencia vigente."""
    if db is None:
        return None
    from mova_fpl.ops.schedule import private_state_cadence_seconds

    state = db.latest_team_state(cycle_id)
    if not state or not state.get("artifact_path") or state.get("quality_status") != "valid":
        return None
    observed = _parse_time(state.get("observed_at"))
    cycle = db.status().get("cycle") or {}
    deadline = cycle.get("deadline_at")
    if observed is None or not deadline:
        return None
    max_age = min(config.private_state_max_age_seconds,
                  private_state_cadence_seconds(str(deadline), now))
    return state if (now - observed).total_seconds() <= max_age else None


def _label_for_source(name: str | None) -> str:
    return "import" if name == "operator_import" else "capture"


def explicit_private_state(config: RuntimeConfig, path: str, gw: int,
                           now: datetime) -> dict:
    """Snapshot sellado indicado a mano (p. ej. el recién importado).

    Salta la ventana de cadencia a propósito: el operador lo eligió. La edad se
    reporta (`state_age_h`) y `stale` avisa si excede el máximo configurado.
    """
    from mova_fpl.data.private_state import load

    normalized, manifest = load(Path(path), expected_team_id=config.team_id)
    if int(normalized["event"]["id"]) != int(gw):
        raise ValueError(f"snapshot privado es GW{normalized['event']['id']}; se pidió GW{gw}")
    observed = _parse_time(normalized["observed_at"])
    age = (now - observed).total_seconds() if observed else None
    return {"artifact_path": str(path), "observed_at": normalized["observed_at"],
            "fingerprint": (manifest.get("quality") or {}).get("fingerprint"),
            "source_name": manifest.get("source_label") or "fpl_authenticated_api",
            "age_seconds": age,
            "stale": age is None or age > config.private_state_max_age_seconds}


def state_provenance(private: dict | None, now: datetime) -> dict:
    """De dónde salió la plantilla del acta; sin estado privado lo dice claro."""
    if not private:
        return {"state_source": "public_reconstruction", "state_age_h": None,
                "state_note": "sin estado privado: plantilla del último GW público; "
                              "FT y chips disponibles son supuestos"}
    age = private.get("age_seconds")
    if age is None:
        observed = _parse_time(private.get("observed_at"))
        age = (now - observed).total_seconds() if observed else None
    return {"state_source": _label_for_source(private.get("source_name")),
            "state_age_h": None if age is None else round(age / 3600, 2),
            "state_fingerprint": private.get("fingerprint"),
            "state_stale": bool(private.get("stale", False))}


def acta_argv(config: RuntimeConfig, *, gw: int, horizon: int, chips: bool,
              versions: dict, out_dir: Path, private_state_dir: str | None,
              interventions_path: str | None = None) -> list[str]:
    argv = [
        sys.executable, "-m", "mova_fpl.cli.live", "--season", config.season,
        "--gw", str(int(gw)), "--policy", "milp", "--horizon", str(int(horizon)),
        "--top-k", "0", "--version", versions["points"],
        "--minutes-version", versions["minutes"], "--team-id", str(config.team_id),
        "--dry-run", "--out", str(out_dir / "acta.md"),
        "--json-out", str(out_dir / "candidates.json"),
    ]
    if chips:
        argv.append("--chips")
    if private_state_dir:
        argv.extend(["--private-team-state", str(private_state_dir)])
    if interventions_path:
        argv.extend(["--interventions", str(interventions_path)])
    return argv


def run_acta(config: RuntimeConfig, db: OpsDB | None, *, gw: int, horizon: int = 3,
             chips: bool = False, now: datetime | None = None, runner=None,
             timeout: int = ACTA_TIMEOUT_SECONDS, private_state_path: str | None = None,
             require_private_state: bool = False, interventions: dict | None = None) -> dict:
    """Corre el acta MILP en dry-run (sin traza) y parsea solo `--json-out`.

    `private_state_path`: snapshot explícito (no pasa por la cadencia de
    `fresh_private_state`). `interventions`: documento ya normalizado de
    `ops.interventions`; se escribe junto al acta y se pasa a `cli.live`.
    """
    current = _utc(now)
    versions, version_source = _model_versions(config, db)
    base = {"schema": ACTA_SCHEMA, "season": config.season, "gw": int(gw),
            "horizon": int(horizon), "chips": bool(chips),
            "model_versions": versions, "model_version_source": version_source,
            "trace_written": False, "fpl_mutated": False}
    missing = acta_prerequisites(config, versions) if runner is None else []
    if missing:
        return {**base, "status": "missing", "needs_vps": True, "missing": missing,
                "detail": "artefactos canónicos/modelos ausentes; el acta corre en el VPS"}
    private = None
    if private_state_path:
        try:
            private = explicit_private_state(config, private_state_path, int(gw), current)
        except Exception as exc:  # noqa: BLE001 - un snapshot explícito inválido es error
            return {**base, "status": "error", "needs_vps": False,
                    **state_provenance(None, current),
                    "detail": f"snapshot privado explícito inválido: {type(exc).__name__}: {exc}"}
    else:
        try:
            private = fresh_private_state(config, db, f"{config.season}-gw{int(gw):02d}", current)
            if private:
                observed = _parse_time(private.get("observed_at"))
                private = {**private, "age_seconds": (
                    (current - observed).total_seconds() if observed else None)}
        except Exception:  # noqa: BLE001 - sin estado privado se usa la reconstrucción pública
            private = None
    provenance = state_provenance(private, current)
    base.update(provenance)
    if require_private_state and (not private or private.get("stale")):
        return {**base, "status": "error", "needs_vps": False,
                "detail": "--require-private-state: estado privado ausente o vencido; "
                          "importa/captura uno y pásalo con --private-state-path"}
    out_dir = _acta_out_dir(config, int(gw), current)
    interventions_path = None
    if interventions:
        interventions_path = str(write_doc(interventions, out_dir))
    argv = acta_argv(config, gw=gw, horizon=horizon, chips=chips, versions=versions,
                     out_dir=out_dir,
                     private_state_dir=private.get("artifact_path") if private else None,
                     interventions_path=interventions_path)
    env = dict(os.environ)
    env.update({
        "MOVA_CANONICAL_DB": str(config.canonical_db),
        "MOVA_TRACE_DB": str(config.trace_db),
        "MOVA_MODEL_ROOT": str(config.artifact_root / "models"),
        "MOVA_GIT_SHA": config.git_sha,
    })
    started = time.monotonic()
    base.update({"acta_path": str(out_dir / "acta.md"),
                 "candidates_path": str(out_dir / "candidates.json"),
                 "private_team_state": (None if not private else {
                     "team_state_id": private.get("team_state_id"),
                     "fingerprint": private.get("fingerprint")}),
                 "command": [Path(argv[0]).name, *argv[1:]]})
    try:
        result = (runner or _default_runner)(argv, env=env, cwd=ROOT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {**base, "status": "error", "needs_vps": False,
                "elapsed_s": round(time.monotonic() - started, 2),
                "detail": f"cli.live excedió {timeout}s"}
    elapsed = round(time.monotonic() - started, 2)
    if int(getattr(result, "returncode", 1)) != 0:
        tail = sanitize_text(str(getattr(result, "stderr", "") or "")[-800:])[0]
        return {**base, "status": "error", "needs_vps": False, "elapsed_s": elapsed,
                "returncode": int(getattr(result, "returncode", 1)), "stderr_tail": tail,
                "detail": "cli.live terminó con error"}
    candidates_path = out_dir / "candidates.json"
    try:
        payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {**base, "status": "error", "needs_vps": False, "elapsed_s": elapsed,
                "detail": f"JSON del acta ilegible: {type(exc).__name__}"}
    if payload.get("schema") != CANDIDATES_SCHEMA:
        return {**base, "status": "error", "needs_vps": False, "elapsed_s": elapsed,
                "detail": f"schema inesperado: {payload.get('schema')!r}"}
    candidates = payload.get("candidates") or []
    return {
        **base, "status": "ok", "needs_vps": False, "elapsed_s": elapsed,
        "selected_candidate_key": payload.get("selected_candidate_key"),
        "candidates": candidates,
        "violations": {str(item.get("candidate_key")): item.get("violations") or []
                       for item in candidates},
        "team_state": payload.get("team_state"),
        "event_context": payload.get("event_context"),
        "engine": payload.get("engine"),
        "report_artifact": payload.get("report_artifact"),
        "interventions": payload.get("interventions"),
    }


# --- secciones ----------------------------------------------------------------

def _elements(boot: dict | None) -> dict[int, dict]:
    if not boot:
        return {}
    teams = {int(team["id"]): team.get("short_name") or team.get("name")
             for team in boot.get("teams") or ()}
    out = {}
    for element in boot.get("elements") or ():
        out[int(element["id"])] = {
            "name": element.get("web_name"),
            "team": teams.get(int(element.get("team") or 0)),
            "position": POSITIONS.get(int(element.get("element_type") or 0)),
            "status": element.get("status"),
            "chance_next": element.get("chance_of_playing_next_round"),
            "news": element.get("news") or "",
            "price": (element.get("now_cost") or 0) / 10,
        }
    return out


def _cycle_section(config, db, boot, gw, now) -> dict:
    db_cycle = db.cycle_row(config.season, gw) if db is not None else None
    events = {int(event["id"]): event for event in (boot or {}).get("events") or ()}
    event, previous = events.get(gw), events.get(gw - 1)
    if not db_cycle and not event:
        return section("missing", None, needs_vps=db is None,
                       detail="sin ops.db ni API pública para la GW")
    deadline = (event or {}).get("deadline_time") or (db_cycle or {}).get("deadline_at")
    deadline_at = _parse_time(deadline)
    previous_closed = None
    if gw == 1:
        previous_closed = True
    elif previous is not None:
        previous_closed = bool(previous.get("finished") and previous.get("data_checked"))
    sources = [name for name, value in (("public_api", event), ("ops_db", db_cycle)) if value]
    data = {
        "season": config.season, "gw": gw, "cycle_id": f"{config.season}-gw{gw:02d}",
        "deadline_at": deadline,
        "seconds_to_deadline": (int((deadline_at - now).total_seconds())
                                if deadline_at else None),
        "is_next": (event or {}).get("is_next"), "is_current": (event or {}).get("is_current"),
        "phase": (db_cycle or {}).get("phase"), "cycle_status": (db_cycle or {}).get("status"),
        "previous_gw": None if gw == 1 else {
            "gw": gw - 1,
            "finished": (previous or {}).get("finished"),
            "data_checked": (previous or {}).get("data_checked"),
        },
        "preliminary": previous_closed is not True,
    }
    status = "ok" if deadline and previous_closed is not None else "degraded"
    return section(status, "+".join(sources), data=data,
                   detail=None if status == "ok" else "sin estado público de la GW previa")


def _authority_section(config, db, now) -> dict:
    fallback = {"operating_model": config.operating_model,
                "fpl_writes": "owner_validated_manual_only"}
    if db is None:
        return section("missing", "config", needs_vps=True, data=fallback,
                       detail="controles efectivos viven en ops.db del VPS")
    from mova_fpl.ops.operator import build_safety

    safety = build_safety(config, db, now=now)
    return section("ok", "ops_db", data={
        **fallback, "operating_model": safety.get("operating_model"),
        "verdict": safety.get("verdict"), "reasons": safety.get("reasons"),
        "controls": safety.get("controls"),
    })


def _player_rows(picks: list[dict], names: dict[int, dict]) -> list[dict]:
    rows = []
    for pick in sorted(picks, key=lambda item: int(item.get("position") or 0)):
        element = int(pick["element"])
        info = names.get(element, {})
        position = int(pick.get("position") or 0)
        rows.append({
            "element": element, "name": info.get("name"), "team": info.get("team"),
            "position": info.get("position"), "squad_position": position,
            "role": "starter" if position <= 11 else "bench",
            "is_captain": bool(pick.get("is_captain")),
            "is_vice_captain": bool(pick.get("is_vice_captain")),
            "multiplier": pick.get("multiplier"),
        })
    return rows


def _explicit_squad(config, path, gw, names, now) -> dict | None:
    """Sección squad desde el snapshot explícito (mismo que usa el acta)."""
    from mova_fpl.data.private_state import load

    info = explicit_private_state(config, path, gw, now)
    normalized, _ = load(Path(path), expected_team_id=config.team_id)
    tr = normalized["transfers"]
    chips = normalized.get("chips") or []
    data = {
        "players": _player_rows(normalized["picks"], names),
        "free_transfers": None, "bank": tr["bank"] / 10,
        "chips": [{"name": c["name"], "status": c["status_for_entry"]} for c in chips],
        "chips_available": sorted(c["name"] for c in chips
                                  if c["status_for_entry"] == "available"),
        "observed_at": info["observed_at"], "age_seconds": int(info["age_seconds"] or 0),
        "fingerprint": info["fingerprint"], "fresh": not info["stale"],
        "state_source": _label_for_source(info["source_name"]),
        "state_age_h": None if info["age_seconds"] is None
        else round(info["age_seconds"] / 3600, 2),
    }
    from mova_fpl.data.private_state import validate
    data["free_transfers"] = validate(normalized, expected_team_id=config.team_id)[1][
        "free_transfers"]
    if info["stale"]:
        return section("degraded", "private_team_state", data=data, needs_vps=True,
                       detail="snapshot explícito vencido")
    return section("ok", "private_team_state", data=data)


def _squad_section(config, db, boot, fetcher, gw, now, network,
                   explicit_path: str | None = None) -> dict:
    names = _elements(boot)
    if explicit_path:
        return _explicit_squad(config, explicit_path, gw, names, now)
    private = None
    if db is not None:
        private = (db.latest_team_state_for_event(config.season, gw)
                   or db.latest_team_state_for_event(config.season, gw - 1))
    if private:
        observed = _parse_time(private.get("observed_at"))
        age = int((now - observed).total_seconds()) if observed else None
        stale = age is None or age > config.private_state_max_age_seconds
        valid = private.get("quality_status") == "valid"
        chips = _json(private.get("chips_json"), []) or []
        data = {
            "players": _player_rows(_json(private.get("squad_json"), []) or [], names),
            "free_transfers": private.get("free_transfers"),
            "bank": (private.get("bank_tenths") or 0) / 10,
            "chips": [{"name": chip.get("name"), "status": chip.get("status_for_entry")}
                      for chip in chips if isinstance(chip, dict)],
            "chips_available": sorted(chip.get("name") for chip in chips if isinstance(chip, dict)
                                      and chip.get("status_for_entry") == "available"),
            "observed_at": private.get("observed_at"), "age_seconds": age,
            "fingerprint": private.get("fingerprint"),
            "team_state_id": private.get("team_state_id"),
            "cycle_id": private.get("cycle_id"), "fresh": not stale and valid,
            "state_source": _label_for_source(private.get("source_name")),
            "state_age_h": None if age is None else round(age / 3600, 2),
        }
        if stale or not valid:
            return section("degraded", "private_team_state", data=data, needs_vps=True,
                           detail="estado privado vencido o no válido; reautenticar sesión FPL")
        return section("ok", "private_team_state", data=data)
    if not network or boot is None:
        return section("missing", None, needs_vps=True,
                       detail="sin estado privado en ops.db y sin red para picks públicos")
    played = [int(event["id"]) for event in boot.get("events") or ()
              if int(event["id"]) < gw and (event.get("finished") or event.get("is_current"))]
    if not played:
        return section("missing", "public_api", needs_vps=True,
                       detail="el equipo aún no tiene jornadas jugadas")
    source_gw = max(played)
    picks = fetcher.picks(config.team_id, source_gw)
    history = fetcher.history(config.team_id)
    entry = picks.get("entry_history") or {}
    used = [{"name": chip.get("name"), "event": chip.get("event")}
            for chip in history.get("chips") or ()]
    return section("degraded", "public_reconstruction", needs_vps=True, data={
        "players": _player_rows(picks.get("picks") or [], names),
        "picks_gw": source_gw, "active_chip": picks.get("active_chip"),
        "bank": (entry.get("bank") or 0) / 10, "value": (entry.get("value") or 0) / 10,
        "free_transfers": "unknown", "chips_used": used, "chips_available": "unknown",
        "fresh": False, "team_id": config.team_id,
    }, detail=(f"picks públicos de GW{source_gw}; FT/chips disponibles exigen el estado "
               "privado del VPS"))


def _acta_summary(acta: dict, names: dict[int, dict]) -> dict:
    """Vista compacta para el brief; `week acta` conserva el bundle completo."""
    data = dict(acta)
    candidates = data.pop("candidates", None) or []
    data["alternatives"] = []
    for candidate in candidates:
        decision = candidate.get("decision") or {}
        summary = {
            "candidate_key": candidate.get("candidate_key"), "label": candidate.get("label"),
            "expected_points": decision.get("expected_points"),
            "captain": decision.get("captain"), "vice_captain": decision.get("vice_captain"),
            "transfers_in": decision.get("transfers_in"),
            "transfers_out": decision.get("transfers_out"),
            "hits": decision.get("hits"), "chip": decision.get("chip"),
            "violations": len(candidate.get("violations") or ()),
        }
        if candidate.get("candidate_key") == data.get("selected_candidate_key"):
            data["selected"] = {**decision, "players": {
                str(element): (names.get(int(element)) or {}).get("name")
                for element in decision.get("squad_15") or ()}}
        data["alternatives"].append(summary)
    return data


def _acta_section(config, db, gw, horizon, chips, now, run, runner, names,
                  acta_options: dict | None = None) -> dict:
    if not run:
        return section("skipped", "cli.live", detail="--no-acta")
    payload = run_acta(config, db, gw=gw, horizon=horizon, chips=chips, now=now,
                       runner=runner, **(acta_options or {}))
    status = payload.get("status")
    return section(status, "cli.live --dry-run", needs_vps=bool(payload.get("needs_vps")),
                   detail=payload.get("detail"),
                   data=_acta_summary(payload, names) if status == "ok" else {
                       key: payload.get(key) for key in (
                           "missing", "stderr_tail", "returncode", "model_versions",
                           "elapsed_s", "acta_path", "candidates_path", "state_source",
                           "state_age_h", "state_note")
                       if payload.get(key) is not None and payload.get(key) != ""})


def _flags_section(boot, squad, acta) -> dict:
    if boot is None:
        return section("missing", None, detail="sin red: los flags salen de bootstrap-static")
    names = _elements(boot)
    elements: dict[int, str] = {}
    for player in ((squad.get("data") or {}).get("players") or ()):
        elements[int(player["element"])] = "squad"
    selected = (acta.get("data") or {}).get("selected") if acta.get("status") == "ok" else None
    for element in (selected or {}).get("transfers_in") or ():
        elements.setdefault(int(element), "acta_transfer_in")
    flagged = []
    for element, origin in sorted(elements.items()):
        info = names.get(element)
        if info is None:
            flagged.append({"element": element, "origin": origin, "status": "unknown",
                            "news": "no aparece en bootstrap-static"})
            continue
        chance = info.get("chance_next")
        if info.get("status") != "a" or (chance is not None and chance < 100) or info["news"]:
            flagged.append({"element": element, "origin": origin, "name": info["name"],
                            "team": info["team"], "status": info["status"],
                            "chance_next": chance, "news": info["news"]})
    data = {"checked": len(elements), "flagged": flagged}
    if not elements:
        return section("degraded", "public_api", data=data,
                       detail="sin plantilla conocida: no hay jugadores que revisar")
    return section("ok", "public_api", data=data)


def _projections_section(config, gw, squad, acta) -> dict:
    from mova_fpl.ops.analytics_store import read_status

    try:
        status = read_status(config)
    except FileNotFoundError:
        status = None
    if status is None:
        expected = ((acta.get("data") or {}).get("selected") or {}).get("expected_points")
        if acta.get("status") == "ok" and expected is not None:
            return section("degraded", "acta", data={"expected_points": expected},
                           detail="sin snapshot analytics; xP total del acta MILP")
        return section("missing", None, needs_vps=True,
                       detail="analytics status.json vive en el VPS")
    batches = [batch for batch in status.get("latest_projection_batches") or ()
               if str(batch.get("season")) == config.season
               and int(batch.get("target_gw") or 0) == gw]
    data = {"generated_at": status.get("generated_at"), "service_status": status.get("status"),
            "batches": batches[:3], "player_xp": None}
    if not batches:
        return section("degraded", "analytics_status", data=data,
                       detail=f"sin proyección sellada para GW{gw}")
    if config.postgres_credential_file.is_file():
        try:
            from mova_fpl.ops.analytics_store import AnalyticsStore

            frame = AnalyticsStore(config).projection_frame(str(batches[0]["batch_id"]))
            wanted = {int(player["element"]) for player in
                      ((squad.get("data") or {}).get("players") or ())}
            wanted |= {int(element) for element in
                       (((acta.get("data") or {}).get("selected") or {}).get("squad_15") or ())}
            if not frame.empty:
                grouped = frame.groupby("element")["xp"].sum()
                data["player_xp"] = {str(int(element)): round(float(value), 2)
                                     for element, value in grouped.items()
                                     if int(element) in wanted}
        except Exception as exc:  # noqa: BLE001
            return section("degraded", "analytics_status", data=data,
                           detail=f"xP por jugador no disponible: {type(exc).__name__}")
    return section("ok", "analytics_status", data=data)


def _strategy_section(db, cycle_id) -> dict:
    if db is None:
        return section("missing", None, needs_vps=True, detail="manifiesto y deliberación en ops.db")
    strategic = db.strategic_status(cycle_id)
    manifest = strategic.get("manifest") or {}
    data = {
        "status": strategic.get("status"),
        "manifest_id": manifest.get("manifest_id"),
        "memory_summary": strategic.get("memory_summary"),
        "unresolved_conflicts": strategic.get("unresolved_conflicts"),
        "decision_envelope": deliberation_for(db, cycle_id),
    }
    if not manifest and not data["decision_envelope"]:
        return section("missing", "ops_db", data=data, detail="ciclo sin manifiesto ni envelope")
    return section("ok", "ops_db", data=data)


def _research_section(db, cycle_id, now) -> dict:
    if db is None:
        return section("missing", None, needs_vps=True, detail="research_signals en ops.db")
    context = db.active_research_context(
        cycle_id, now=now.isoformat(timespec="milliseconds"))
    status = "ok" if context["signals"] or context["conflicts"] else "missing"
    return section(status, "ops_db", data=context,
                   detail=None if status == "ok" else "sin señales vigentes para el ciclo")


def _lessons_section(config, db, gw) -> dict:
    if db is None:
        return section("missing", None, needs_vps=True, detail="lecciones y notas en ops.db")
    data = {"lessons": lessons_for(db, config.season, gw - 1) if gw > 1 else [],
            "notes": [], "previous_notes": []}
    try:
        data["notes"] = db.strategy_notes(season=config.season, gw=gw)
        data["previous_notes"] = [
            note for note in db.strategy_notes(season=config.season, through_gw=gw - 1,
                                               limit=50)
            if not note["superseded"] and note["kind"] in {
                "owner_preference", "constraint", "post_mortem", "decision"}
        ] if gw > 1 else []
    except Exception as exc:  # noqa: BLE001 - ops.db previa a la migración 25
        return section("degraded", "ops_db", data=data,
                       detail=f"strategy_notes no disponible: {type(exc).__name__}")
    status = "ok" if any(data.values()) else "missing"
    return section(status, "ops_db", data=data,
                   detail=None if status == "ok" else "sin lecciones ni notas")


def _execution_section(config, db, cycle_id) -> dict:
    if db is None:
        return section("missing", None, needs_vps=True, detail="ejecuciones en ops.db")
    from mova_fpl.ops.manual_delivery import receipt

    data = {"manual_executions": db.manual_executions_for_cycle(cycle_id),
            "manual_receipt": None, "decision_notes": []}
    try:
        data["manual_receipt"] = receipt(config, db, cycle_id)
    except Exception as exc:  # noqa: BLE001
        data["manual_receipt"] = {"status": "error", "error": type(exc).__name__}
    try:
        season, gw = cycle_id.rsplit("-gw", 1)
        data["decision_notes"] = db.strategy_notes(season=season, gw=int(gw),
                                                   kinds=("decision",))
    except Exception:  # noqa: BLE001
        pass
    status = "ok" if any(data.values()) else "missing"
    return section(status, "ops_db", data=data,
                   detail=None if status == "ok" else "sin ejecución ni decisión registrada")


def derive_open_decisions(sections: dict, *, gw: int) -> list[dict]:
    """Reglas puras y deterministas sobre las secciones ya construidas."""
    out: list[dict] = []

    def add(code: str, severity: str, text: str, **detail) -> None:
        out.append({"code": code, "severity": severity, "text": text,
                    **({"detail": detail} if detail else {})})

    cycle = sections["cycle"].get("data") or {}
    if cycle.get("seconds_to_deadline") is not None and cycle["seconds_to_deadline"] < 0:
        add("deadline_passed", "blocker", f"El deadline de GW{gw} ya pasó.")
    if cycle.get("preliminary"):
        add("preliminary_gw", "blocker",
            f"GW{gw - 1} no está finished+data_checked: propuesta preliminar; "
            "no promover chips ni transferencias.")
    authority = sections["authority"].get("data") or {}
    if authority.get("verdict") == "unsafe":
        add("authority_unsafe", "blocker", "build_safety reporta estado unsafe.",
            reasons=authority.get("reasons"))
    squad = sections["squad"]
    squad_data = squad.get("data") or {}
    if squad.get("source") != "private_team_state" or not squad_data.get("fresh"):
        add("private_state_missing", "decide",
            "Sin estado privado fresco: FT, banco y chips sin confirmar. Reautenticar la "
            "sesión FPL en el browser del VPS y correr `mova private-state capture --force` "
            "(o `mova week brief --capture-private-state`) antes de cerrar transferencias/chips.")
    acta = sections["acta"]
    selected = (acta.get("data") or {}).get("selected") if acta.get("status") == "ok" else None
    if acta.get("status") in {"error", "missing"}:
        add("acta_unavailable", "info", "Sin acta MILP en esta corrida; correr `mova week acta` "
            "donde estén el dataset canónico y los modelos.")
    starters = set((selected or {}).get("starters") or ()) or {
        int(player["element"]) for player in squad_data.get("players") or ()
        if player.get("role") == "starter"}
    for flag in (sections["flags"].get("data") or {}).get("flagged") or ():
        starter = int(flag["element"]) in starters
        add("starter_flagged" if starter else "bench_flagged", "decide" if starter else "info",
            f"{'Titular' if starter else 'Suplente/candidato'} con flag: "
            f"{flag.get('name') or flag['element']} "
            f"(status {flag.get('status')}, chance {flag.get('chance_next')}).",
            element=flag["element"], news=flag.get("news"))
    if selected:
        transfers = selected.get("transfers_in") or []
        if transfers:
            add("transfers_proposed", "decide",
                f"El acta propone {len(transfers)} transferencia(s) con {selected.get('hits', 0)} "
                f"hit(s); FT disponibles: {squad_data.get('free_transfers', 'unknown')}.",
                transfers_in=transfers, transfers_out=selected.get("transfers_out"))
        if selected.get("chip"):
            add("chip_proposed", "decide",
                f"El acta propone chip {selected['chip']}; requiere OK explícito del owner.")
        xp = (sections["projections"].get("data") or {}).get("player_xp") or {}
        captain, vice = selected.get("captain"), selected.get("vice_captain")
        if captain is not None and vice is not None and str(captain) in xp and str(vice) in xp:
            margin = round(xp[str(captain)] - xp[str(vice)], 2)
            if margin < CAPTAIN_MARGIN_XP:
                add("captain_margin_tight", "decide",
                    f"Margen C vs VC de {margin} xP (< {CAPTAIN_MARGIN_XP}).",
                    captain=captain, vice_captain=vice)
    conflicts = (sections["research_signals"].get("data") or {}).get("conflicts") or []
    if conflicts:
        add("research_conflicts", "decide",
            f"{len(conflicts)} conflicto(s) de research sin resolver.",
            conflict_ids=[item.get("conflict_id") for item in conflicts])
    return out


def _brief_state(sections: dict) -> dict:
    """Procedencia del estado: la del acta si corrió; si no, la de la sección squad."""
    acta = sections.get("acta") or {}
    data = acta.get("data") or {}
    if data.get("state_source"):
        return {"state_source": data["state_source"], "state_age_h": data.get("state_age_h"),
                "used_by": "acta", **({"note": data["state_note"]}
                                      if data.get("state_note") else {})}
    squad = sections.get("squad") or {}
    sdata = squad.get("data") or {}
    if sdata.get("state_source"):
        return {"state_source": sdata["state_source"], "state_age_h": sdata.get("state_age_h"),
                "used_by": "squad"}
    source = squad.get("source")
    return {"state_source": "public_reconstruction" if source == "public_reconstruction"
            else "none", "state_age_h": None, "used_by": "squad",
            "note": "sin estado privado usado"}


def build_week_brief(config: RuntimeConfig, db: OpsDB | None, *, gw: int,
                     now: datetime | None = None, network: bool = True,
                     run_acta_flag: bool = True, chips: bool = False, horizon: int = 3,
                     fetcher=None, acta_runner=None, acta_options: dict | None = None) -> dict:
    current = _utc(now)
    gw = int(gw)
    if not 1 <= gw <= 38:
        raise ValueError("gw debe estar entre 1 y 38")
    if db is not None and not db.path.is_file():
        db = None  # nunca crear ni migrar ops.db desde un brief
    cycle_id = f"{config.season}-gw{gw:02d}"
    fetcher = fetcher or PublicFPL()
    boot, network_error = None, None
    if network:
        try:
            boot = fetcher.bootstrap()
        except Exception as exc:  # noqa: BLE001
            network_error = f"{type(exc).__name__}: {exc}"
    names = _elements(boot)
    sections: dict[str, dict] = {}
    sections["cycle"] = _guard(lambda: _cycle_section(config, db, boot, gw, current), "cycle")
    sections["authority"] = _guard(lambda: _authority_section(config, db, current), "ops_db")
    sections["squad"] = _guard(
        lambda: _squad_section(config, db, boot, fetcher, gw, current, network,
                               (acta_options or {}).get("private_state_path")), "squad")
    sections["acta"] = _guard(lambda: _acta_section(
        config, db, gw, horizon, chips, current, run_acta_flag, acta_runner, names,
        acta_options), "cli.live")
    sections["flags"] = _guard(
        lambda: _flags_section(boot, sections["squad"], sections["acta"]), "public_api")
    sections["projections"] = _guard(lambda: _projections_section(
        config, gw, sections["squad"], sections["acta"]), "analytics")
    sections["strategy_reasons"] = _guard(lambda: _strategy_section(db, cycle_id), "ops_db")
    sections["research_signals"] = _guard(
        lambda: _research_section(db, cycle_id, current), "ops_db")
    sections["lessons"] = _guard(lambda: _lessons_section(config, db, gw), "ops_db")
    sections["execution"] = _guard(lambda: _execution_section(config, db, cycle_id), "ops_db")
    try:
        sections["open_decisions"] = section(
            "ok", "derived", data=derive_open_decisions(sections, gw=gw))
    except Exception as exc:  # noqa: BLE001
        sections["open_decisions"] = section("error", "derived", data=[],
                                             detail=f"{type(exc).__name__}: {exc}")
    ok = [name for name in SECTIONS[:-1] if sections[name]["status"] == "ok"]
    ready = (all(sections[name]["status"] == "ok" for name in CORE_SECTIONS)
             and (sections["squad"].get("data") or {}).get("fresh"))
    return {
        "schema": SCHEMA,
        "generated_at": current.isoformat(timespec="seconds"),
        "season": config.season, "gw": gw, "cycle_id": cycle_id,
        "team_id": config.team_id,
        "operating_model": config.operating_model,
        "overall": "ready" if ready else "partial" if ok else "empty",
        "state": _brief_state(sections),
        "inputs": {"network": bool(network), "acta": bool(run_acta_flag),
                   "chips": bool(chips), "horizon": int(horizon),
                   "ops_db_present": db is not None,
                   "network_error": sanitize_text(network_error)[0][:300]
                   if network_error else None},
        "missing_on_vps": [name for name in SECTIONS if sections[name]["needs_vps"]],
        "sections": sections,
        "runtime_mutated": False, "fpl_mutated": False,
    }


# --- Markdown ------------------------------------------------------------------

def _badge(item: dict) -> str:
    vps = " · necesita VPS" if item.get("needs_vps") else ""
    return f"`{item['status']}`{vps}"


def render_week_brief(brief: dict) -> str:
    s = brief["sections"]
    lines = [
        f"# MOVA · brief GW{brief['gw']} ({brief['season']})",
        "",
        f"- Generado: {brief['generated_at']} · overall **{brief['overall']}** · "
        f"modelo `{brief['operating_model']}`",
        f"- Falta en VPS: {', '.join(brief['missing_on_vps']) or 'nada'}",
        f"- Estado usado: **{(brief.get('state') or {}).get('state_source')}** · edad "
        f"{(brief.get('state') or {}).get('state_age_h')} h",
        "",
        "## Decisiones abiertas",
    ]
    decisions = s["open_decisions"].get("data") or []
    lines += [f"- **{item['severity']}** `{item['code']}`: {item['text']}" for item in decisions]
    if not decisions:
        lines.append("- ninguna")
    cycle = s["cycle"].get("data") or {}
    lines += ["", f"## Ciclo {_badge(s['cycle'])}"]
    if cycle:
        lines.append(f"- Deadline {cycle.get('deadline_at')} · fase {cycle.get('phase')} · "
                     f"preliminar {cycle.get('preliminary')}")
    authority = s["authority"].get("data") or {}
    lines += ["", f"## Autoridad {_badge(s['authority'])}",
              f"- operating_model `{authority.get('operating_model')}` · veredicto "
              f"`{authority.get('verdict', 'n/d')}` · escrituras FPL: solo con OK del owner"]
    squad = s["squad"]
    data = squad.get("data") or {}
    lines += ["", f"## Plantilla {_badge(squad)} ({squad.get('source')})"]
    if data.get("players"):
        lines.append(f"- FT {data.get('free_transfers')} · banco {data.get('bank')} · "
                     f"chips disponibles {data.get('chips_available')}")
        lines += ["", "| # | Jugador | Pos | Club | Rol |", "|--:|---|---|---|---|"]
        for player in data["players"]:
            mark = " (C)" if player["is_captain"] else " (VC)" if player["is_vice_captain"] else ""
            lines.append(f"| {player['squad_position']} | {player.get('name') or player['element']}"
                         f"{mark} | {player.get('position') or ''} | {player.get('team') or ''} | "
                         f"{player['role']} |")
    acta = s["acta"]
    lines += ["", f"## Acta MILP {_badge(acta)}"]
    adata = acta.get("data") or {}
    if acta["status"] == "ok":
        sel = adata.get("selected") or {}
        names = sel.get("players") or {}

        def name(element):
            return names.get(str(element)) or element

        lines.append(f"- Seleccionado `{adata.get('selected_candidate_key')}` · xP "
                     f"{sel.get('expected_points')} · C {name(sel.get('captain'))} · "
                     f"VC {name(sel.get('vice_captain'))} · chip {sel.get('chip')}")
        lines.append(f"- Entran {[name(e) for e in sel.get('transfers_in') or []]} · salen "
                     f"{[name(e) for e in sel.get('transfers_out') or []]} · hits {sel.get('hits')}")
        for alt in adata.get("alternatives") or ():
            lines.append(f"  - `{alt['candidate_key']}` xP {alt['expected_points']} · "
                         f"violaciones {alt['violations']}")
        lines.append(f"- Acta: {adata.get('acta_path')}")
    elif acta.get("detail"):
        lines.append(f"- {acta['detail']}")
        for path in adata.get("missing") or ():
            lines.append(f"  - falta `{path}`")
    flags = s["flags"].get("data") or {}
    lines += ["", f"## Flags {_badge(s['flags'])}"]
    for flag in flags.get("flagged") or ():
        lines.append(f"- {flag.get('name') or flag['element']} ({flag.get('team') or ''}): "
                     f"{flag.get('status')} · {flag.get('chance_next')}% · {flag.get('news')}")
    for key, title in (("projections", "Proyecciones"), ("strategy_reasons", "Razones"),
                       ("research_signals", "Research"), ("lessons", "Lecciones y notas"),
                       ("execution", "Ejecución")):
        item = s[key]
        lines += ["", f"## {title} {_badge(item)}"]
        if item.get("detail"):
            lines.append(f"- {item['detail']}")
    notes = (s["lessons"].get("data") or {})
    for note in (notes.get("notes") or []) + (notes.get("previous_notes") or []):
        lines.append(f"- [GW{note['gw']} {note['kind']}/{note['source']}] {note['text']}")
    return "\n".join(lines) + "\n"
