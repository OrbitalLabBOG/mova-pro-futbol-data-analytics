"""WP-001 / AC-WP001-006: las fronteras del paquete se verifican, no se confian.

Grafo permitido (02-architecture.md):
    data   -> rules                vocabulario del dominio, nada mas
    rules  -> (nadie)              puro: sin datos, sin modelos
    models -> data, rules
    opt    -> rules, models
    agent  -> rules                 solo el contrato: no decide, no optimiza
    engine -> data, rules, models, optimizer, trace, agent
    cli    -> engine
Y ningun modulo puede importar del legacy src/mova_data | src/mova_model.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "mova_fpl"

ALLOWED = {
    # `data` puede usar el VOCABULARIO del dominio (Position, Squad, ChipUse) para
    # devolver los mismos objetos que devuelve el almacen. Se amplio al leer el
    # estado real del equipo desde la API: `data/live.py` tiene que construir una
    # `Squad`, y duplicar el tipo para no cruzar la frontera seria peor.
    # No debilita nada: `rules` es una hoja pura sin dependencias —lo garantiza su
    # propia prueba— asi que no puede aparecer un ciclo.
    "data": {"rules"},
    "rules": set(),
    "models": {"data", "rules"},
    "optimizer": {"rules", "models"},
    # `agent` es deliberadamente el subpaquete mas pobre del grafo. No importa
    # `engine` ni `optimizer`: `measure()` recibe la funcion de decision como
    # parametro. Un agente que pudiera llamar al optimizador por su cuenta podria
    # saltarselo, y ahi se acaba la garantia de que solo mueve entradas.
    "agent": {"rules"},
    "engine": {"data", "rules", "models", "optimizer", "trace", "agent"},
    "trace": set(),
    "cli": {"engine", "data", "rules", "models", "optimizer", "trace", "agent"},
}
LEGACY = ("mova_data", "mova_model", "src.mova_data", "src.mova_model")


def _modules():
    return [p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append(node.module)
    return out


def _subpackage(path: Path) -> str | None:
    rel = path.relative_to(PKG).parts
    return rel[0] if len(rel) > 1 else None


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(ROOT)))
def test_sin_importaciones_al_legacy(path: Path):
    for imp in _imports(path):
        assert not imp.startswith(LEGACY), (
            f"{path.relative_to(ROOT)} importa legacy '{imp}'. ADR-001 lo prohibe."
        )


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(ROOT)))
def test_grafo_de_dependencias(path: Path):
    sub = _subpackage(path)
    if sub is None:
        return
    permitido = ALLOWED.get(sub)
    assert permitido is not None, f"subpaquete no declarado en la arquitectura: {sub}"
    for imp in _imports(path):
        if not imp.startswith("mova_fpl."):
            continue
        target = imp.split(".")[1]
        if target == sub:
            continue
        assert target in permitido, (
            f"{path.relative_to(ROOT)}: '{sub}' no puede importar de '{target}'. "
            f"Permitido: {sorted(permitido) or 'nada'}"
        )


def test_rules_es_puro_cuando_exista():
    """rules/ no puede tocar datos ni librerias de datos (se activa con WP-002)."""
    rules_dir = PKG / "rules"
    if not rules_dir.exists():
        pytest.skip("rules/ llega en WP-002")
    prohibidas = {"pandas", "sqlite3", "numpy"}
    for path in rules_dir.rglob("*.py"):
        for imp in _imports(path):
            raiz = imp.split(".")[0]
            assert raiz not in prohibidas, f"{path.name} importa '{imp}': rules debe ser puro"


#: Modulos autorizados a leer el oraculo. Son ENTORNO y MEDICION, nunca decision:
#: el simulador puntua lo ya decidido y la CLI de evaluacion contrasta un modelo
#: contra lo que paso. Ninguno alimenta a `decide()`. La lista es corta a
#: proposito y cada entrada tiene que justificarse aqui antes de anadirse.
ORACULO_PERMITIDO = {"simulator.py", "eval_points.py"}


def test_el_oraculo_no_se_filtra_a_quien_decide():
    """`Store.results()` es el oraculo del entorno: no puede llegar al agente.

    Cualquier modulo fuera de la lista que lo invoque estaria leyendo el futuro
    por una puerta lateral.
    """
    permitidos = ORACULO_PERMITIDO
    for path in _modules():
        if path.name in permitidos or path.name == "store.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "results", (
                    f"{path.relative_to(ROOT)} llama .results(): solo el simulador puede"
                )


def test_ningun_modulo_de_decision_esta_en_la_lista_del_oraculo():
    """La lista de excepciones no puede crecer hacia el lado que decide.

    Si manana alguien mete `policies.py` o un modulo de `models/` en
    ORACULO_PERMITIDO, el backtest deja de ser ciego y esta prueba lo dice.
    """
    prohibidos = {"policies.py", "runner.py", "greedy.py", "naive.py", "projection.py",
                  "milp.py", "horizon.py", "heuristics.py", "points.py", "minutes.py",
                  "defcon.py", "goals.py", "cleansheet.py", "bonus.py"}
    assert not (ORACULO_PERMITIDO & prohibidos), (
        f"modulos de decision con acceso al oraculo: {sorted(ORACULO_PERMITIDO & prohibidos)}")


def test_roster_no_expone_columnas_de_resultado():
    """El catalogo pre-deadline no puede incluir rendimiento (leakage disfrazado)."""
    from mova_fpl.data.schema import FORBIDDEN_AS_FEATURE
    from mova_fpl.data.store import Store
    assert not (set(Store.ROSTER_COLS) & FORBIDDEN_AS_FEATURE)
