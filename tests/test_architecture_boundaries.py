"""WP-001 / AC-WP001-006: las fronteras del paquete se verifican, no se confian.

Grafo permitido (02-architecture.md):
    data   -> (nadie del paquete)
    rules  -> (nadie)              puro: sin datos, sin modelos
    models -> data, rules
    opt    -> rules, models
    engine -> data, rules, models, optimizer, trace
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
    "data": set(),
    "rules": set(),
    "models": {"data", "rules"},
    "optimizer": {"rules", "models"},
    "engine": {"data", "rules", "models", "optimizer", "trace"},
    "trace": set(),
    "cli": {"engine", "data", "rules", "models", "optimizer", "trace"},
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
