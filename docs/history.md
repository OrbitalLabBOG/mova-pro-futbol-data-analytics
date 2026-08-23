---
type: project
name: "MOVA FPL — Repository History"
created: 2026-08-23
updated: 2026-08-23
status: archived-reference
tags: [mova, fpl, history, archive]
---

# Historia del repositorio

El 23 de agosto de 2026 `main` se convirtió en un repositorio exclusivamente operativo para
Fantasy Premier League. El árbol completo anterior quedó sellado en el tag inmutable
[`archive/pre-harness-cleanup-2026-08-23`](https://github.com/OrbitalLabBOG/mova-pro-futbol-data-analytics/tree/archive/pre-harness-cleanup-2026-08-23).

El tag conserva:

- el capítulo Mundial 2026 y apuestas cuantitativas;
- `src/mova_data`, `src/mova_model` y scripts del motor FPL anterior;
- visualizaciones, piezas de divulgación y outputs binarios;
- documentación histórica 00–20;
- el laboratorio inicial de agente.

Esos archivos se retiraron de `main` porque no participan en el build, runtime ni tests del
producto vigente. El motor FPL anterior tiene leakage estructural: agrega información sin
cutoff temporal y usa atributos observados después de la decisión. No es una biblioteca de
la cual rescatar código; cualquier idea debe reimplementarse causalmente.

El backtest inicial del agente dejó dos conclusiones que sí permanecen vigentes:

1. comparar totales de temporada después de perturbar la trayectoria es estadísticamente
   inestable; la evaluación correcta es pareada y en sombra;
2. una sola temporada no tiene potencia para detectar mejoras pequeñas, por lo que el
   feedback de producción debe acumular evidencia sin auto-promover reglas.

No se reescribió la historia Git durante la temporada. El árbol de trabajo y el contexto del
agente quedan limpios, mientras que clones completos aún contienen los blobs históricos. Una
separación física o `filter-repo` puede evaluarse fuera de temporada.

## Deuda deliberada conservada

El optimizador permanece en PuLP 3.3 y el paquete está fijado a `<4`. PuLP 4 cambia la API
de creación de variables y el solver CBC; la migración debe hacerse con un backtest pareado,
no mezclarse con este reset estructural. Los dos warnings conocidos se filtran en pytest para
que cualquier advertencia nueva vuelva a ser visible.
