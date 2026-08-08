"""Proyeccion de xp sobre un horizonte de varias jornadas.

Que se puede saber y que no
---------------------------
El calendario esta publicado desde el arranque de la temporada: un manager sabe
en la GW7 que su delantero tiene doble jornada en la GW9 y que su defensa
descansa en la GW10. Eso NO es leakage; es la informacion sobre la que se decide.

Lo que no se sabe es el precio futuro ni la forma futura. Por eso aqui:

- el precio se asume CONSTANTE (no se modela especulacion; es no-objetivo de WP-006);
- el rendimiento futuro es el rendimiento actual por partido, multiplicado por el
  numero de partidos de esa jornada y descontado por un factor de incertidumbre.

Limitacion declarada (L-01): el calendario se lee de los datos ya ingeridos, asi
que incorpora aplazamientos que en su momento no estaban anunciados. El efecto es
pequeno y acotado a jornadas reprogramadas, pero es un adelanto de informacion y
queda registrado como tal en la evidencia del workpack.
"""
from __future__ import annotations

#: cuanto se descuenta cada jornada adicional del horizonte. 0.84 -> la GW+3 pesa 0.59
DEFAULT_DECAY = 0.84


def per_match_rate(xp_gw: float, partidos_ahora: int) -> float:
    """Convierte el xp de la jornada actual en xp POR PARTIDO.

    El proyector entrega una fila por jugador, asi que en doble jornada su xp
    describe un solo partido. Dividir por los partidos reales seria doble
    correccion; lo correcto es tratar ese numero como tasa por partido.
    """
    return float(xp_gw)


def build_xp_matrix(candidates, schedule: dict, gw: int, horizon: int,
                    decay: float = DEFAULT_DECAY) -> dict:
    """Matriz xp[gw][element] para las `horizon` jornadas desde `gw`.

    `schedule` es {(equipo, gw): numero_de_partidos}. Un equipo sin entrada en una
    jornada tiene JORNADA EN BLANCO y aporta cero: no desaparece del problema,
    simplemente no puntua. Dos partidos duplican el xp de esa jornada.

    El descuento por incertidumbre se aplica desde t=1: la jornada que se decide
    hoy no se descuenta.
    """
    if horizon < 1:
        raise ValueError(f"horizonte debe ser >= 1, recibido {horizon}")
    if not 0 < decay <= 1:
        raise ValueError(f"decay debe estar en (0, 1], recibido {decay}")

    out: dict[int, dict[int, float]] = {}
    for t in range(horizon):
        g = gw + t
        peso = decay ** t
        fila: dict[int, float] = {}
        for c in candidates:
            partidos = int(schedule.get((c.team, g), 0))
            fila[c.element] = per_match_rate(c.xp, partidos) * partidos * peso
        out[g] = fila
    return out


def fixture_counts(rows) -> dict:
    """Normaliza filas (equipo, gw, n) al dict que espera `build_xp_matrix`."""
    out: dict = {}
    for r in rows:
        get = (lambda k: r[k]) if isinstance(r, dict) else (lambda k: getattr(r, k))
        out[(str(get("team")), int(get("gw")))] = int(get("n_fixtures"))
    return out


def summarize(xp_matrix: dict) -> dict:
    """Resumen legible del horizonte: total de xp disponible por jornada."""
    return {g: round(sum(v.values()), 1) for g, v in sorted(xp_matrix.items())}
