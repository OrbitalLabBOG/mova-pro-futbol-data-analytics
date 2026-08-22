---
type: workpack
name: "WP-005 — Lifecycle de decisión, modelos y estrategia"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, workpack, models, optimization]
status: proposed
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
