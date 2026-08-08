"""WP-001 / AC-WP001-007: sin credenciales en el paquete (REQ-S-001).

v1 no consume secretos: todas las fuentes son publicas y sin autenticacion.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "mova_fpl"

PATRONES = {
    "api key generica": re.compile(r'(?i)(api[_-]?key|secret|passwd|password|token)\s*=\s*["\'][A-Za-z0-9_\-]{16,}["\']'),
    "bearer": re.compile(r'(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}'),
    "clave OpenAI/OpenRouter": re.compile(r'sk-[A-Za-z0-9_\-]{20,}'),
    "JWT": re.compile(r'eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}'),
    "clave privada": re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    "AWS": re.compile(r'AKIA[0-9A-Z]{16}'),
}


def _archivos():
    return [p for p in PKG.rglob("*") if p.is_file() and "__pycache__" not in p.parts]


@pytest.mark.parametrize("path", _archivos(), ids=lambda p: str(p.relative_to(ROOT)))
def test_sin_patrones_de_secreto(path: Path):
    txt = path.read_text(encoding="utf-8", errors="replace")
    for nombre, patron in PATRONES.items():
        m = patron.search(txt)
        assert m is None, f"{path.relative_to(ROOT)}: posible {nombre} -> {m.group()[:24]}..."


def test_no_se_leen_variables_de_entorno_sensibles():
    for path in PKG.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        txt = path.read_text(encoding="utf-8")
        for var in ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "SERVICE_ROLE"):
            assert var not in txt, f"{path.relative_to(ROOT)} referencia {var}"
