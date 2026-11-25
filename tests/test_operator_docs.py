"""Docs y skills del modelo copiloto (ADR-021) no derivan del catálogo ni recomiendan legacy."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from mova_fpl.ops.tools import TOOLS

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("mova-fpl-operator", "fpl-expert", "fpl-web-ops")
CANONICAL = {name: ROOT / ".claude" / "skills" / name / "SKILL.md" for name in SKILLS}
ADAPTERS = {name: ROOT / ".agents" / "skills" / name / "SKILL.md" for name in SKILLS}
OPERATOR_SKILL = CANONICAL["mova-fpl-operator"]
RUNBOOK = ROOT / "docs" / "operations" / "gameweek.md"
ADR = ROOT / "docs/specs/fpl-autonomous-operator/decisions/ADR-021-copilot-operating-model.md"
HARNESS_SPEC = ROOT / "docs/specs/fpl-autonomous-operator/10-autonomous-harness-v1.md"
VPS = ROOT / "docs" / "operations" / "vps.md"
COPILOT_UPDATED = date(2026, 11, 25)

# Documentos que guían la operación semanal: no pueden recomendar la cadena retirada.
GUIDANCE = (
    *CANONICAL.values(), *ADAPTERS.values(),
    *sorted((ROOT / ".claude/skills/fpl-web-ops/references").glob("*.md")),
    RUNBOOK, ROOT / "AGENTS.md", ROOT / "CLAUDE.md",
)
RETIRED = ("execute dispatch", "execute begin", "execute claim", "execute prepare",
           "mova-fpl-delivery.timer", "mova-fpl-research.timer", "delivery-cycle.sh")
# Una mención solo es aceptable como prohibición o antecedente explícito.
NEGATION = re.compile(r"\b(no|nunca|ni|sin)\b|legacy|retirad|prohib|antecedente",
                      re.IGNORECASE)


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} sin frontmatter YAML"
    block = text[4:text.index("\n---", 4)]
    values: dict[str, str] = {}
    for line in block.splitlines():
        match = re.match(r"^\s*([A-Za-z_]+):\s*(.*)$", line)
        if match:
            values.setdefault(match.group(1), match.group(2).strip().strip('"'))
    return values


def skill_table(path: Path) -> list[tuple[str, str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\| `([^`]+)` \| (.+) \| (read|write-memory|write-fpl) \|$", line)
        if match:
            rows.append((match.group(1), match.group(2).strip(), match.group(3)))
    return rows


@pytest.mark.parametrize("path", GUIDANCE, ids=lambda path: str(path.relative_to(ROOT)))
def test_guias_no_recomiendan_la_cadena_retirada(path):
    offenders = [
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if any(token in line for token in RETIRED) and not NEGATION.search(line)
    ]
    assert not offenders, f"{path.name} recomienda legacy: {offenders}"


@pytest.mark.parametrize("path", [OPERATOR_SKILL, RUNBOOK], ids=["operator-skill", "runbook"])
def test_skill_y_runbook_cubren_el_ciclo_semanal(path):
    text = path.read_text(encoding="utf-8")
    for step in ("mova week brief", "mova week acta", "memory note add", "--kind decision",
                 "execute manual-package", "execute record-manual", "analytics reconcile",
                 "review settle-auto", "post_mortem", "OK explícito de Julián"):
        assert step in text, f"{path.name} no menciona {step!r}"


def test_skills_hablan_del_modelo_copiloto():
    assert "week brief" in CANONICAL["fpl-expert"].read_text(encoding="utf-8")
    web_ops = CANONICAL["fpl-web-ops"].read_text(encoding="utf-8")
    assert "OK explícito de Julián" in web_ops
    assert "manual-package" in web_ops and "record-manual" in web_ops


@pytest.mark.parametrize("path", [*CANONICAL.values(), *ADAPTERS.values(), RUNBOOK, ADR,
                                  ROOT / "AGENTS.md", ROOT / "README.md"],
                         ids=lambda path: str(path.relative_to(ROOT)))
def test_frontmatter_actualizado_al_corte_copiloto(path):
    updated = frontmatter(path).get("updated")
    assert updated, f"{path} sin updated"
    assert date.fromisoformat(updated) >= COPILOT_UPDATED


@pytest.mark.parametrize("name", SKILLS)
def test_adaptadores_apuntan_a_la_canonica(name):
    adapter, canonical = frontmatter(ADAPTERS[name]), frontmatter(CANONICAL[name])
    assert adapter["type"] == "native-adapter"
    assert adapter["name"] == canonical["name"] == name
    assert adapter["canonical"] == f".claude/skills/{name}/SKILL.md"
    assert (ROOT / adapter["canonical"]).is_file()
    assert adapter["description"] == canonical["description"]
    assert f".claude/skills/{name}/SKILL.md" in ADAPTERS[name].read_text(encoding="utf-8")


def test_skill_operador_es_concisa():
    assert len(OPERATOR_SKILL.read_text(encoding="utf-8").splitlines()) < 200


def test_tabla_de_tools_coincide_con_el_catalogo():
    catalog = {tool.name: tool for tool in TOOLS}
    rows = skill_table(OPERATOR_SKILL)
    assert rows, "la skill del operador no tiene tabla de tools"
    for name, command, effect in rows:
        assert name in catalog, f"{name} no está en mova tools"
        tool = catalog[name]
        assert effect == tool.side_effect, name
        if tool.entrypoint == "skill":
            continue
        prefix = []
        for token in tool.argv:
            if token.startswith("-"):
                break
            prefix.append(token)
        expected = " ".join([tool.entrypoint, *prefix])
        assert command.strip("`").startswith(expected), f"{name}: {command} ≠ {expected}"
    names = {name for name, _, _ in rows}
    weekly = {"tools", "status", "week.brief", "acta.dry_run", "memory.read",
              "memory.note.add", "execute.manual_package", "execute.record_manual",
              "analytics.reconcile", "review.settle_auto", "review.gw", "fpl-web-ops"}
    assert weekly <= names, sorted(weekly - names)


def test_adr021_y_spec_autonoma_superseded():
    assert ADR.is_file()
    adr = frontmatter(ADR)
    assert adr["status"] == "accepted"
    spec = HARNESS_SPEC.read_text(encoding="utf-8")
    assert frontmatter(HARNESS_SPEC)["status"] == "superseded"
    assert "Superseded por [ADR-021](decisions/ADR-021-copilot-operating-model.md)" in spec


def test_rollout_vps_exige_ok_de_julian():
    text = VPS.read_text(encoding="utf-8")
    section = text[text.index("## Rollout ADR-021: modelo copiloto"):]
    section = section[:section.index("\n## ", 5)]
    assert "Requiere el OK explícito de Julián" in section
    for step in ("git pull", "install-systemd.sh", "mova control delivery_scope null",
                 "--actor julian --reason", "operating_model=copilot", "mova doctor",
                 "systemctl list-timers"):
        assert step in section, step
