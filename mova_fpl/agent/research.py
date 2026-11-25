"""Ajustes de research del operador sobre las ENTRADAS del acta. Puro.

Un documento JSON (`mova-research-adjustments-v1`) se convierte en una
`Intervention` (xp_multiplier, lock_in/out, chips) más un mapa `p_play` que
sobrescribe la disponibilidad del modelo ANTES de proyectar. Dos mecanismos:

* `p_play` (absoluto, 0..1): reemplaza `disponibilidad`; sirve para subir a un
  dudoso confirmado (0.5 -> 0.95) y para vetar (0 -> xP 0), sin dividir por la
  disponibilidad del modelo, así que es seguro en p=0. Subir por encima del
  valor del modelo exige `confidence: "high"` explícito.
* `xp_multiplier`: factor sobre el xP ya proyectado (se aplica con
  `contract.apply`, que escala candidatos y horizonte).

Los deltas se reportan por jugador (xP proyectado antes/después) y, aparte, el
re-score de la MISMA decisión; nunca como diferencia de dos soluciones MILP.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from mova_fpl.agent.contract import MULT_MAX, MULT_MIN, Intervention

DOC_SCHEMA = "mova-research-adjustments-v1"
#: tope de jugadores tocados (p_play/xp_multiplier/lock_*) en una sola corrida
MAX_ADJUSTED = 8
TOP_FIELDS = {"schema", "gw", "source", "rationale", "adjustments", "lock_out",
              "lock_in", "block_chips", "allow_chips"}
ADJ_FIELDS = {"element", "p_play", "xp_multiplier", "reason", "confidence"}
CONFIDENCE = {"low", "medium", "high"}
#: nombres de la API FPL y abreviaturas -> nombres del motor (frontera del mapper)
CHIP_ALIASES = {
    "wildcard": "wildcard", "freehit": "free_hit", "free_hit": "free_hit",
    "bboost": "bench_boost", "bench_boost": "bench_boost",
    "3xc": "triple_captain", "triple_captain": "triple_captain",
}


def normalize_chip(name) -> str:
    key = str(name).strip().lower()
    if key not in CHIP_ALIASES:
        raise ValueError(f"chip desconocido: {name!r}")
    return CHIP_ALIASES[key]


@dataclass(frozen=True, slots=True)
class Research:
    intervention: Intervention
    p_play: dict = field(default_factory=dict)       # element -> 0..1
    confidence: dict = field(default_factory=dict)   # element -> low|medium|high
    reasons: dict = field(default_factory=dict)      # element -> texto

    def is_empty(self) -> bool:
        return self.intervention.is_empty() and not self.p_play

    def adjusted_elements(self) -> set:
        iv = self.intervention
        return (set(self.p_play) | set(iv.xp_multiplier) | set(iv.lock_in)
                | set(iv.lock_out))


def _ids(values, label: str) -> frozenset:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{label} debe ser una lista de elementos")
    return frozenset(int(v) for v in values)


def parse(doc: dict, *, gw: int) -> Research:
    """Documento -> `Research`. Estricto: error explícito ante cualquier duda."""
    if not isinstance(doc, dict):
        raise ValueError("el documento de research debe ser un objeto JSON")
    if doc.get("schema") not in (None, DOC_SCHEMA):
        raise ValueError(f"schema de research incompatible: {doc.get('schema')!r}")
    extra = set(doc) - TOP_FIELDS
    if extra:
        raise ValueError(f"claves no permitidas en research: {sorted(extra)}")
    if int(doc.get("gw", gw)) != int(gw):
        raise ValueError(f"research es de la GW{doc.get('gw')}; se pidió la GW{gw}")
    source = str(doc.get("source") or "").strip()
    rationale = str(doc.get("rationale") or "").strip()

    p_play, conf, reasons, mult = {}, {}, {}, {}
    adjustments = doc.get("adjustments") or []
    if not isinstance(adjustments, list):
        raise ValueError("adjustments debe ser una lista")
    for item in adjustments:
        if not isinstance(item, dict) or set(item) - ADJ_FIELDS:
            raise ValueError(f"ajuste inválido o con claves no permitidas: {item!r}")
        element = int(item["element"])
        if element in p_play or element in mult:
            raise ValueError(f"elemento {element} ajustado dos veces")
        if "p_play" not in item and "xp_multiplier" not in item:
            raise ValueError(f"ajuste de {element} sin p_play ni xp_multiplier")
        if item.get("p_play") is not None:
            p = float(item["p_play"])
            if not math.isfinite(p) or not 0.0 <= p <= 1.0:
                raise ValueError(f"p_play {p} del elemento {element} fuera de [0, 1]")
            p_play[element] = p
        if item.get("xp_multiplier") is not None:
            m = float(item["xp_multiplier"])
            if not math.isfinite(m) or not MULT_MIN <= m <= MULT_MAX:
                raise ValueError(f"xp_multiplier {m} del elemento {element} fuera de "
                                 f"[{MULT_MIN}, {MULT_MAX}]")
            mult[element] = m
        level = item.get("confidence")
        if level is not None:
            if level not in CONFIDENCE:
                raise ValueError(f"confidence inválida: {level!r}")
            conf[element] = level
        if item.get("reason"):
            reasons[element] = str(item["reason"])[:300]

    lock_out = _ids(doc.get("lock_out") or [], "lock_out")
    lock_in = _ids(doc.get("lock_in") or [], "lock_in")
    block = frozenset(normalize_chip(c) for c in doc.get("block_chips") or [])
    allow = frozenset(normalize_chip(c) for c in doc.get("allow_chips") or [])

    iv = Intervention(gw=int(gw), author=source, rationale=rationale, xp_multiplier=mult,
                      allow_chips=allow, block_chips=block, lock_in=lock_in,
                      lock_out=lock_out)
    research = Research(iv, p_play, conf, reasons)
    if research.is_empty():
        return research
    if not source:
        raise ValueError("research no vacío exige `source` (autor/fuente)")
    if not rationale:
        raise ValueError("research no vacío exige `rationale`")
    touched = research.adjusted_elements()
    if len(touched) > MAX_ADJUSTED:
        raise ValueError(f"research toca {len(touched)} jugadores; el tope es {MAX_ADJUSTED}")
    return research


def apply_availability(research: Research, elements, model_availability):
    """Disponibilidad con los `p_play` aplicados. Devuelve (array nuevo, avisos).

    `elements` y `model_availability` están alineados con las filas del roster
    (pueden repetir elemento). Subir por encima del valor del modelo requiere
    `confidence == "high"`. No hay división: p=0 no puede fallar.
    """
    elems = [int(e) for e in elements]
    base = np.asarray(model_availability, dtype=float)
    out = base.copy()
    known = set(elems)
    for element, p in research.p_play.items():
        if element not in known:
            raise ValueError(f"p_play: el elemento {element} no está en el roster")
        rows = [i for i, e in enumerate(elems) if e == element]
        model = float(base[rows[0]])
        if p > model + 1e-9 and research.confidence.get(element) != "high":
            raise ValueError(
                f"p_play {p} sube la disponibilidad del modelo ({model:.2f}) del elemento "
                f"{element}: exige confidence=\"high\"")
        for i in rows:
            out[i] = p
    return out


def adjustment_report(research: Research, *, names: dict, model_availability: dict,
                      xp_raw: dict, xp_final: dict) -> list:
    """Una fila por jugador tocado: cambio de xP proyectado y de p_play.

    `xp_raw` = xP del GW sin research; `xp_final` = con p_play y multiplicador.
    Es un cambio de PROYECCIÓN del jugador, no una ganancia de decisión.
    """
    rows = []
    iv = research.intervention
    for element in sorted(research.adjusted_elements()):
        before, after = float(xp_raw.get(element, 0.0)), float(xp_final.get(element, 0.0))
        rows.append({
            "element": element, "name": names.get(element),
            "p_play_before": model_availability.get(element),
            "p_play_after": research.p_play.get(element, model_availability.get(element)),
            "xp_multiplier": iv.xp_multiplier.get(element),
            "lock": ("out" if element in iv.lock_out else "in" if element in iv.lock_in
                     else None),
            "xp_before": round(before, 3), "xp_after": round(after, 3),
            "delta_xp": round(after - before, 3),
            "confidence": research.confidence.get(element),
            "reason": research.reasons.get(element),
        })
    return rows


def rescore(decision, xp: dict) -> float:
    """xP de la jornada de UNA decisión fija bajo un mapa de xP (sin resolver)."""
    xi = sum(float(xp.get(e, 0.0)) for e in decision.starters)
    if decision.chip == "bench_boost":
        xi += sum(float(xp.get(e, 0.0)) for e in decision.bench_order)
    mult = 3 if decision.chip == "triple_captain" else 2
    return xi + (mult - 1) * float(xp.get(decision.captain, 0.0))
