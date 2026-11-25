"""Catálogo estático de tools del modelo copiloto (ADR-021): `mova tools [--json]`.

Cada entrada describe un comando existente que el asistente puede invocar en una
sesión de GW. `argv` es un ejemplo concreto que parsea con el CLI real (lo
verifica `tests/test_tools_catalog.py`); `inputs` documenta los parámetros.
Ningún comando del CLI es `write-fpl`: esa clase solo la tiene la skill externa
`fpl-web-ops`, y solo con OK explícito del owner sobre un plan concreto.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SCHEMA = "mova-tools-v1"
SIDE_EFFECTS = ("read", "write-memory", "write-fpl")
ENTRYPOINTS = ("mova", "python -m mova_fpl.cli.live", "skill")
AUDIT = (
    {"name": "--actor", "required": True},
    {"name": "--reason", "required": True},
    {"name": "--idempotency-key", "required": True},
)


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    argv: tuple[str, ...]
    summary: str
    side_effect: str
    output_schema: str | None
    needs_vps_data: bool = True
    inputs: tuple[dict, ...] = field(default_factory=tuple)
    entrypoint: str = "mova"
    notes: str | None = None

    def to_dict(self) -> dict:
        out = asdict(self)
        out["argv"] = list(self.argv)
        out["inputs"] = [dict(item) for item in self.inputs]
        out["command"] = (["mova", *self.argv] if self.entrypoint == "mova" else
                          ["python", "-m", "mova_fpl.cli.live", *self.argv]
                          if self.entrypoint.startswith("python") else [])
        return out


GW = {"name": "--gw", "type": "int", "required": True}

TOOLS: tuple[Tool, ...] = (
    Tool("tools", ("tools", "--json"), "Este catálogo.", "read", SCHEMA,
         needs_vps_data=False),
    Tool("status", ("status", "--json"), "Estado operativo consolidado.", "read",
         "mova-fpl-operator-v1"),
    Tool("safety", ("safety",), "¿Es seguro esperar? Autoridad y alertas.", "read",
         "mova-safety-summary-v1"),
    Tool("doctor", ("doctor", "--json", "--no-network"), "Diagnóstico verificable.", "read",
         "operator-doctor-v1", inputs=({"name": "--no-network", "type": "flag"},)),
    Tool("cockpit", ("cockpit", "--json"), "Tablero read-only.", "read", "mova-cockpit-v1"),
    Tool("triage", ("triage", "--json"), "Paquete de diagnóstico de incidente.", "read",
         None, inputs=({"name": "--incident-id", "type": "str"},)),
    Tool("data.status", ("data", "status"), "Frescura del data plane.", "read", None),
    Tool("data.coverage", ("data", "coverage"), "Cobertura del data plane.", "read", None),
    Tool("collect", ("collect", "fpl", "--force", "--actor", "julian", "--reason", "brief",
                     "--idempotency-key", "collect:gw12:1"),
         "Fuerza una recolección pública auditada.", "write-memory", None,
         inputs=({"name": "source", "choices": ["all", "fpl", "odds", "schedule", "events"]},
                 *AUDIT)),
    Tool("private_state.capture",
         ("private-state", "capture", "--force", "--actor", "julian",
          "--reason", "captura previa a la GW", "--idempotency-key", "private-state:gw12:1"),
         "Captura on-demand del estado privado (plantilla, banco, FT, chips) en el host.",
         "write-memory", "mova-private-capture-v1",
         inputs=({"name": "--force", "type": "flag", "required": True}, *AUDIT),
         notes="Sin timer (ADR-022). Requiere sesión FPL viva en el browser del VPS; "
               "ejecutar desde el host. Úsese si el brief marca el estado privado como viejo."),
    Tool("private_state.import",
         ("private-state", "import", "--file", "/tmp/team-snapshot.json", "--actor", "julian",
          "--reason", "equipo leído del browser", "--idempotency-key", "private-import:gw12:1"),
         "Importa el equipo real leído por el operador (JSON crudo de la API o simplificado: "
         "picks, bank en décimas, free_transfers, chips) y lo sella como `operator_import`.",
         "write-memory", "mova-private-import-v1",
         inputs=({"name": "--file", "default": "-"}, *AUDIT),
         notes="Devuelve `artifact_path`: pásalo a `week acta --private-state-path` "
               "(no depende de la cadencia). `transfers.limit` null => FT supuestos."),
    Tool("gw.close",
         ("gw", "close", "--gw", "11", "--actor", "julian", "--reason", "cierre GW11",
          "--idempotency-key", "gw-close:gw11"),
         "Cierra una GW finished+data_checked con picks públicos, puntos oficiales y la nota "
         "decision; escribe post_mortem. No exige ejecución verificada (sin settle-auto).",
         "write-memory", "mova-gw-close-v1",
         inputs=(GW, {"name": "--dry-run", "type": "flag"}, *AUDIT),
         notes="Sale con código 2 si la GW no está finished+data_checked o faltan datos."),
    Tool("incidents.close_obsolete",
         ("incidents", "close-obsolete", "--actor", "julian",
          "--reason", "harness retirado ADR-022", "--idempotency-key", "close-obsolete:1"),
         "Cierra incidentes obsoletos (Ejecución FPL ambigua, Backup recovery observation, "
         "Shadow decision falló); Local storage headroom low solo con >=28 GiB libres.",
         "write-memory", "mova-incident-cleanup-v1",
         inputs=({"name": "--dry-run", "type": "flag"}, *AUDIT)),
    Tool("analytics.status", ("analytics", "status"), "Scorecards y proyecciones.", "read",
         "mova-analytics-service-status-v1"),
    Tool("analytics.project", ("analytics", "project"), "Sella proyección pre-deadline.",
         "write-memory", None),
    Tool("analytics.reconcile", ("analytics", "reconcile"),
         "Evalúa GWs con data_checked.", "write-memory", None),
    Tool("model.status", ("model", "status"), "Bundle activo.", "read", None),
    Tool("model.explain", ("model", "explain", "--batch-id", "batch_x", "--element", "1"),
         "Explica la proyección de un jugador.", "read", None,
         inputs=({"name": "--batch-id", "required": True},
                 {"name": "--element", "type": "int", "required": True})),
    Tool("model.predict", ("model", "predict", "--actor", "julian", "--reason", "brief",
                           "--idempotency-key", "predict:gw12:1"),
         "Crea o reutiliza una proyección inmutable.", "write-memory", None, inputs=AUDIT),
    Tool("week.brief", ("week", "brief", "--gw", "12", "--json"),
         "Brief de la GW: ciclo, autoridad, plantilla, flags, acta, razones, memoria y "
         "decisiones abiertas. Nunca falla por datos faltantes.", "read", "mova-week-brief-v1",
         inputs=(GW, {"name": "--json", "type": "flag"}, {"name": "--no-network", "type": "flag"},
                 {"name": "--no-acta", "type": "flag"}, {"name": "--chips", "type": "flag"},
                 {"name": "--horizon", "type": "int", "default": 3},
                 {"name": "--private-state-path"}, {"name": "--interventions"},
                 {"name": "--intervention-from-notes", "type": "flag"}),
         notes="con acta escribe artefactos efímeros bajo artifact_root/copilot o tmp"),
    Tool("acta.dry_run", ("week", "acta", "--gw", "12", "--horizon", "3", "--json"),
         "Acta MILP en dry-run (sin traza) con candidatos y violaciones.", "read",
         "mova-acta-dry-run-v1",
         inputs=(GW, {"name": "--json", "type": "flag"}, {"name": "--chips", "type": "flag"},
                 {"name": "--horizon", "type": "int", "default": 3},
                 {"name": "--private-state-path"}, {"name": "--interventions"},
                 {"name": "--intervention-from-notes", "type": "flag"},
                 {"name": "--require-private-state", "type": "flag"},
                 {"name": "--timeout", "type": "int", "default": 600}),
         notes="Reporta state_source (import|capture|public_reconstruction) y state_age_h. "
               "Research: ajusta p_play/xP antes de proyectar, sin solves extra."),
    Tool("acta.commit", ("--season", "2026-27", "--gw", "12", "--horizon", "3", "--top-k", "0",
                         "--team-id", "3609854"),
         "Acta MILP que persiste la traza committed en trace.db.", "write-memory",
         "mova-live-decision-candidates-v1", entrypoint="python -m mova_fpl.cli.live",
         inputs=(GW, {"name": "--chips", "type": "flag"}, {"name": "--json-out"})),
    Tool("strategy.status", ("strategy", "status"), "Manifiesto y memory_summary.", "read",
         None),
    Tool("strategy.prepare", ("strategy", "prepare"), "Sella el manifiesto del ciclo.",
         "write-memory", None),
    Tool("research.due", ("strategy", "research", "due"), "¿Toca research?", "read", None),
    Tool("research.coverage", ("strategy", "research", "coverage"), "Cobertura de research.",
         "read", None),
    Tool("research.enqueue", ("strategy", "research", "enqueue", "--force", "--actor", "julian",
                              "--reason", "noticias", "--idempotency-key", "research:gw12:1"),
         "Encola research on-demand (el worker corre en el host).", "write-memory", None,
         inputs=AUDIT),
    Tool("research.import", ("strategy", "research", "import"), "Importa resultados listos.",
         "write-memory", None),
    Tool("deliberate.status", ("strategy", "deliberate", "status"),
         "Strategist/Critic del último envelope.", "read", None),
    Tool("deliberate.enqueue", ("strategy", "deliberate", "enqueue"),
         "Encola deliberación sobre el envelope.", "write-memory", None),
    Tool("deliberate.import", ("strategy", "deliberate", "import"),
         "Importa deliberaciones listas.", "write-memory", None),
    Tool("execute.status", ("execute", "status"), "Planes, gates y recibos.", "read",
         "mova-execution-status-v1"),
    Tool("execute.preflight", ("execute", "preflight", "--actor", "julian", "--reason", "gw12",
                               "--idempotency-key", "preflight:gw12:1"),
         "Sella el diff y evalúa autorización sin operar el browser.", "write-memory", None,
         inputs=AUDIT),
    Tool("execute.manual_package",
         ("execute", "manual-package", "--gw", "12", "--approved-by", "julian",
          "--approved-at", "2026-11-26T20:00:00Z", "--operations", "lineup,captaincy",
          "--pre-state", "/var/lib/mova-fpl/artifacts/private-state/pre",
          "--post-state", "/var/lib/mova-fpl/artifacts/private-state/post",
          "--evidence", "/var/lib/mova-fpl/artifacts/manual/gw12-evidence.json",
          "--rationale", "OK de Julián en chat"),
         "Ensambla y valida el paquete manual v2 para record-manual (solo escribe archivos).",
         "read", "mova-fpl-manual-verified-execution-v2",
         inputs=(GW, {"name": "--approved-by", "required": True},
                 {"name": "--approved-at", "required": True},
                 {"name": "--operations", "required": True,
                  "choices": ["lineup", "captaincy", "transfers", "hits", "chip"]},
                 {"name": "--pre-state", "required": True},
                 {"name": "--post-state", "required": True},
                 {"name": "--evidence", "required": True},
                 {"name": "--rationale", "required": True}, {"name": "--out"}),
         notes="exige snapshots privados pre/post: depende de la sesión FPL del VPS"),
    Tool("execute.record_manual", ("execute", "record-manual", "--package", "/tmp/p.json",
                                   "--actor", "julian", "--reason", "gw12",
                                   "--idempotency-key", "manual-verified:gw12:1"),
         "Registra una ejecución humana ya verificada.", "write-memory", None,
         inputs=({"name": "--package", "required": True}, *AUDIT)),
    Tool("review.status", ("review", "status", "--gw", "11"), "Settlement y feedback.",
         "read", None, inputs=(GW,)),
    Tool("review.settle_auto", ("review", "settle-auto", "--gw", "11", "--actor", "julian",
                                "--reason", "cierre", "--idempotency-key", "settle:gw11"),
         "Cierra una GW finished+data_checked.", "write-memory", None, inputs=(GW, *AUDIT)),
    Tool("review.auto", ("review", "auto", "--gw", "11", "--actor", "julian", "--reason",
                         "causas", "--idempotency-key", "review:gw11"),
         "Clasifica causas post-GW.", "write-memory", None, inputs=(GW, *AUDIT)),
    Tool("review.gw", ("review", "gw", "--package", "/tmp/review.json", "--actor", "julian",
                       "--reason", "cierre", "--idempotency-key", "review-gw:gw11"),
         "Cierra una GW con package manual.", "write-memory", None,
         inputs=({"name": "--package", "required": True}, *AUDIT)),
    Tool("improve.status", ("improve", "status", "--gw", "11"), "Lecciones y propuestas.",
         "read", "mova-continuous-improvement-status-v1"),
    Tool("memory.read", ("memory", "read", "--gw", "12", "--json"),
         "Notas + lecciones + deliberación + intervenciones + ejecuciones manuales.", "read",
         "mova-memory-v1", inputs=(GW, {"name": "--json", "type": "flag"})),
    Tool("memory.note.add", ("memory", "note", "add", "--gw", "12", "--kind", "decision",
                             "--text", "XI aprobado", "--source", "owner", "--players-json",
                             '{"captain": 1}', "--actor", "julian", "--reason", "OK en chat",
                             "--idempotency-key", "note:gw12:decision:1", "--json"),
         "Nota append-only (reason, owner_preference, hypothesis, constraint, post_mortem, "
         "decision).", "write-memory", "mova-strategy-note-v1",
         inputs=(GW, {"name": "--kind", "required": True,
                      "choices": ["reason", "owner_preference", "hypothesis", "constraint",
                                  "post_mortem", "decision"]},
                 {"name": "--text", "required": True},
                 {"name": "--source", "choices": ["owner", "assistant"]},
                 {"name": "--players-json", "type": "json|@file"},
                 {"name": "--supersedes"}, *AUDIT, {"name": "--json", "type": "flag"})),
    Tool("memory.note.list", ("memory", "note", "list", "--gw", "12", "--json"), "Lista notas.",
         "read", "mova-strategy-note-v1",
         inputs=({"name": "--gw", "type": "int"}, {"name": "--kind"},
                 {"name": "--json", "type": "flag"})),
    Tool("alerts.status", ("alerts", "status"), "Outbox sanitizado.", "read", None),
    Tool("alerts.acknowledge", ("alerts", "acknowledge", "--incident-id", "inc_x", "--actor",
                                "julian", "--reason", "visto"),
         "Reconoce un incidente.", "write-memory", None),
    Tool("postgres.status", ("postgres", "status"), "Salud del shadow.", "read", None),
    Tool("postgres.verify", ("postgres", "verify"), "Revalida conteos.", "read", None),
    Tool("fpl-web-ops", (), "Aplica en fantasy.premierleague.com un plan ya aprobado por el "
         "owner y produce evidencia pre/post.", "write-fpl", None, entrypoint="skill",
         notes=".claude/skills/fpl-web-ops; solo con OK explícito de Julián"),
)


def catalog(operating_model: str | None = None) -> dict:
    return {
        "schema": SCHEMA,
        "operating_model": operating_model,
        "side_effects": list(SIDE_EFFECTS),
        "flow": ["week.brief", "acta.dry_run", "owner_validation", "fpl-web-ops",
                 "execute.manual_package", "execute.record_manual", "memory.note.add",
                 "review.settle_auto"],
        "gw_cycle": ["private_state.import", "acta.dry_run", "gw.close"],
        "tools": [tool.to_dict() for tool in TOOLS],
    }


def render(payload: dict) -> str:
    lines = [f"MOVA tools · operating_model={payload['operating_model']}", ""]
    width = max(len(tool["name"]) for tool in payload["tools"])
    for tool in payload["tools"]:
        command = " ".join(tool["command"]) or f"skill {tool['name']}"
        lines.append(f"{tool['name']:<{width}}  [{tool['side_effect']:<12}] {command}")
        lines.append(f"{'':<{width}}  {tool['summary']}")
    return "\n".join(lines) + "\n"
