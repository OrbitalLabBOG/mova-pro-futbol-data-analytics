"""WP-001 / AC-WP001-008: v1 es de solo lectura frente a servicios externos (REQ-S-002).

Un bug no puede gastar transferencias ni hits reales porque no existe codigo
capaz de escribir en la API de FPL.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "mova_fpl"

VERBOS_ESCRITURA = ("POST", "PUT", "PATCH", "DELETE")
LLAMADAS_PROHIBIDAS = {
    ("requests", "post"), ("requests", "put"), ("requests", "patch"), ("requests", "delete"),
    ("httpx", "post"), ("httpx", "put"), ("httpx", "patch"), ("httpx", "delete"),
    ("session", "post"), ("session", "put"), ("session", "patch"), ("session", "delete"),
}


def _modules():
    return [p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts]


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(ROOT)))
def test_sin_verbos_de_escritura_declarados(path: Path):
    txt = path.read_text(encoding="utf-8")
    for verbo in VERBOS_ESCRITURA:
        for m in re.finditer(rf'method\s*=\s*["\']{verbo}["\']', txt, re.IGNORECASE):
            pytest.fail(f"{path.relative_to(ROOT)}: declara method={verbo} en pos {m.start()}")


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(ROOT)))
def test_sin_llamadas_http_de_escritura(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            obj = getattr(node.func.value, "id", None)
            if obj and (obj, node.func.attr) in LLAMADAS_PROHIBIDAS:
                pytest.fail(f"{path.relative_to(ROOT)}: llamada {obj}.{node.func.attr}() prohibida")


def test_la_unica_primitiva_de_red_es_get():
    src = (PKG / "data" / "sources.py").read_text(encoding="utf-8")
    assert 'method="GET"' in src
    assert src.count("urlopen") == 1, "solo debe existir un punto de salida a red"


#: superficies de FPL que este paquete NO puede tocar nunca.
#:   my-team   -> requiere autenticacion; devuelve precios de compra y venta
#:   transfers -> POST: es como se gastan transferencias de verdad
#:   login     -> autenticacion
#: `entry` NO esta aqui, y es deliberado: /api/entry/{id}/ y sus sub-rutas son
#: publicas y de lectura —lo que cualquiera ve al abrir el perfil de un equipo—.
#: Se necesitan para leer la plantilla vigente y los chips ya gastados desde la
#: GW2. La garantia de que no se puede escribir NO la da esta lista: la da que
#: exista un solo `urlopen` en el paquete y que declare method="GET".
SUPERFICIES_PROHIBIDAS = ("/api/my-team", "my-team", "/api/transfers", "login")


def _literales_de_codigo(path: Path) -> list[str]:
    """Cadenas que el modulo USA, sin docstrings ni comentarios.

    La distincion importa: una URL solo puede llamarse si aparece como literal en
    el codigo. Un comentario que explica *por que no* tocamos `my-team` es
    documentacion util y prohibirlo empujaria a ofuscar el texto, que es
    exactamente lo contrario de lo que busca esta prueba.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = set()
    for nodo in ast.walk(tree):
        if isinstance(nodo, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            cuerpo = getattr(nodo, "body", [])
            if cuerpo and isinstance(cuerpo[0], ast.Expr) and isinstance(cuerpo[0].value, ast.Constant) \
               and isinstance(cuerpo[0].value.value, str):
                docstrings.add(id(cuerpo[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def test_ninguna_url_de_escritura_a_fpl():
    """Ningun literal del codigo puede componer una ruta de escritura."""
    for path in _modules():
        for cadena in _literales_de_codigo(path):
            for endpoint in SUPERFICIES_PROHIBIDAS:
                assert endpoint not in cadena, (
                    f"{path.relative_to(ROOT)} usa el literal {cadena!r}, que compone "
                    f"la superficie prohibida {endpoint}")


def test_los_endpoints_de_equipo_solo_se_leen():
    """Toda ruta /api/entry/ del paquete pasa por la primitiva GET, sin excepcion.

    Es lo que sustituye a la prohibicion anterior. Antes bastaba con no nombrar
    `entry`; ahora que hace falta leerlo, la garantia tiene que ser mas fuerte:
    cada funcion que lo menciona devuelve `_get(...)` y nada mas.
    """
    src = (PKG / "data" / "sources.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    funciones = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    tocan_entry = [f for f in funciones if "entry" in ast.unparse(f)]
    assert tocan_entry, "se esperaban funciones de lectura de equipo en sources.py"
    for f in tocan_entry:
        cuerpo = [n for n in f.body if not isinstance(n, ast.Expr)]   # sin docstring
        assert len(cuerpo) == 1 and isinstance(cuerpo[0], ast.Return), (
            f"{f.name}() debe ser un unico return; hace mas cosas")
        llamada = cuerpo[0].value
        assert isinstance(llamada, ast.Call) and getattr(llamada.func, "id", None) == "_get", (
            f"{f.name}() no pasa por la primitiva GET")


def test_ningun_modulo_fuera_de_sources_construye_urls_de_fpl():
    """El resto del paquete pide datos por funcion, nunca componiendo una URL."""
    for path in _modules():
        if path.name == "sources.py":
            continue
        for cadena in _literales_de_codigo(path):
            # con esquema: una URL invocable lo lleva. Una etiqueta de procedencia
            # en el acta ("fantasy.premierleague.com/api ... solo GET") no.
            assert not any(f"{esq}://fantasy.premierleague.com" in cadena
                           for esq in ("http", "https")), (
                f"{path.relative_to(ROOT)} compone una URL de FPL por su cuenta: {cadena!r}")
