---
type: workpack
name: "WP-003 — Collector vivo, snapshots y reconciliación"
created: 2026-08-21
updated: 2026-08-23
tags: [mova, fpl, workpack, collector, data-quality]
status: completed
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

## Cierre

Completado por HV1-03a en la revisión `f2b68a7`. FPL oficial, odds, calendario y eventos
operan como fuentes independientes con artifacts sellados, calidad, frescura, incidentes,
API, métricas y scheduling autónomo. La degradación real de odds 2026/27 queda visible y no
contamina las demás fuentes.

Evidencia: [14-hv1-03a-data-service-evidence.md](../14-hv1-03a-data-service-evidence.md).

La interfaz uniforme de modelos no pertenece al cierre de este workpack y continúa como
HV1-03b.
