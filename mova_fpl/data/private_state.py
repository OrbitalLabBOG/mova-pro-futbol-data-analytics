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
    made = int(transfers.get("made", -1))
    cost = int(transfers.get("cost", -1))
    # `limit` es null en la API de FPL cuando no hay tope de transferencias de la
    # semana (chip wildcard/free hit activo, o ventana sin límite) y puede faltar
    # en capturas parciales. No es un error: el tope es desconocido. Supuesto
    # conservador documentado: 1 FT menos lo ya hecho (nunca inventamos bolsa de
    # FT); `free_transfers_assumed` lo declara en la calidad para que el acta lo
    # diga. El operador puede fijar los FT explícitos con `free_transfers` en el
    # snapshot simplificado (se normaliza a limit=FT, made=0).
    raw_limit = transfers.get("limit")
    limit = None if raw_limit is None else int(raw_limit)
    if not 0 <= bank <= 500 or not 700 <= value <= 1500:
        raise ValueError("bank/value privados fuera de rango")
    if (limit is not None and not 0 <= limit <= 5) or not 0 <= made <= 100 \
            or not 0 <= cost <= 20:
        raise ValueError("bloque de transferencias privado inválido")
    free_transfers = (max(0, min(5, 1 - made)) if limit is None
                      else max(0, min(5, limit - made)))

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
        "free_transfers_assumed": limit is None,
        "available_chips": sorted(
            c["name"] for c in chips if c["status_for_entry"] == "available"
        ),
        "fingerprint": _sha_json(state_for_fingerprint),
    }
    return normalized, quality


def seal(payload: dict, season: str, out_root: Path, *, expected_team_id: int,
         source_label: str | None = None) -> tuple[Path, dict, dict]:
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
    if source_label:  # p. ej. "operator_import"; ausente = captura autenticada
        manifest["source_label"] = source_label
    manifest_raw = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    if dest.exists():
        if (dest / 'team-state.json').read_bytes() == raw and (dest / 'manifest.json').read_bytes() == manifest_raw:
            return dest, manifest, normalized
        raise ValueError('private snapshot observation already sealed with different content')
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


# --------------------------------------------------------- import del operador

#: valor de `source_name`/`source_label` para snapshots leídos por el operador
SOURCE_IMPORT = "operator_import"
SOURCE_CAPTURE = "fpl_authenticated_api"
#: chips de la API; los nombres del motor (`free_hit`...) se aceptan y se traducen
_CHIP_TO_API = {"wildcard": "wildcard", "freehit": "freehit", "free_hit": "freehit",
                "bboost": "bboost", "bench_boost": "bboost", "3xc": "3xc",
                "triple_captain": "3xc"}
_POS_NAMES = {"GKP": 1, "GK": 1, "DEF": 2, "MID": 3, "FWD": 4}


def _pick_from_operator(raw: dict, element_types: dict | None) -> dict:
    element = int(raw["element"])
    etype = raw.get("element_type", raw.get("pos"))
    if isinstance(etype, str):
        etype = _POS_NAMES.get(etype.upper(), etype)
    if etype is None and element_types:
        etype = element_types.get(element)
    if etype is None:
        raise ValueError(f"element_type ausente para element {element}")
    slot = int(raw["position"])  # slot de plantilla 1..15, igual que my-team
    multiplier = raw.get("multiplier")
    if multiplier is None:
        multiplier = (2 if raw.get("is_captain") else 1) if slot <= 11 else 0
    return {
        "element": element, "element_type": int(etype), "position": slot,
        "multiplier": int(multiplier), "is_captain": bool(raw.get("is_captain")),
        "is_vice_captain": bool(raw.get("is_vice_captain")),
        "purchase_price": int(raw["purchase_price"]),
        "selling_price": int(raw["selling_price"]),
    }


def _chip_from_any(raw) -> dict:
    """Acepta un nombre (= disponible) o un dict estilo API; devuelve el chip exacto."""
    if isinstance(raw, str):
        raw = {"name": raw, "status_for_entry": "available"}
    name = _CHIP_TO_API.get(str(raw.get("name", "")).lower())
    if name is None:
        raise ValueError(f"chip privado desconocido: {raw.get('name')}")
    return {
        "name": name, "number": int(raw.get("number") or 1),
        "status_for_entry": raw.get("status_for_entry", "available"),
        "is_pending": bool(raw.get("is_pending", False)),
        "start_event": raw.get("start_event"), "stop_event": raw.get("stop_event"),
    }


def normalize_import(doc: dict, *, expected_team_id: int, now: datetime | None = None,
                     deadline_lookup=None, element_types: dict | None = None) -> dict:
    """Snapshot del operador (o my-team crudo/ya sanitizado) -> payload para `validate`.

    Formatos aceptados:
    * `mova-fpl-private-team-state-v1` ya sanitizado: solo se podan claves ajenas.
    * my-team crudo de FPL (`picks`, `transfers`, `chips`, `event`/`gw`).
    * Simplificado: `picks[{element, position(slot 1..15), selling_price,
      purchase_price, element_type|pos?, multiplier?, is_captain, is_vice_captain}]`,
      `bank` en DÉCIMAS (55 = £5.5M, unidad de la API), `free_transfers` (se guarda
      como limit=FT, made=0), `chips` (lista de nombres disponibles o dicts API),
      `event`/`gw`, `observed_at` (UTC con zona; por defecto ahora).
    Claves desconocidas se descartan; los precios/bank en millones se rechazan por
    rango en `validate` en vez de adivinar la unidad.
    """
    if not isinstance(doc, dict):
        raise ValueError("el snapshot debe ser un objeto JSON")
    now = now or datetime.now(timezone.utc)
    team_id = doc.get("team_id")
    if team_id is not None and int(team_id) != int(expected_team_id):
        raise ValueError(f"team_id inesperado: {team_id}")
    event = doc.get("event")
    gw = event.get("id") if isinstance(event, dict) else (event if event is not None else doc.get("gw"))
    if gw is None:
        raise ValueError("snapshot sin event/gw")
    deadline = event.get("deadline_time") if isinstance(event, dict) else doc.get("deadline_time")
    if not deadline and deadline_lookup:
        deadline = deadline_lookup(int(gw))
    if not deadline:
        raise ValueError(f"sin deadline_time para GW{gw}; inclúyelo en el snapshot")

    picks = [_pick_from_operator(p, element_types) for p in (doc.get("picks") or ())]
    tr = doc.get("transfers")
    if isinstance(tr, dict):
        transfers = {
            "bank": tr.get("bank"), "value": tr.get("value"), "limit": tr.get("limit"),
            "made": tr.get("made"), "cost": tr.get("cost", 0), "status": tr.get("status", ""),
        }
    else:
        if doc.get("bank") is None or doc.get("free_transfers") is None:
            raise ValueError("snapshot simplificado exige bank (décimas) y free_transfers")
        transfers = {"bank": doc["bank"], "limit": int(doc["free_transfers"]), "made": 0,
                     "cost": 0, "status": SOURCE_IMPORT, "value": doc.get("value")}
    if transfers["made"] is None:
        raise ValueError("transfers.made ausente")
    if transfers["value"] is None:  # valor del equipo = ventas + banco no se mezcla: sólo plantilla
        transfers["value"] = sum(p["selling_price"] for p in picks)
    transfers["bank"] = int(transfers["bank"])
    return {
        "schema": SCHEMA,
        "observed_at": doc.get("observed_at") or now.isoformat(),
        "team_id": int(expected_team_id),
        "event": {"id": int(gw), "deadline_time": str(deadline)},
        "picks_last_updated": doc.get("picks_last_updated"),
        "picks": picks,
        "transfers": {k: (int(v) if k not in ("status", "limit") and v is not None else v)
                      for k, v in transfers.items()},
        "chips": [_chip_from_any(c) for c in (doc.get("chips") or ())],
    }
