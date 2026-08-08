"""WP-002 / AC-WP002-006: rules/ es puro. Sin datos, sin I/O, sin estado."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "mova_fpl" / "rules"
PROHIBIDAS = {"pandas", "numpy", "sqlite3", "requests", "httpx", "urllib", "scipy", "sklearn"}


def _modulos():
    return [p for p in RULES.rglob("*.py") if "__pycache__" not in p.parts]


@pytest.mark.parametrize("path", _modulos(), ids=lambda p: p.name)
def test_sin_librerias_de_datos_ni_red(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        nombres = []
        if isinstance(node, ast.Import):
            nombres = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            nombres = [node.module]
        for n in nombres:
            assert n.split(".")[0] not in PROHIBIDAS, f"{path.name} importa '{n}'"


@pytest.mark.parametrize("path", _modulos(), ids=lambda p: p.name)
def test_sin_acceso_a_ficheros(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open", f"{path.name} abre ficheros"


def test_scoring_es_determinista():
    from mova_fpl.rules import PlayerStats, Position, score
    s = PlayerStats(Position.MID, minutes=90, goals_scored=2, assists=1, bonus=3)
    assert len({score(s, "2025-26").total for _ in range(50)}) == 1


def test_los_tipos_son_inmutables():
    import dataclasses
    from mova_fpl.rules import PlayerStats, Position
    s = PlayerStats(Position.MID, minutes=90)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.minutes = 45
