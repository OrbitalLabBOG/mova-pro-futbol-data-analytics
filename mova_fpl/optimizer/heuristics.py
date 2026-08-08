"""Recorte del mercado antes de resolver, con criterio declarado (AC-WP006-006).

El legacy filtraba a los veinte mejores por posicion sin decirlo. Eso rompe la
garantia de optimalidad en silencio: si la mejor plantilla necesita un suplente
barato que no esta entre los veinte mejores por xp, el solver jamas lo ve y
devuelve un optimo que no lo es, con cara de optimo global.

Aqui el recorte existe (sin el, resolver 38 jornadas es inviable) pero:

1. su criterio esta escrito;
2. incluye SIEMPRE a la plantilla actual, porque el modelo debe poder no vender;
3. incluye SIEMPRE a los mas baratos de cada posicion, que son el relleno de
   banquillo del que depende la factibilidad presupuestal;
4. devuelve un informe con cuanto recorto, para poder medir el efecto.
"""
from __future__ import annotations

from dataclasses import dataclass

#: mejores por posicion segun xp acumulado en el horizonte
DEFAULT_TOP_K = 30
#: mas baratos por posicion que se conservan como relleno de banquillo
DEFAULT_CHEAPEST = 6


@dataclass(frozen=True, slots=True)
class ShortlistReport:
    total: int
    kept: int
    por_posicion: dict
    forzados: int          # miembros de la plantilla actual rescatados del recorte

    @property
    def ratio(self) -> float:
        return self.kept / self.total if self.total else 1.0

    def __str__(self) -> str:
        det = ", ".join(f"{p}:{n}" for p, n in sorted(self.por_posicion.items()))
        return (f"shortlist {self.kept}/{self.total} ({100 * self.ratio:.0f}%) "
                f"[{det}] forzados={self.forzados}")


def shortlist(candidates, xp_matrix: dict, keep_ids=(), top_k: int = DEFAULT_TOP_K,
              cheapest: int = DEFAULT_CHEAPEST) -> tuple[list, ShortlistReport]:
    """Devuelve (candidatos recortados, informe).

    `top_k <= 0` desactiva el recorte por xp y deja pasar el mercado entero: es el
    modo con el que se mide cuanto cuesta el recorte en optimalidad.
    """
    forzados = set(keep_ids)
    acumulado = {c.element: sum(fila.get(c.element, 0.0) for fila in xp_matrix.values())
                 for c in candidates}

    por_pos: dict = {}
    for c in candidates:
        por_pos.setdefault(c.position, []).append(c)

    elegidos: dict = {}
    detalle: dict = {}
    for pos, grupo in por_pos.items():
        if top_k <= 0:
            sel = list(grupo)
        else:
            mejores = sorted(grupo, key=lambda c: (-acumulado[c.element], c.element))[:top_k]
            baratos = sorted(grupo, key=lambda c: (c.price, c.element))[:cheapest]
            sel = list({c.element: c for c in mejores + baratos}.values())
        for c in sel:
            elegidos[c.element] = c
        detalle[pos.value if hasattr(pos, "value") else str(pos)] = len(sel)

    rescatados = 0
    for c in candidates:
        if c.element in forzados and c.element not in elegidos:
            elegidos[c.element] = c
            rescatados += 1

    salida = sorted(elegidos.values(), key=lambda c: c.element)
    return salida, ShortlistReport(total=len(candidates), kept=len(salida),
                                   por_posicion=detalle, forzados=rescatados)
