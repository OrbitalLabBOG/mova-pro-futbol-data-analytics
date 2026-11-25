"""Research del operador -> documento `mova-research-adjustments-v1` para el acta.

Esta capa solo lee archivo/notas, normaliza nombres de chip en la frontera
(API `freehit` -> motor `free_hit`) y escribe el JSON que `cli.live
--interventions` valida y aplica (la validación estricta vive en
`mova_fpl.agent.research`; `ops` no importa `agent`).

Forma de nota admitida (kind hypothesis|constraint|reason, no decision): el
campo `players_json` lleva `{"research_adjustment": {...}}` con las mismas claves
del documento (`adjustments`, `lock_out`, `lock_in`, `block_chips`, `allow_chips`).
El texto libre de la nota es la justificación; cualquier otra nota se ignora.
"""
from __future__ import annotations

import json
from pathlib import Path

from mova_fpl.data.live import CHIP_API

DOC_SCHEMA = "mova-research-adjustments-v1"
NOTE_KINDS = ("hypothesis", "constraint", "reason")
NOTE_KEY = "research_adjustment"
_LIST_KEYS = ("lock_out", "lock_in", "block_chips", "allow_chips")
_ENGINE_CHIPS = set(CHIP_API.values())


def _chip(name) -> str:
    key = str(name).strip().lower()
    key = CHIP_API.get(key, key)  # freehit -> free_hit; engine names pasan
    if key not in _ENGINE_CHIPS:
        raise ValueError(f"chip desconocido: {name!r}")
    return key


def normalize_doc(doc: dict, *, gw: int) -> dict:
    """Copia superficial con chips en nombres del motor; no valida el resto."""
    if not isinstance(doc, dict):
        raise ValueError("el archivo de interventions debe ser un objeto JSON")
    out = dict(doc)
    out.setdefault("gw", int(gw))
    for key in ("block_chips", "allow_chips"):
        if out.get(key):
            out[key] = sorted({_chip(c) for c in out[key]})
    return out


def load_file(path: str | Path, *, gw: int) -> dict:
    return normalize_doc(json.loads(Path(path).read_text(encoding="utf-8")), gw=gw)


def doc_from_notes(db, *, season: str, gw: int) -> dict | None:
    """Documento fusionado de las notas con `research_adjustment`; None si no hay."""
    if db is None:
        return None
    try:
        notes = db.strategy_notes(season=season, gw=gw, kinds=NOTE_KINDS)
    except Exception:  # noqa: BLE001 - sin tabla/notas no hay research que aplicar
        return None
    adjustments: dict[int, dict] = {}
    lists: dict[str, set] = {key: set() for key in _LIST_KEYS}
    sources, texts = [], []
    # `strategy_notes` viene de la más nueva a la más vieja: la nueva gana por elemento.
    for note in notes:
        players = note.get("players") if "players" in note else note.get("players_json")
        if isinstance(players, str):
            try:
                players = json.loads(players)
            except ValueError:
                continue
        block = players.get(NOTE_KEY) if isinstance(players, dict) else None
        if note.get("superseded") or not isinstance(block, dict):
            continue
        for item in block.get("adjustments") or ():
            if isinstance(item, dict) and "element" in item:
                adjustments.setdefault(int(item["element"]), item)
        for key in _LIST_KEYS:
            lists[key].update(block.get(key) or ())
        sources.append(f"{note.get('source') or 'note'}:{note.get('actor') or '?'}")
        texts.append(str(note.get("text") or "").strip())
    if not adjustments and not any(lists.values()):
        return None
    doc = {"schema": DOC_SCHEMA, "gw": int(gw),
           "source": "notes(" + ",".join(sorted(set(sources))) + ")",
           "rationale": " | ".join(t for t in texts if t)[:1500],
           "adjustments": [adjustments[k] for k in sorted(adjustments)]}
    doc.update({key: sorted(values) for key, values in lists.items() if values})
    return normalize_doc(doc, gw=gw)


def merge_docs(first: dict | None, second: dict | None) -> dict | None:
    """Fusiona dos documentos de la misma GW; `second` gana por elemento."""
    if not first or not second:
        return first or second
    by_el = {int(a["element"]): a for a in first.get("adjustments") or ()}
    by_el.update({int(a["element"]): a for a in second.get("adjustments") or ()})
    out = {"schema": DOC_SCHEMA, "gw": second.get("gw", first.get("gw")),
           "source": f"{first.get('source', '')}+{second.get('source', '')}".strip("+"),
           "rationale": " | ".join(x for x in (first.get("rationale"),
                                               second.get("rationale")) if x),
           "adjustments": [by_el[k] for k in sorted(by_el)]}
    for key in _LIST_KEYS:
        merged = sorted(set(first.get(key) or ()) | set(second.get(key) or ()))
        if merged:
            out[key] = merged
    return out


def write_doc(doc: dict, out_dir: Path) -> Path:
    path = Path(out_dir) / "interventions.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path
