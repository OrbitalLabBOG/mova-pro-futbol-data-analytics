---
type: project
name: "Motor de decision FPL 2026/27 - modelos, reglas y harness de backtest blind — Readiness"
created: 2026-08-07
updated: 2026-08-07
tags: [readiness, quality-gate, fpl-decision-engine, mova]
status: draft
---

# Motor de decisión FPL 2026/27 — Readiness Review

**Fecha de evaluación:** 2026-08-07 · **Versión evaluada:** 1 · **Modalidad:** standard

## Veredicto

**CONCERNS** — Paquete aprobado y en ejecución. Queda **una decisión de producto abierta**
(Q-02) que bloquea exclusivamente a WP-006, y una dependencia menor (Q-01) que sólo muerde
desde GW2. Los riesgos R-01 a R-04 están aceptados por su owner.

Desglose por workpack, porque el veredicto no es uniforme:

| Workpack | Estado | Razón |
| --- | --- | --- |
| WP-001 Almacén y `as_of` | **Listo para ejecutar** | Sin dependencias abiertas |
| WP-002 Motor de reglas | **Listo para ejecutar** | Sin dependencias abiertas |
| WP-003 Walking skeleton | **Listo para ejecutar** | Depende sólo de 001 y 002 |
| WP-004 Modelo de minutos | **Listo para ejecutar** | Depende sólo de 001 y 003 |
| WP-005 Puntos y DefCon | **Listo para ejecutar** | Riesgo R-03 declarado y acotado |
| WP-006 Optimizador | **Bloqueado** | Q-02 sin responder define la función objetivo |
| WP-007 Operación GW1 | **Parcial** | Ejecutable para GW1; desde GW2 requiere Q-01 |

## Evidencia revisada

- `data/mundial.db`: conteos por tabla, cobertura de columnas por temporada, tipos de
  evento Opta y rango de partidos de Premier League.
- `data/raw/fpl/bootstrap_static.json`: deadline de GW1 2026/27, número de jugadores y
  presencia de campos de contribución defensiva.
- `merged_gw.csv` de 2025-26 descargado del repositorio `vaastav`: 29.757 filas,
  841 jugadores, 38 gameweeks, 46 columnas verificadas una por una.
- `src/mova_model/fpl_xp.py` y `src/mova_model/fpl_optimizer.py`: origen del leakage y
  naturaleza real del optimizador.
- `docs/10-backtest-y-critica.md`: precedente metodológico correcto dentro del mismo repo.
- `docs/16..20` y `outputs/`: resultados afirmados, contrastados entre sí.
- Reglas oficiales 2026/27 de la Premier League (BPS y contribución defensiva).
- Estado del arte externo: formulación MILP para alineaciones (arXiv 2505.02170) y
  benchmark libre de contaminación de agentes LLM en el Mundial 2026 (arXiv 2607.17765).

## Checklist

- [x] Intención, alcance y no objetivos son coherentes.
- [x] Requisitos `must` son medibles y trazables.
- [x] Decisiones materiales tienen alternativas y ADR (ADR-001 a ADR-006).
- [x] Contratos críticos están explícitos (`as_of`, `score`, `decide`, `solve`).
- [x] Seguridad, privacidad y trust boundaries están cubiertos para modalidad `standard`.
- [x] Operación, observabilidad y rollback están definidos.
- [x] Workpacks cubren los requisitos y definen evidencia por criterio.
- [x] El validador determinista pasa en modo `ready` (2026-08-07).
- [x] Aprobación de Julián, aprobador único: alcance, arquitectura y riesgo (2026-08-07).


## Hallazgos

| Severidad | Hallazgo | Owner | Resolución/aceptación |
| --- | --- | --- | --- |
| **blocker** | Q-02: sin definir si el objetivo es rank global o mini-liga, la función objetivo de WP-006 queda indeterminada. Default asumido: maximizar puntos esperados | Julián | open — bloquea aprobación de WP-006, no de WP-001..005 |
| **major** | Q-01: falta el `entry_id` del equipo FPL para leer estado real. No afecta GW1 (estado inicial trivial), sí desde GW2 | Julián | open — resolver antes del 21-ago |
| **major** | R-01: el plan estimado suma 80 h en 14 días calendario contra un deadline que no se mueve | Julián | Mitigado por walking skeleton (WP-003) y por el corte declarado del 18-ago: si WP-006 no está, se juega GW1 con la heurística de WP-003. Requiere aceptación explícita |
| **major** | R-02 / C-01: `rules_2026_27` no es validable contra ground truth porque la temporada no ha ocurrido. Sólo `rules_2025_26` tiene golden test | Julián | **aceptado** — el diff automático aísla los cuatro cambios de BPS y quedó verificado contra la fuente oficial |
| **minor** | R-03 / C-02: el componente DefCon se entrena con una sola temporada (29.757 filas), única con la regla vigente | Julián | Aceptar reportando incertidumbre del componente por separado |
| **minor** | R-04 / C-03: el backtest sobre 2025/26 sobreestima el componente bonus porque BPS cambió para 2026/27 | Julián | **aceptado** — se reporta el desglose de bonus por separado |
| **minor** | Q-03: quedan 89 partidos Opta sin recolectar de los 380 de 2025/26 | Julián | No bloquea. Afecta sólo el stretch de recomputar BPS |
| **info** | Los documentos 16 a 20 y los reportes de `outputs/` afirman resultados no reproducibles y mutuamente inconsistentes | Julián | Marcar deprecados con nota que apunte a este paquete. Decisión de borrado, separada |

## Riesgos aceptados y owner

Julián es el **aprobador único** de esta iniciativa: alcance, arquitectura y riesgo. El
2026-08-07 aprobó el paquete y autorizó la implementación, aceptando el corte de
cronograma de R-01 y las mitigaciones de R-02, R-03 y R-04.

El paquete queda en `approved`. **WP-006 continúa bloqueado por Q-02**, que no es un tema
de aprobación sino una decisión de producto sin resolver: la función objetivo del
optimizador cambia según si se persigue rank global o una mini-liga.

## Acciones pendientes

1. **Julián responde Q-02** — única acción que desbloquea WP-006.
2. Julián aporta el `entry_id` del equipo FPL (Q-01), necesario desde GW2.
3. Continuar la ejecución por WP-004.

## Aprobaciones

Julián es el aprobador único de esta iniciativa.

| Área | Responsable | Decisión | Fecha |
| --- | --- | --- | --- |
| Alcance, arquitectura y riesgo | Julián Zuluaga | **approved** | 2026-08-07 |
