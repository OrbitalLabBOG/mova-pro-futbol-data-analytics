"""Ensambla el paquete `mova-fpl-manual-verified-execution-v2` para `record-manual`.

Modelo copiloto (ADR-021): el owner valida un plan en el chat, el cambio se aplica
en FPL (a mano o con `fpl-web-ops`) y este comando arma el paquete a partir de los
snapshots privados pre/post y la evidencia browser. No escribe en FPL ni en ops.db:
solo deja dos archivos bajo `MOVA_ARTIFACT_ROOT` y los valida con el mismo código
que usará `mova execute record-manual` (`supervised._validate_v2`).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from mova_fpl.data.private_state import validate as validate_private_state
from mova_fpl.ops.config import RuntimeConfig
from mova_fpl.ops.db import OpsDB, sha256_json
from mova_fpl.ops.memory import sanitize_text
from mova_fpl.ops.supervised import SCHEMA, _assert_v2_artifacts_under_root, _utc, _validate_v2

RESULT_SCHEMA = "mova-manual-package-result-v1"
POLICY_VERSION = "adr-021-copilot-owner-validated-1.0.0"
OPERATIONS = ("lineup", "captaincy", "transfers", "hits", "chip")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _state(path: Path) -> tuple[Path, dict, dict, dict]:
    """Acepta el directorio del snapshot o su `team-state.json`."""
    directory = path if path.is_dir() else path.parent
    file = directory / "team-state.json"
    if not file.is_file():
        raise FileNotFoundError(f"team-state.json no existe en {directory}")
    raw = json.loads(file.read_text(encoding="utf-8"))
    normalized, quality = validate_private_state(raw)
    reference = {"artifact_path": str(directory), "payload_sha256": _sha256(file),
                 "fingerprint": quality["fingerprint"]}
    return directory, normalized, quality, reference


def parse_operations(values: list[str] | None) -> list[str]:
    operations = sorted({item.strip() for value in values or () for item in value.split(",")
                         if item.strip()})
    invalid = set(operations) - set(OPERATIONS)
    if not operations or invalid:
        raise ValueError(f"--operations inválidas: {sorted(invalid) or 'vacías'}; "
                         f"usar {','.join(OPERATIONS)}")
    return operations


def build_manual_package(config: RuntimeConfig, *, gw: int, approved_by: str,
                         approved_at: str, operations: list[str], pre_state: Path,
                         post_state: Path, evidence: Path, rationale: str,
                         season: str | None = None, started_at: str | None = None,
                         finished_at: str | None = None, expires_at: str | None = None,
                         chip: str | None = None, hits: int | None = None,
                         out: Path | None = None, overwrite: bool = False,
                         db: OpsDB | None = None) -> dict:
    season = season or config.season
    gw = int(gw)
    cycle_id = f"{season}-gw{gw:02d}"
    if not approved_by.strip():
        raise ValueError("--approved-by es obligatorio")
    clean_rationale, _ = sanitize_text(rationale)
    if not clean_rationale:
        raise ValueError("--rationale es obligatorio")
    operations = parse_operations(operations)
    evidence = Path(evidence)
    if not evidence.is_file():
        raise FileNotFoundError(evidence)
    _, pre, pre_quality, pre_ref = _state(Path(pre_state))
    _, post, post_quality, post_ref = _state(Path(post_state))
    if int(post["event"]["id"]) != gw:
        raise ValueError(f"post-state corresponde a GW{post['event']['id']}, no a GW{gw}")
    deadline = _utc(post["event"]["deadline_time"], "post.deadline_time")
    authorized = _utc(approved_at, "--approved-at")
    pre_observed = _utc(pre["observed_at"], "pre.observed_at")
    post_observed = _utc(post["observed_at"], "post.observed_at")
    started = _utc(started_at, "--started-at") if started_at else max(authorized, pre_observed)
    finished = _utc(finished_at, "--finished-at") if finished_at else post_observed
    expires = _utc(expires_at, "--expires-at") if expires_at else deadline

    pre_elements = {int(pick["element"]) for pick in pre["picks"]}
    post_picks = sorted(post["picks"], key=lambda pick: int(pick["position"]))
    post_elements = {int(pick["element"]) for pick in post_picks}
    transfers_in = sorted(post_elements - pre_elements)
    transfers_out = sorted(pre_elements - post_elements)
    if hits is None:
        hits = int((post.get("transfers") or {}).get("cost") or 0)
    if chip is None:
        before = {row["name"]: row["status_for_entry"] for row in pre.get("chips") or ()}
        after = {row["name"]: row["status_for_entry"] for row in post.get("chips") or ()}
        used = sorted(name for name, status in before.items()
                      if status == "available" and after.get(name) != "available")
        if len(used) > 1:
            raise ValueError(f"pre/post muestran varios chips consumidos: {used}")
        chip = used[0] if used else None
    risk_class = ("R2" if not (transfers_in or transfers_out or hits or chip)
                  and set(operations) <= {"lineup", "captaincy"} else "R3")
    action_level = {"R2": "A2", "R3": "A3"}[risk_class]

    players = [{
        "element": int(pick["element"]), "squad_position": int(pick["position"]),
        "role": "starter" if int(pick["position"]) <= 11 else "bench",
        "is_captain": bool(pick.get("is_captain")),
        "is_vice_captain": bool(pick.get("is_vice_captain")),
    } for pick in post_picks]

    package_path = Path(out) if out else (
        config.artifact_root / "manual" / f"gw{gw:02d}-execution-v2.json")
    artifact_dir = package_path.parent / package_path.stem
    decision_path = artifact_dir / "decision.json"
    decision_artifact = {
        "schema": "mova-copilot-owner-decision-v1", "season": season, "gw": gw,
        "cycle_id": cycle_id, "approved_by": approved_by, "approved_at": _iso(authorized),
        "operations": operations, "players": players,
        "transfers": {"in": transfers_in, "out": transfers_out, "hits": hits},
        "chip": chip, "rationale": clean_rationale,
        "pre_fingerprint": pre_quality["fingerprint"],
        "post_fingerprint": post_quality["fingerprint"],
    }
    decision_bytes = (json.dumps(decision_artifact, ensure_ascii=False, indent=2,
                                 sort_keys=True) + "\n").encode("utf-8")
    decision_sha = hashlib.sha256(decision_bytes).hexdigest()
    envelope_sha = decision_sha
    if db is not None and db.path.is_file():
        try:
            envelope = db.latest_decision_envelope(cycle_id)
            if envelope:
                envelope_sha = str(envelope["content_sha256"])
        except Exception:  # noqa: BLE001 - el envelope es referencia opcional
            pass
    suffix = post_quality["fingerprint"][:12]
    strategy = {
        "strategy_id": f"strategy_manual_{cycle_id}_{suffix}", "window_name": f"gw{gw:02d}",
        "policy_version": POLICY_VERSION,
        "inventory": {row["name"]: row["status_for_entry"] for row in post.get("chips") or ()},
        "recommended_chip": chip,
        "status": "chip_used_verified" if chip else "hold_verified",
        "rationale": clean_rationale,
    }
    strategy["manifest_sha256"] = sha256_json(strategy)
    diff = {"in": transfers_in, "out": transfers_out, "hits": hits}
    package = {
        "schema": SCHEMA, "season": season, "gw": gw, "cycle_id": cycle_id,
        "deadline_at": _iso(deadline),
        "authorization": {
            "action_level": action_level, "risk_class": risk_class,
            "authorized_by": approved_by, "policy_version": POLICY_VERSION,
            "authorized_at": _iso(authorized), "expires_at": _iso(expires),
            "allowed_operations": operations,
        },
        "decision": {
            "decision_id": f"decision_manual_{cycle_id}_{suffix}", "mode": "supervised",
            "policy_version": POLICY_VERSION, "status": "executed_verified",
            "expected_points": None, "chip": chip, "transfers": diff,
            "fingerprint": post_quality["fingerprint"], "players": players,
            "artifact_path": str(decision_path), "manifest_sha256": decision_sha,
        },
        "strategy": strategy,
        "execution": {
            "execution_id": f"execution_manual_{cycle_id}_{suffix}",
            "action_level": action_level, "envelope_sha256": envelope_sha,
            "status": "verified", "started_at": _iso(started), "finished_at": _iso(finished),
            "evidence_path": str(evidence), "evidence_sha256": _sha256(evidence),
        },
        "pre_team_state": pre_ref, "post_team_state": post_ref,
        "verification_checks": [
            {"check_id": f"check_{name}_{cycle_id}_{suffix}", "check_name": name,
             "expected": expected, "observed": observed, "passed": expected == observed}
            for name, expected, observed in (
                ("authorization", {"approved_by": approved_by, "operations": operations},
                 {"approved_by": approved_by, "operations": operations}),
                ("pre_state", pre_ref["fingerprint"], pre_quality["fingerprint"]),
                ("post_reload_state", post_quality["fingerprint"], post_ref["fingerprint"]),
                ("exact_diff", diff, {"in": transfers_in, "out": transfers_out, "hits": hits}),
            )
        ],
    }
    package_bytes = (json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True)
                     + "\n").encode("utf-8")
    if package_path.exists() and package_path.read_bytes() != package_bytes and not overwrite:
        raise FileExistsError(f"{package_path} ya existe con otro contenido; usar --overwrite")
    if decision_path.exists() and decision_path.read_bytes() != decision_bytes and not overwrite:
        raise FileExistsError(f"{decision_path} ya existe con otro contenido; usar --overwrite")
    created = not decision_path.exists()
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_bytes(decision_bytes)
    try:
        _assert_v2_artifacts_under_root(package, config.artifact_root)
        validation = _validate_v2(package)
    except Exception:
        if created:
            decision_path.unlink(missing_ok=True)
        raise
    package_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = package_path.with_suffix(package_path.suffix + ".tmp")
    tmp.write_bytes(package_bytes)
    tmp.replace(package_path)
    package_sha = hashlib.sha256(package_bytes).hexdigest()
    return {
        "schema": RESULT_SCHEMA, "status": "ready", "package_schema": SCHEMA,
        "package_path": str(package_path), "package_sha256": package_sha,
        "decision_artifact": str(decision_path), "cycle_id": cycle_id,
        "action_level": action_level, "risk_class": risk_class,
        "allowed_operations": validation["allowed_operations"],
        "transfers_in": validation["transfers_in"], "transfers_out": validation["transfers_out"],
        "hits": validation["hits"], "chip": validation["chip"],
        "pre_fingerprint": validation["pre_fingerprint"],
        "post_fingerprint": validation["post_fingerprint"],
        "next_command": [
            "mova", "execute", "record-manual", "--package", str(package_path),
            "--actor", "<actor>", "--reason", "<razón>",
            "--idempotency-key", f"manual-verified:{cycle_id}:{package_sha[:12]}",
        ],
        "runtime_mutated": False, "fpl_mutated": False,
    }
