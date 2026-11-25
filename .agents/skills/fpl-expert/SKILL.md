---
name: fpl-expert
description: Analizar el brief y el acta de MOVA FPL para proponer XI, C/VC, transferencias y chips con razones, formular Intervention acotadas y alternativas; o modificar reglas, xP, MILP y planificador de chips del motor. No usar para ejecutar clicks en la cuenta web.
metadata:
  vertical: mova
  type: native-adapter
  canonical: .claude/skills/fpl-expert/SKILL.md
  updated: 2026-11-25
---

# Adaptador nativo: FPL Expert

Lee completamente el workflow canónico en
`../../../.claude/skills/fpl-expert/SKILL.md` y sigue únicamente las referencias necesarias
para la tarea.

Uso principal (ADR-021): leer `mova week brief`/`mova week acta` y construir la propuesta con
razones que Julián valida. La operación visual de una decisión aprobada pertenece a
`fpl-web-ops`, no a esta skill.
