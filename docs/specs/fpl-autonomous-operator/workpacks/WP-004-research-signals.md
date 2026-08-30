---
type: workpack
name: "WP-004 — Investigación y señales de noticias"
created: 2026-08-21
updated: 2026-08-30
tags: [mova, fpl, workpack, research, llm]
status: active-shadow
---

# WP-004 — Investigación y señales de noticias

## Objetivo

Recolectar noticias/ruedas de prensa/alineaciones y convertirlas en claims citados,
expirables y reconciliados con jugadores FPL.

## Dependencias

WP-002 y WP-003.

## Entregables

- registry de fuentes/tier/TTL y adaptadores;
- JSON Schemas `ResearchRequest` v1, `ResearchResult` v1 y `ResearchSignal` v2 más modelos
  Pydantic strict;
- workers one-shot separados para Pydantic AI/OpenRouter y Codex;
- inbox/processing/outbox/quarantine atómicos e importer fail-closed;
- discovery OpenRouter acotado, safe fetch, artifacts/hash y evidence locator;
- entity resolution exacta a `element`;
- conflict resolver y policy de evidencia;
- extractor LLM con prompt/version/hash y fixtures gold;
- budgets por capa, wall timeout, usage/cost-known, redaction y telemetría sin contenido;
- transformador determinista hacia `Intervention` con límites productivos.

## Criterios de aceptación

- toda señal tiene URL, published/observed, hash, confianza, TTL y claim;
- toda señal importable tiene `SourceDocument` recuperado y locator; citation metadata sola
  no cuenta como evidencia;
- nombres ambiguos no se resuelven sin club/identidad suficiente;
- rumor único no crea lock/hit/chip;
- ausencia confirmada puede mapearse a disponibilidad cero con rationale;
- contradicciones permanecen visibles;
- el extractor no puede producir `Decision` ni llamar executor.
- TestModel/FunctionModel no pueden hacer requests reales durante unit tests;
- corpus SSRF/injection y replay de provider pasan;
- raw Codex JSONL, prompts y responses no aparecen en logs/OTel/artifacts generales;
- todo fallback crea attempt y los límites de transport/output/job se observan por separado.

## Rollout

Solo shadow hasta cumplir la política de promoción de la readiness.

## Plan de entrega

`HN-0 contratos → HN-1 queue/importer → HN-2 Pydantic offline/shadow → HN-3 web evidence →
HN-4 Codex specialist → HN-5 shadow completo`.

La implementación exacta está en
[../09-agent-harness-implementation-spec.md](../09-agent-harness-implementation-spec.md).

## Estado verificado

Researcher v2 ya opera one-shot en producción shadow con search, fetch independiente,
locator sellado, cobertura exacta, budget y cuarentena fail-closed. El worker normaliza
únicamente estructura: elimina duplicados y referencias sin documento, degrada cobertura
sin evidencia y fija `generated_at` con su reloj confiable; nunca crea evidencia ni relaja
el importador.

La corrida viva GW3 `research_d7350894755bf88acebe3f579f217841` importó 12 documentos,
11 verificados, 13 señales, 10 aceptadas y cero conflictos. La cobertura fue parcial:
18/25 sujetos y 15/25 con evidencia verificada. El workpack continúa `active-shadow` hasta
cumplir tres GWs v2 con los umbrales de promoción; no se debe presentar esta corrida como
gate aprobado.
