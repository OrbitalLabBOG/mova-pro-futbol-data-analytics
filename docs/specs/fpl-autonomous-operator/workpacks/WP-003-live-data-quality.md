---
type: workpack
name: "WP-003 — Collector vivo, snapshots y reconciliación"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, workpack, collector, data-quality]
status: proposed
---

# WP-003 — Collector vivo, snapshots y reconciliación

## Objetivo

Convertir el collector actual en una etapa observable que selle bytes, detecte drift y
reconcilie estado público/privado sin contaminar el almacén histórico.

## Dependencias

WP-001 y WP-002.

## Entregables

- artifact store y manifest canónico;
- quality contracts de bootstrap, fixtures, entry/history/picks y team state;
- season partition estricta y política de frescura;
- adapter privado para PP/SP/FT/chips o ledger reconciliado;
- quarantine y replay offline.

## Criterios de aceptación

- cambio 599→600 crea snapshots distintos, no overwrite;
- parser drift y conteos anómalos bloquean write y alertan;
- datos stale permiten análisis declarado, nunca ejecución;
- squad fingerprint y presupuesto se comparan entre fuentes;
- servicio `premier-league-api` mezclado no puede entrar como live authority;
- manifest reproduce exactamente el State de una decisión.
