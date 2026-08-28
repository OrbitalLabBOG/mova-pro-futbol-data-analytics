---
type: workpack
name: "WP-005 — Lifecycle de decisión, modelos y estrategia"
created: 2026-08-21
updated: 2026-08-28
tags: [mova, fpl, workpack, models, optimization]
status: in_progress
---

# WP-005 — Lifecycle de decisión, modelos y estrategia

## Objetivo

Orquestar `State → Intervention → decide → validate → revision` y separar decisión de
training/promoción.

## Dependencias

WP-002, WP-003; WP-004 opcional en shadow.

## Entregables

- model registry y artifact resolver;
- config/rules/prompt registry y run manifest;
- sensitivity scenarios y diff entre revisiones;
- strategy state de FTs, valor, chips, blancos/dobles y risk lambda;
- settlement y atribución pareada;
- pipeline candidate/shadow/promote/retire.

## Criterios de aceptación

- misma entrada/hash produce mismo fingerprint;
- training no puede ejecutarse dentro de una decisión;
- modelos sin hash/metrics/cutoff no cargan en production;
- hits/chips requieren gates versionados y escenarios robustos;
- toda intervención que cambia decisión tiene contrafactual local;
- replay offline reproduce decisión y acta;
- `minutes/1.1.0` y `points/1.1.0` quedan baseline hasta promoción formal.

## Corte implementado — HV1-06A

- `Decision.to_dict/from_dict` reemplaza la interpretación del acta humana;
- todo ciclo compara `do_nothing`, `milp_baseline` y `primary_alternative`;
- `DecisionEnvelope` liga candidatos, checks y controles al SHA real del `CycleManifest`;
- los hard gates producen `blocked` o `staged` antes de cualquier capa LLM;
- SQLite migration 007 y PostgreSQL migration 008 conservan envelope, candidatos y checks;
- API, status, Prometheus y audit permiten inspección sin abrir artefactos privados.

Pendiente para cerrar WP-005: Strategist/Critic acotados, sensibilidad longitudinal y pipeline
formal de promoción/retire.
