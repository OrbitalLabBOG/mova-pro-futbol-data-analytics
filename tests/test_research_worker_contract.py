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
    assert "ca-certificates" in dockerfile
    assert "COPY mova_fpl" not in dockerfile
    assert "USER 10002:10002" in dockerfile


def test_worker_deshabilita_herramientas_que_podrian_leer_auth_o_actuar():
    worker = (ROOT / "deploy/research/codex-worker.mjs").read_text(encoding="utf-8")
    for feature in ("shell_tool", "computer_use", "browser_use", "apps", "multi_agent"):
        assert f'"{feature}"' in worker
    assert '...(isResearch ? ["--search"] : [])' in worker
    assert "const prompt = isResearch ? researchPrompt : deliberationPrompt" in worker
    assert '"--sandbox", "read-only"' in worker
    assert 'mkdirSync("/tmp/mova-research"' in worker
    assert "Cada señal y cada conflicto" in worker
    assert "únicamente URLs incluidas en documents" in worker
    assert "manifest.research_summary.focus" in worker
    assert "previous_active_signals" in worker
    assert "fetch independiente" in worker
    assert "coverage.subjects" in worker
    assert '"mova-research-brief-v2"' in worker
    assert "duration_ms: Date.now() - startedAtMs" in worker
    assert "search_requests: null" in worker
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
    assert schema["properties"]["schema"]["const"] == "mova-research-brief-v2"
    assert "coverage" in schema["required"]
    assert "evidence_text" in schema["properties"]["documents"]["items"]["required"]
    assert schema["properties"]["usage"]["additionalProperties"] is False

    def assert_typed(node):
        if isinstance(node, dict):
            if "const" in node or "enum" in node:
                assert "type" in node
            for child in node.values():
                assert_typed(child)
        elif isinstance(node, list):
            for child in node:
                assert_typed(child)

    assert_typed(schema)

    deliberation = json.loads(
        (ROOT / "deploy/research/decision-deliberation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert deliberation["additionalProperties"] is False
    assert deliberation["properties"]["strategist"]["additionalProperties"] is False
    assert deliberation["properties"]["critic"]["additionalProperties"] is False
    assert_typed(deliberation)


def test_timer_no_es_un_agente_residente():
    timer = (ROOT / "deploy/systemd/mova-fpl-research.timer").read_text(encoding="utf-8")
    service = (ROOT / "deploy/systemd/mova-fpl-research.service").read_text(encoding="utf-8")
    assert "OnCalendar=*:7/15" in timer
    assert "Type=oneshot" in service
    assert "TimeoutStartSec=10min" in service


def test_timer_no_levanta_codex_sin_request_pendiente():
    cycle = (ROOT / "deploy/bin/research-cycle.sh").read_text(encoding="utf-8")
    assert 'compgen -G "$research_root/inbox/*.request.json"' in cycle
    assert cycle.index("compgen -G") < cycle.index("docker compose")
