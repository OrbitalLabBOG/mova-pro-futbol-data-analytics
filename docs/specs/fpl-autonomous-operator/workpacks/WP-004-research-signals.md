---
type: workpack
name: "WP-004 — Investigación y señales de noticias"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, workpack, research, llm]
status: proposed
---

# WP-004 — Investigación y señales de noticias

## Objetivo

Recolectar noticias/ruedas de prensa/alineaciones y convertirlas en claims citados,
expirables y reconciliados con jugadores FPL.

## Dependencias

WP-002 y WP-003.

## Entregables

- registry de fuentes/tier/TTL y adaptadores;
- schema `ResearchSignal` y entity resolution a `element`;
- conflict resolver y policy de evidencia;
- extractor LLM con prompt/version/hash y fixtures gold;
- transformador determinista hacia `Intervention` con límites productivos.

## Criterios de aceptación

- toda señal tiene URL, published/observed, hash, confianza, TTL y claim;
- nombres ambiguos no se resuelven sin club/identidad suficiente;
- rumor único no crea lock/hit/chip;
- ausencia confirmada puede mapearse a disponibilidad cero con rationale;
- contradicciones permanecen visibles;
- el extractor no puede producir `Decision` ni llamar executor.

## Rollout

Solo shadow hasta cumplir la política de promoción de la readiness.
