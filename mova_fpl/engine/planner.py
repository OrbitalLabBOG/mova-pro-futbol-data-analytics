"""Planificador de chips: decide QUE chips se ponen sobre la mesa cada jornada.

Por que hace falta una pieza aparte
-----------------------------------
El coste de oportunidad de un chip vive FUERA de la ventana del optimizador. Un
triple captain gastado en la GW5 dentro de un horizonte de 3 jornadas no puede
saber que la GW14 era mejor: el modelo simplemente no ve tan lejos. Si se meten
las binarias de chip al MILP sin mas, los quema todos en las primeras jornadas,
porque dentro de su horizonte son ganancia gratis.

De ahi la division de trabajo, que es la misma que se le va a aplicar al agente:

    el planificador AUTORIZA  ·  el optimizador EJECUTA

El planificador mira la temporada; el MILP mira la ventana. Autorizar no es
obligar: el optimizador juega el chip solo si le conviene, y por eso la
intervencion del planificador siempre queda medible por diferencia.

La caducidad cambia el problema
-------------------------------
Desde 2025/26 hay dos juegos de chips y el primero muere en la GW19. Un chip sin
usar al cerrar su ventana no es prudencia: es valor quemado. Por eso el umbral
DECAE hacia cero al acercarse el corte, y en la ultima jornada de la ventana
cualquier valor positivo basta para jugarlo.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from mova_fpl.optimizer.freehit import evaluate as evaluate_free_hit
from mova_fpl.optimizer.milp import CHIPS_MODELADOS, Infeasible, OptimizerConfig, solve

#: valor minimo, en puntos esperados, para gastar un chip cuando NO esta por caducar.
#: Punto de partida razonado, no medido: un chip que rinde menos que esto casi
#: siempre tiene una jornada mejor por delante. El backtest los calibra.
PISOS = {
    "wildcard": 8.0,          # reconstruir la plantilla tiene que arreglar algo gordo
    "free_hit": 8.0,          # solo se justifica en jornada rota
    "bench_boost": 6.0,       # cuatro suplentes decentes rinden esto en doble
    "triple_captain": 5.0,    # un capitan de elite en doble supera esto de sobra
}


@dataclass(frozen=True, slots=True)
class PlannerConfig:
    enabled: bool = False
    #: jornadas de calendario que el planificador puede mirar hacia adelante.
    #: NO es el horizonte del optimizador: es cuanta ESTRUCTURA (dobles, blancos)
    #: se considera anunciada. Seis aproxima el rezago real con que la Premier
    #: confirma reprogramaciones; mirar la temporada entera seria adelantar
    #: informacion que un manager no tenia (limitacion L-01).
    structure_lookahead: int = 6
    #: cuanto mejor tiene que ser una jornada futura para que valga la pena esperar
    margen_espera: float = 1.15
    pisos: dict = field(default_factory=lambda: dict(PISOS))
    #: chips que el planificador puede considerar. Vacio = todos los del catalogo.
    solo: frozenset = frozenset()


@dataclass(frozen=True, slots=True)
class ChipVerdict:
    """Que se autoriza esta jornada y por que. Va integro al acta y a la traza."""
    gw: int
    chip: str | None
    value: float
    threshold: float
    reason: str
    candidates: dict = field(default_factory=dict)   # chip -> valor estimado
    free_hit_plan: object = None                     # FreeHitPlan si aplica

    def as_note(self) -> str:
        if self.chip is None:
            if not self.candidates:
                return "chips: ninguno disponible"
            detalle = " · ".join(f"{c} {v:+.1f}" for c, v in sorted(self.candidates.items()))
            return f"chips: ninguno ({self.reason}) — evaluados: {detalle}"
        return (f"chip {self.chip}: +{self.value:.1f} xp esperados "
                f"(umbral {self.threshold:.1f}) — {self.reason}")


# ------------------------------------------------------------------ estructura

def _fixtures_por_gw(schedule: dict, gw: int) -> tuple[int, int, int]:
    """(equipos con partido, equipos con doble, equipos sin partido) en esa jornada."""
    equipos = {t for (t, g) in schedule}
    if not equipos:
        return 0, 0, 0
    juegan = dobles = 0
    for t in equipos:
        n = int(schedule.get((t, gw), 0))
        if n >= 1:
            juegan += 1
        if n >= 2:
            dobles += 1
    return juegan, dobles, len(equipos) - juegan


def structure_factor(chip: str, gw: int, schedule: dict) -> float:
    """Cuan favorable es el calendario de una jornada para un chip concreto.

    Es un proxy deliberadamente grueso: sirve para COMPARAR jornadas entre si, no
    para estimar puntos. El valor absoluto lo da el solve, no esto.
    """
    equipos = {t for (t, _) in schedule}
    if not equipos:
        return 1.0
    juegan, dobles, blancos = _fixtures_por_gw(schedule, gw)
    n = len(equipos)
    if chip in ("bench_boost", "triple_captain"):
        return 1.0 + dobles / n              # el doble es lo que multiplica
    if chip == "free_hit":
        return 1.0 + 2.0 * blancos / n       # el free hit brilla en jornada rota
    return 1.0                                # el wildcard no depende del calendario


def _mejor_futuro(chip: str, gw: int, schedule: dict, hasta: int) -> float:
    """Mejor factor estructural visible por delante, sin contar la jornada actual."""
    futuros = [structure_factor(chip, g, schedule) for g in range(gw + 1, hasta + 1)]
    return max(futuros) if futuros else 0.0


# -------------------------------------------------------------------- umbral

def threshold(chip: str, gw: int, restantes: int, valor_ahora: float,
              schedule: dict, config: PlannerConfig) -> tuple[float, str]:
    """Cuanto tiene que rendir el chip HOY para que no convenga esperar.

    Devuelve (umbral, motivo). El motivo se escribe en el acta: una decision de
    chip que no se puede explicar no se puede auditar despues.
    """
    if restantes <= 1:
        return 0.0, "ultima jornada de la ventana: o se juega o se pierde"

    piso = float(config.pisos.get(chip, 0.0))
    hasta = gw + max(0, config.structure_lookahead)
    ahora = structure_factor(chip, gw, schedule)
    futuro = _mejor_futuro(chip, gw, schedule, hasta)

    if futuro > ahora * config.margen_espera and ahora > 0:
        # hay una jornada estructuralmente mejor a la vista: subir el liston en
        # proporcion a cuanto mejor es
        exigido = max(piso, valor_ahora * (futuro / ahora))
        return exigido, (f"se ve una jornada mejor en las proximas "
                         f"{config.structure_lookahead} (factor {futuro:.2f} vs {ahora:.2f})")

    # sin nada mejor a la vista, el piso se relaja segun se acerca la caducidad
    urgencia = min(1.0, (restantes - 1) / 8.0)
    exigido = piso * urgencia
    if urgencia >= 1.0:
        return exigido, (f"no se ve nada mejor en las proximas {config.structure_lookahead} "
                         f"y quedan {restantes} jornadas de ventana: se aplica el piso "
                         f"habitual de {piso:.1f}")
    return exigido, (f"la ventana se cierra en {restantes} jornadas: el piso baja "
                     f"de {piso:.1f} a {exigido:.1f} para no desperdiciar el chip")


# ------------------------------------------------------------------ valoracion

def chip_value(state, xp_matrix: dict, chip: str, ocfg: OptimizerConfig,
               base_obj: float) -> tuple[float, object]:
    """Puntos esperados que anade un chip en la jornada que se decide.

    Se mide igual que se medira la intervencion del agente: resolviendo dos veces
    y restando. Nada de formulas cerradas.
    """
    gw = state.gw
    if chip == "free_hit":
        plan = evaluate_free_hit(state, xp_matrix[gw], ocfg)
        return plan.value, plan
    if chip not in CHIPS_MODELADOS:
        return 0.0, None
    permiso = replace(state, chips_allowed={gw: frozenset({chip})})
    sol = solve(permiso, xp_matrix, replace(ocfg, tie_break=0.0, chip_epsilon=0.0))
    return round(sol.objective - base_obj, 4), None


def plan(state, xp_matrix: dict, ocfg: OptimizerConfig,
         config: PlannerConfig | None = None) -> ChipVerdict:
    """Decide que chip se autoriza en `state.gw`, si alguno."""
    config = config or PlannerConfig()
    gw = state.gw
    if not config.enabled or state.chips is None:
        return ChipVerdict(gw=gw, chip=None, value=0.0, threshold=0.0,
                           reason="planificador desactivado")

    disponibles = set(state.chips_available(gw))
    if config.solo:
        disponibles &= set(config.solo)
    if not disponibles:
        return ChipVerdict(gw=gw, chip=None, value=0.0, threshold=0.0,
                           reason="sin chips disponibles en esta ventana")

    ventana = state.chips.window_for(gw)
    restantes = ventana.remaining(gw) if ventana else 0
    schedule = getattr(state, "schedule", None) or {}

    limpio = replace(state, chips_allowed={})
    base = solve(limpio, xp_matrix, replace(ocfg, tie_break=0.0, chip_epsilon=0.0))

    valores: dict = {}
    planes: dict = {}
    for c in sorted(disponibles):
        try:
            v, extra = chip_value(state, xp_matrix, c, ocfg, base.objective)
        except Infeasible:
            continue                       # ese chip no da solucion valida aqui
        valores[c] = round(v, 2)
        if extra is not None:
            planes[c] = extra

    if not valores:
        return ChipVerdict(gw=gw, chip=None, value=0.0, threshold=0.0,
                           reason="ningun chip produjo solucion valida", candidates={})

    mejor, motivo_final, umbral_final = None, "", 0.0
    for c, v in sorted(valores.items(), key=lambda kv: -kv[1]):
        u, motivo = threshold(c, gw, restantes, v, schedule, config)
        if v > u and v > 0:
            mejor, umbral_final, motivo_final = c, u, motivo
            break
        if mejor is None:                  # guarda el motivo del mejor candidato
            umbral_final, motivo_final = u, motivo

    if mejor is None:
        return ChipVerdict(gw=gw, chip=None, value=0.0, threshold=umbral_final,
                           reason=motivo_final or "ningun chip supera su umbral",
                           candidates=valores)

    return ChipVerdict(gw=gw, chip=mejor, value=valores[mejor], threshold=umbral_final,
                       reason=motivo_final, candidates=valores,
                       free_hit_plan=planes.get(mejor))
