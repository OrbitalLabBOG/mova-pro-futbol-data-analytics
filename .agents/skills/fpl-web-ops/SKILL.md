---
name: fpl-web-ops
description: "Operar la cuenta real de Fantasy Premier League con agent-browser: crear o reemplazar la plantilla, ordenar titulares y banca, asignar capitán y vice, guardar y producir evidencia pre/post verificable para `mova execute manual-package`. Usar solo para aplicar en la web un plan que Julián aprobó explícitamente en el chat, o para leer estado privado no expuesto por la API pública."
metadata:
  vertical: mova
  type: native-adapter
  canonical: .claude/skills/fpl-web-ops/SKILL.md
  updated: 2026-11-25
---

# Adaptador nativo: FPL Web Ops

Lee completamente el workflow canónico en
`../../../.claude/skills/fpl-web-ops/SKILL.md` y sigue sus referencias según la operación.

Gate (ADR-021): OK explícito de Julián en el chat sobre un plan concreto; la skill devuelve
pre/post state y evidencia para `mova execute manual-package`. No dupliques aquí el procedimiento: `.claude/skills/fpl-web-ops/` es la fuente de verdad.
