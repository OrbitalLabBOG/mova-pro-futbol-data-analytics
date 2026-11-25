"""Catálogo de tools del modelo copiloto (ADR-021): anti-drift contra el CLI real."""

from __future__ import annotations

import json

import pytest

from mova_fpl.cli.live import build_parser as live_parser
from mova_fpl.ops.cli import main, parser
from mova_fpl.ops.tools import ENTRYPOINTS, SCHEMA, SIDE_EFFECTS, TOOLS, catalog


@pytest.mark.parametrize("tool", [tool for tool in TOOLS if tool.entrypoint != "skill"],
                         ids=lambda tool: tool.name)
def test_cada_argv_parsea_con_el_cli_real(tool):
    target = parser() if tool.entrypoint == "mova" else live_parser()
    target.parse_args(list(tool.argv))


def test_catalogo_es_estatico_unico_y_tipado():
    names = [tool.name for tool in TOOLS]
    assert len(names) == len(set(names))
    for tool in TOOLS:
        assert tool.side_effect in SIDE_EFFECTS
        assert tool.entrypoint in ENTRYPOINTS
        assert tool.summary.strip()
    write_fpl = [tool for tool in TOOLS if tool.side_effect == "write-fpl"]
    assert [tool.name for tool in write_fpl] == ["fpl-web-ops"]
    assert all(tool.entrypoint == "skill" for tool in write_fpl)
    required = {"status", "safety", "doctor", "cockpit", "week.brief", "acta.dry_run",
                "acta.commit", "execute.manual_package", "execute.record_manual",
                "memory.read", "memory.note.add", "review.settle_auto", "improve.status"}
    assert required <= set(names)


def test_ninguna_tool_recomienda_la_cadena_de_delivery_legacy():
    for tool in TOOLS:
        if tool.argv[:1] == ("execute",):
            assert tool.argv[1] not in {"dispatch", "prepare", "claim", "begin", "finalize",
                                        "ui-plan", "fail"}


def test_mova_tools_json(capsys, monkeypatch):
    monkeypatch.delenv("MOVA_ENABLE_SCHEDULED_DELIVERY", raising=False)
    assert main(["tools", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == SCHEMA == catalog()["schema"]
    assert payload["operating_model"] == "copilot"
    assert {"name", "argv", "summary", "inputs", "side_effect", "needs_vps_data",
            "output_schema", "command"} <= set(payload["tools"][0])
    assert main(["tools"]) == 0
    assert "week.brief" in capsys.readouterr().out


def test_tools_que_emiten_json_aceptan_json_flag():
    """Consistencia: toda tool `mova` con contrato JSON del flujo semanal acepta --json."""
    cli = parser()
    for name in ("week.brief", "acta.dry_run", "memory.read", "memory.note.add",
                 "memory.note.list", "status", "doctor", "cockpit", "tools"):
        tool = next(tool for tool in TOOLS if tool.name == name)
        assert "--json" in tool.argv, name
        assert cli.parse_args(list(tool.argv)).as_json is True, name
