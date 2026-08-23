"""Validación y snapshots del estado autenticado ya sanitizado.

Este módulo no conoce sesiones, cookies ni browser tooling. Recibe un documento
con allowlist producido fuera del engine y lo trata como entrada no confiable.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "mova-fpl-private-team-state-v1"
PARSER = "private-team-state-v1"
CHIP_NAMES = {"wildcard", "freehit", "bboost", "3xc"}
CHIP_STATUS = {"available", "played", "unavailable"}
TOP_FIELDS = {"schema", "observed_at", "team_id", "event", "picks_last_updated",
              "picks", "transfers", "chips"}
PICK_FIELDS = {"element", "element_type", "position", "multiplier", "is_captain",
               "is_vice_captain", "purchase_price", "selling_price"}
TRANSFER_FIELDS = {"bank", "value", "limit", "made", "cost", "status"}
CHIP_FIELDS = {"name", "number", "status_for_entry", "is_pending", "start_event",
               "stop_event"}


def _sha_json(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("observed_at debe incluir zona horaria")
    return parsed.astimezone(timezone.utc)


def validate(payload: dict, *, expected_team_id: int | None = None) -> tuple[dict, dict]:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("schema privado ausente o incompatible")
    unexpected = set(payload) - TOP_FIELDS
    if unexpected:
        raise ValueError(f"campos privados no permitidos: {sorted(unexpected)}")
    team_id = int(payload.get("team_id", 0))
    if team_id <= 0 or (expected_team_id is not None and team_id != int(expected_team_id)):
        raise ValueError(f"team_id inesperado: {team_id}")
    observed = _utc(payload["observed_at"])
    event = payload.get("event") or {}
    if set(event) - {"id", "deadline_time"}:
        raise ValueError("evento privado contiene campos no permitidos")
    gw = int(event.get("id", 0))
    if not 1 <= gw <= 38 or not event.get("deadline_time"):
        raise ValueError("evento privado inválido")
    _utc(event["deadline_time"])

    picks = list(payload.get("picks") or ())
    if len(picks) != 15:
        raise ValueError(f"estado privado tiene {len(picks)} jugadores; se esperaban 15")
    elements = [int(p.get("element", 0)) for p in picks]
    positions = [int(p.get("position", 0)) for p in picks]
    if min(elements) <= 0 or len(set(elements)) != 15:
        raise ValueError("elements privados inválidos o duplicados")
    if set(positions) != set(range(1, 16)):
        raise ValueError("positions privadas deben ser exactamente 1..15")
    counts = Counter(int(p.get("element_type", 0)) for p in picks)
    if counts != Counter({1: 2, 2: 5, 3: 5, 4: 3}):
        raise ValueError(f"cuotas por posición inválidas: {dict(counts)}")
    if sum(bool(p.get("is_captain")) for p in picks) != 1:
        raise ValueError("se esperaba exactamente un capitán")
    if sum(bool(p.get("is_vice_captain")) for p in picks) != 1:
        raise ValueError("se esperaba exactamente un vicecapitán")
    for pick in picks:
        if set(pick) != PICK_FIELDS:
            raise ValueError("pick privado no cumple allowlist exacta")
        for field in ("purchase_price", "selling_price"):
            value = int(pick.get(field, 0))
            if not 30 <= value <= 200:
                raise ValueError(f"{field} fuera de rango para element {pick.get('element')}")
        if int(pick.get("multiplier", -1)) not in {0, 1, 2, 3}:
            raise ValueError(f"multiplier inválido para element {pick.get('element')}")

    transfers = payload.get("transfers") or {}
    if set(transfers) != TRANSFER_FIELDS:
        raise ValueError("transferencias privadas no cumplen allowlist exacta")
    bank, value = int(transfers.get("bank", -1)), int(transfers.get("value", -1))
    limit, made = int(transfers.get("limit", -1)), int(transfers.get("made", -1))
    cost = int(transfers.get("cost", -1))
    if not 0 <= bank <= 500 or not 700 <= value <= 1500:
        raise ValueError("bank/value privados fuera de rango")
    if not 0 <= limit <= 5 or not 0 <= made <= 100 or not 0 <= cost <= 20:
        raise ValueError("bloque de transferencias privado inválido")
    free_transfers = max(0, min(5, limit - made))

    chips = list(payload.get("chips") or ())
    if len(chips) > 4 or len({str(c.get("name")) for c in chips}) != len(chips):
        raise ValueError("lista privada de chips inválida")
    for chip in chips:
        if set(chip) != CHIP_FIELDS:
            raise ValueError("chip privado no cumple allowlist exacta")
        if chip.get("name") not in CHIP_NAMES:
            raise ValueError(f"chip privado desconocido: {chip.get('name')}")
        if chip.get("status_for_entry") not in CHIP_STATUS:
            raise ValueError(f"estado de chip desconocido: {chip.get('status_for_entry')}")

    normalized = {
        "schema": SCHEMA,
        "observed_at": observed.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "team_id": team_id,
        "event": {"id": gw, "deadline_time": event["deadline_time"]},
        "picks_last_updated": payload.get("picks_last_updated"),
        "picks": sorted(picks, key=lambda p: int(p["position"])),
        "transfers": {
            "bank": bank, "value": value, "limit": limit, "made": made,
            "cost": cost, "status": str(transfers.get("status", "")),
        },
        "chips": sorted(chips, key=lambda c: str(c["name"])),
    }
    state_for_fingerprint = {k: v for k, v in normalized.items() if k != "observed_at"}
    quality = {
        "parser": PARSER, "team_id": team_id, "gw": gw, "players": 15,
        "bank_tenths": bank, "team_value_tenths": value,
        "free_transfers": free_transfers, "transfers_made": made,
        "available_chips": sorted(
            c["name"] for c in chips if c["status_for_entry"] == "available"
        ),
        "fingerprint": _sha_json(state_for_fingerprint),
    }
    return normalized, quality


def seal(payload: dict, season: str, out_root: Path, *, expected_team_id: int) -> tuple[Path, dict, dict]:
    normalized, quality = validate(payload, expected_team_id=expected_team_id)
    observed = _utc(normalized["observed_at"])
    stamp = observed.strftime("%Y%m%dT%H%M%S%fZ")
    gw = int(normalized["event"]["id"])
    dest = out_root / season / f"gw{gw:02d}" / stamp
    raw = (json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    payload_sha = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema": "mova-fpl-private-team-state-manifest-v1",
        "captured_at": normalized["observed_at"],
        "source": "FPL authenticated team-state GET via isolated browser",
        "parser": PARSER,
        "payload_sha256": payload_sha,
        "quality": quality,
    }
    manifest_raw = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.mkdir(parents=True, exist_ok=False)
    (tmp / "team-state.json").write_bytes(raw)
    (tmp / "manifest.json").write_bytes(manifest_raw)
    tmp.replace(dest)
    return dest, manifest, normalized


def load(path: Path, *, expected_team_id: int | None = None) -> tuple[dict, dict]:
    raw = (path / "team-state.json").read_bytes()
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    actual = hashlib.sha256(raw).hexdigest()
    if actual != manifest.get("payload_sha256"):
        raise ValueError("snapshot privado alterado o corrupto")
    normalized, quality = validate(json.loads(raw), expected_team_id=expected_team_id)
    if quality["fingerprint"] != (manifest.get("quality") or {}).get("fingerprint"):
        raise ValueError("fingerprint privado no coincide con el manifest")
    return normalized, manifest
