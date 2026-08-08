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


def test_ninguna_url_de_escritura_a_fpl():
    for path in _modules():
        txt = path.read_text(encoding="utf-8")
        for endpoint in ("/api/my-team", "/api/transfers", "/api/entry", "login"):
            assert endpoint not in txt, f"{path.relative_to(ROOT)} referencia {endpoint}"
