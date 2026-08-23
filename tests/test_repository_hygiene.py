"""Contratos para que el árbol operativo no vuelva a absorber el archivo histórico."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import mova_fpl
import pytest

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_ROOTS = {
    "divulgacion",
    "ig",
    "notebooks",
    "outputs",
    "scripts",
    "src",
    "viz",
}


def test_no_hay_superficies_legacy_en_main():
    assert not {name for name in FORBIDDEN_ROOTS if (ROOT / name).exists()}


def test_fuentes_de_verdad_existen():
    required = (
        "AGENTS.md",
        "pyproject.toml",
        "compose.yaml",
        "docs/README.md",
        "docs/operations/gameweek.md",
        "docs/operations/vps.md",
        "docs/specs/fpl-autonomous-operator/10-autonomous-harness-v1.md",
    )
    assert not [path for path in required if not (ROOT / path).is_file()]


def test_version_del_paquete_y_metadata_coinciden():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == mova_fpl.__version__


def test_git_no_versiona_archivos_pesados():
    if not (ROOT / ".git").is_dir():
        pytest.skip("el artefacto instalado no incluye metadata Git")
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    oversized = []
    for raw in tracked:
        if not raw:
            continue
        path = ROOT / raw.decode()
        if path.is_file() and path.stat().st_size > 1_000_000:
            oversized.append(str(path.relative_to(ROOT)))
    assert not oversized, f"artefactos >1 MB deben vivir fuera de Git: {oversized}"
