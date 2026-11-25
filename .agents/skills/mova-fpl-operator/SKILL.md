---
name: mova-fpl-operator
description: "Operar MOVA FPL en modelo copiloto (ADR-021): leer el catálogo `mova tools`, armar el brief semanal, proponer la decisión a Julián, registrar memoria y cerrar la GW; además salud, datos, modelos, incidentes y rollout del VPS. No usar para escoger jugadores sin el motor ni para hacer clicks en FPL."
metadata:
  vertical: mova
  type: native-adapter
  canonical: .claude/skills/mova-fpl-operator/SKILL.md
  updated: 2026-11-25
---

# Adaptador nativo: MOVA FPL Operator

Lee completamente el workflow canónico en
`../../../.claude/skills/mova-fpl-operator/SKILL.md` y carga únicamente los runbooks que este
indique para la operación solicitada.

Modelo copiloto (ADR-021): empieza por `mova tools --json` y `mova week brief --gw N --json`;
nada se escribe en FPL sin el OK explícito de Julián. La estrategia deportiva pertenece a
`fpl-expert`; la ejecución visual aprobada pertenece a `fpl-web-ops`.
