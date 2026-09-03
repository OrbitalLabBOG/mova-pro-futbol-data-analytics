"""Cierre causal, local y no ejecutable de un shadow vivo congelado.

La herramienta solo hace GET a la API oficial de FPL. No usa la base ni el
scheduler de producción y escribe evidencia content-addressed fuera del repo.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.analytics.strategy_shadow import (
    aggregate_strategy_shadow,
    settle_strategy_shadow,
)
from mova_fpl.data.sources import fetch_bootstrap, fetch_event_live, fetch_team_picks
from mova_fpl.ops.collector.contracts import canonical_bytes


SCHEMA = "mova-live-shadow-settlement-v1"
MANUAL_SCHEMA = "mova-manual-outcome-v1"


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _code_evidence() -> dict:
    strategy_source = inspect.getsourcefile(settle_strategy_shadow)
    if strategy_source is None:
        raise RuntimeError("no se pudo resolver el código de strategy_shadow")
    return {
        "live_settlement_sha256": _sha(Path(__file__).read_bytes()),
        "strategy_shadow_sha256": _sha(Path(strategy_source).read_bytes()),
    }


def _read_json(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} no contiene un objeto JSON")
    return value, raw


def load_frozen_observation(directory: Path) -> tuple[dict, dict, dict]:
    """Carga EXP008 y demuestra que el bundle no cambió desde el deadline."""
    observation, observation_raw = _read_json(directory / "live-observation.json")
    manifest, manifest_raw = _read_json(directory / "manifest.json")
    bundle, bundle_raw = _read_json(directory / "gw03-shadow.json")
    report_raw = (directory / "gw03-shadow.md").read_bytes()

    if observation.get("schema") != "mova-long-horizon-live-observation-v1":
        raise ValueError("observación live incompatible")
    if manifest.get("schema") != "mova-long-horizon-live-manifest-v1":
        raise ValueError("manifest live incompatible")
    if observation.get("experiment_id") != manifest.get("experiment_id"):
        raise ValueError("experiment_id inconsistente")
    expected_bundle = observation.get("outputs", {}).get("candidate_bundle_sha256")
    if _sha(bundle_raw) != expected_bundle:
        raise ValueError("hash del bundle congelado no coincide")
    expected_report = observation.get("outputs", {}).get("report_sha256")
    if _sha(report_raw) != expected_report:
        raise ValueError("hash del reporte congelado no coincide")
    for key in ("season", "gw", "deadline_at"):
        if observation.get(key) != manifest.get("target", {}).get(key):
            raise ValueError(f"{key} inconsistente entre observación y manifest")
        if key in bundle and bundle.get(key) != observation.get(key):
            raise ValueError(f"{key} inconsistente en bundle")

    shadow = bundle.get("strategy_shadow") or {}
    if shadow.get("selected_for_execution") is not False:
        raise ValueError("el shadow congelado adquirió autoridad de ejecución")
    if shadow.get("season") != observation.get("season"):
        raise ValueError("temporada del shadow inconsistente")
    if int(shadow.get("gw", 0)) != int(observation.get("gw", 0)):
        raise ValueError("GW del shadow inconsistente")
    evidence = {
        "experiment_id": observation["experiment_id"],
        "observation_sha256": _sha(observation_raw),
        "manifest_sha256": _sha(manifest_raw),
        "bundle_sha256": _sha(bundle_raw),
        "report_sha256": _sha(report_raw),
    }
    return observation, bundle, evidence


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("deadline sin zona horaria")
    return parsed.astimezone(timezone.utc)


def event_readiness(bootstrap: dict, gw: int,
                    expected_deadline: str | None = None) -> dict:
    events = {
        int(row["id"]): row for row in bootstrap.get("events") or []
        if row.get("id") is not None
    }
    event = events.get(int(gw))
    if event is None:
        raise ValueError(f"bootstrap oficial no contiene GW{gw}")
    finished = bool(event.get("finished"))
    checked = bool(event.get("data_checked"))
    official_deadline = event.get("deadline_time")
    deadline_matches = (
        expected_deadline is None
        or (official_deadline is not None
            and _instant(str(official_deadline)) == _instant(expected_deadline))
    )
    ready = finished and checked and deadline_matches
    return {
        "gw": int(gw),
        "deadline_at": official_deadline,
        "deadline_matches_frozen_observation": deadline_matches,
        "finished": finished,
        "data_checked": checked,
        "ready": ready,
        "status": (
            "deadline_mismatch" if not deadline_matches else
            "ready" if ready else "waiting_for_finished_data_checked"
        ),
    }


def _normalize_live(payload: dict) -> list[dict]:
    rows = []
    for item in payload.get("elements") or []:
        stats = item.get("stats") or {}
        rows.append({
            "element": int(item["id"]),
            "minutes": int(stats.get("minutes") or 0),
            "total_points": int(stats.get("total_points") or 0),
        })
    if not rows:
        raise ValueError("event-live oficial no contiene jugadores")
    return rows


def _normalize_players(bootstrap: dict) -> list[dict]:
    rows = []
    for item in bootstrap.get("elements") or []:
        rows.append({
            "element": int(item["id"]),
            "web_name": str(item.get("web_name") or ""),
            "team_id": int(item.get("team") or 0),
            "element_type": int(item.get("element_type") or 0),
            "now_cost": int(item.get("now_cost") or 0),
        })
    return rows


def manual_from_file(path: Path, *, season: str, gw: int) -> tuple[dict, dict]:
    payload, raw = _read_json(path)
    if payload.get("schema") != MANUAL_SCHEMA:
        raise ValueError("outcome manual incompatible")
    if payload.get("season") != season or int(payload.get("gw", 0)) != int(gw):
        raise ValueError("outcome manual no corresponde a season/GW")
    if "actual_points" not in payload:
        raise ValueError("outcome manual sin actual_points")
    manual = {
        "fingerprint": payload.get("fingerprint"),
        "expected_points": payload.get("expected_points"),
        "actual_points": int(payload["actual_points"]),
    }
    evidence = {
        "source": "explicit_manual_outcome",
        "artifact_sha256": _sha(raw),
        "payload": payload,
    }
    return manual, evidence


def manual_from_public_picks(payload: dict, live: list[dict], *, season: str,
                             gw: int) -> tuple[dict, dict]:
    """Construye evidencia de la decisión observada, sin credenciales ni writes."""
    history = payload.get("entry_history") or {}
    if int(history.get("event") or 0) != int(gw):
        raise ValueError("picks públicos no corresponden a la GW")
    picks = sorted(payload.get("picks") or [], key=lambda row: int(row["position"]))
    if len(picks) != 15:
        raise ValueError("picks públicos no contienen 15 jugadores")
    score = {int(row["element"]): int(row["total_points"]) for row in live}
    multiplier_points = sum(
        score.get(int(row["element"]), 0) * int(row.get("multiplier") or 0)
        for row in picks
    )
    transfer_cost = int(history.get("event_transfers_cost") or 0)
    reported_points = int(history["points"])
    fingerprint_payload = {
        "season": season,
        "gw": int(gw),
        "active_chip": payload.get("active_chip"),
        "picks": [{
            "element": int(row["element"]),
            "position": int(row["position"]),
            "multiplier": int(row.get("multiplier") or 0),
            "is_captain": bool(row.get("is_captain")),
            "is_vice_captain": bool(row.get("is_vice_captain")),
        } for row in picks],
        "event_transfers_cost": transfer_cost,
    }
    public_fingerprint = _sha(canonical_bytes(fingerprint_payload))[:16]
    manual = {
        "fingerprint": f"public-picks:{public_fingerprint}",
        "expected_points": None,
        "actual_points": reported_points,
    }
    evidence = {
        "source": "official_public_picks_get",
        "fingerprint_schema": "canonical public picks, not Decision.fingerprint",
        "fingerprint": manual["fingerprint"],
        "reported_points": reported_points,
        "multiplier_points_before_hits": multiplier_points,
        "event_transfers_cost": transfer_cost,
        "reconciliation_delta": reported_points - (multiplier_points - transfer_cost),
        "active_chip": payload.get("active_chip"),
        "automatic_subs": payload.get("automatic_subs") or [],
    }
    return manual, evidence


def build_settlement(*, observation: dict, bundle: dict, frozen_evidence: dict,
                     bootstrap: dict, bootstrap_raw: bytes, event_live: dict,
                     event_live_raw: bytes, manual: dict | None = None,
                     manual_evidence: dict | None = None,
                     observed_at: str | None = None) -> dict:
    gw = int(observation["gw"])
    readiness = event_readiness(
        bootstrap, gw, expected_deadline=str(observation["deadline_at"]),
    )
    if not readiness["ready"]:
        raise RuntimeError(f"GW{gw} todavía no está finished + data_checked")
    live = _normalize_live(event_live)
    settlement = settle_strategy_shadow(
        bundle["strategy_shadow"],
        season=str(observation["season"]),
        gw=gw,
        live=live,
        players=_normalize_players(bootstrap),
        manual=manual,
    )
    gate = aggregate_strategy_shadow([settlement])
    return {
        "schema": SCHEMA,
        "experiment_id": observation["experiment_id"],
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": observation["season"],
        "gw": gw,
        "status": "settled",
        "selected_for_execution": False,
        "production_writes": 0,
        "network_policy": "official FPL GET only",
        "code": _code_evidence(),
        "frozen_inputs": frozen_evidence,
        "official": {
            **readiness,
            "bootstrap_sha256": _sha(bootstrap_raw),
            "event_live_sha256": _sha(event_live_raw),
            "live_rows": len(live),
        },
        "manual_evidence": manual_evidence or {
            "source": "not_provided",
            "status": "pending_explicit_or_public_observation",
        },
        "settlement": settlement,
        "gate": gate,
    }


def _write_content_addressed(directory: Path, payload: dict) -> tuple[Path, str]:
    raw = canonical_bytes(payload)
    digest = _sha(raw)
    path = directory / f"settlement-gw{int(payload['gw']):02d}-{digest[:16]}.json"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise RuntimeError("colisión de artefacto content-addressed")
    return path, digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("probe", "settle"))
    parser.add_argument("--experiment-dir", type=Path, required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--manual-json", type=Path)
    source.add_argument("--team-id", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    observation, bundle, frozen = load_frozen_observation(args.experiment_dir)
    bootstrap_raw = fetch_bootstrap()
    bootstrap = json.loads(bootstrap_raw)
    readiness = event_readiness(
        bootstrap, int(observation["gw"]),
        expected_deadline=str(observation["deadline_at"]),
    )
    if args.command == "probe" or not readiness["ready"]:
        print(json.dumps({
            "experiment_id": observation["experiment_id"],
            "frozen_inputs": frozen,
            "official": readiness,
            "writes": 0,
        }, sort_keys=True))
        return 0 if readiness["ready"] else 3

    event_live_raw = fetch_event_live(int(observation["gw"]))
    event_live = json.loads(event_live_raw)
    live = _normalize_live(event_live)
    manual = manual_evidence = None
    if args.manual_json:
        manual, manual_evidence = manual_from_file(
            args.manual_json,
            season=str(observation["season"]), gw=int(observation["gw"]),
        )
    elif args.team_id is not None:
        public_raw = fetch_team_picks(args.team_id, int(observation["gw"]))
        manual, manual_evidence = manual_from_public_picks(
            json.loads(public_raw), live,
            season=str(observation["season"]), gw=int(observation["gw"]),
        )
        manual_evidence["artifact_sha256"] = _sha(public_raw)

    payload = build_settlement(
        observation=observation,
        bundle=bundle,
        frozen_evidence=frozen,
        bootstrap=bootstrap,
        bootstrap_raw=bootstrap_raw,
        event_live=event_live,
        event_live_raw=event_live_raw,
        manual=manual,
        manual_evidence=manual_evidence,
    )
    path, digest = _write_content_addressed(args.experiment_dir, payload)
    print(json.dumps({
        "status": "settled",
        "artifact_path": str(path),
        "artifact_sha256": digest,
        "promotion_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
