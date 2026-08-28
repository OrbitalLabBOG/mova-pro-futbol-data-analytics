"""Frontera estática del worker Codex: capacidad mínima y cero autoridad FPL."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_imagen_codex_esta_versionada_y_no_contiene_app():
    dockerfile = (ROOT / "deploy/docker/research.Dockerfile").read_text(encoding="utf-8")
    assert "node:22-bookworm-slim@sha256:" in dockerfile
    assert "@openai/codex@${CODEX_VERSION}" in dockerfile
    assert "ARG CODEX_VERSION=0.144.6" in dockerfile
    assert "COPY mova_fpl" not in dockerfile
    assert "USER 10002:10002" in dockerfile


def test_worker_deshabilita_herramientas_que_podrian_leer_auth_o_actuar():
    worker = (ROOT / "deploy/research/codex-worker.mjs").read_text(encoding="utf-8")
    for feature in ("shell_tool", "computer_use", "browser_use", "apps", "multi_agent"):
        assert f'"{feature}"' in worker
    assert '"--search", "exec"' in worker
    assert '"--sandbox", "read-only"' in worker
    assert 'mkdirSync("/tmp/mova-research"' in worker
    assert "fantasy.premierleague.com" not in worker


def test_compose_no_monta_db_browser_repo_ni_secretos_en_research():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    section = compose.split("\n  research:\n", 1)[1].split("\nnetworks:\n", 1)[0]
    assert "read_only: true" in section
    assert "cap_drop:" in section and "- ALL" in section
    assert 'group_add:' in section and '- "10001"' in section
    assert section.count("/research") >= 1
    assert "/home/research/.codex" in section
    for forbidden in (
        "postgres_password", "odds_api_key", "browser-profile", "/var/lib/mova-fpl/db",
        "runtime.env", "network_mode: host", "/var/run/docker.sock",
    ):
        assert forbidden not in section


def test_schema_de_salida_es_json_valido_y_cerrado():
    schema = json.loads(
        (ROOT / "deploy/research/research-brief.schema.json").read_text(encoding="utf-8")
    )
    assert schema["additionalProperties"] is False
    assert schema["properties"]["documents"]["maxItems"] == 80
    assert schema["properties"]["signals"]["maxItems"] == 120
    assert schema["properties"]["usage"]["additionalProperties"] is False


def test_timer_no_es_un_agente_residente():
    timer = (ROOT / "deploy/systemd/mova-fpl-research.timer").read_text(encoding="utf-8")
    service = (ROOT / "deploy/systemd/mova-fpl-research.service").read_text(encoding="utf-8")
    assert "OnCalendar=*:7/15" in timer
    assert "Type=oneshot" in service
    assert "TimeoutStartSec=10min" in service
