---
type: evidence
name: "HV1-05C — recuperación Researcher v2 y deliberación GW3"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, research, agents, evidence, shadow]
status: deployed-shadow
---

# HV1-05C — recuperación Researcher v2 y deliberación GW3

## Resultado

Se recuperó el servicio Researcher v2 frente a dos fallos observados en producción y se validó
el ciclo Researcher → DecisionEnvelope → Strategist/Critic. Todo ocurrió en `shadow/A0`, con
`kill_switch=true`, `browser_writes=false`, compliance pendiente y cero cambios al equipo FPL.

El worker ahora:

- canoniza URLs HTTPS y elimina documentos duplicados;
- conserva sólo referencias respaldadas por documentos del mismo brief;
- descarta señales/conflictos huérfanos y degrada cobertura sin evidencia;
- reconstruye los 25 sujetos en el orden exacto del foco sellado;
- toma `generated_at` de su reloj de finalización, no del modelo;
- publica un reporte de normalización con conteos, sin URLs ni contenido.

No se modificaron outputs en cuarentena. Cada replay creó una solicitud nueva, auditada e
idempotente. El importador mantuvo todos sus gates de SSRF, cutoff, fetch, locator, identidad y
hash.

## Evidencia viva

| Evidencia | Resultado |
| --- | --- |
| prueba contra rechazo real | 23 documentos emitidos; 2 duplicados y 1 referencia huérfana removidos |
| corrida aceptada | `research_d7350894755bf88acebe3f579f217841` |
| documentos | 12; 11 con fetch/locator verificado |
| señales | 13; 10 aceptadas y 3 candidatas |
| conflictos | 0 |
| cobertura | 18/25 revisados = 72% |
| evidencia por sujeto | 15/25 = 60% |
| envelope posterior | `envelope_11b70a6415878d71da5e5db1`, bloqueado |
| deliberación | `deliberation_1bd330b37593b84e5284f3b269904265` |
| resultado crítico | `block`, 5 riesgos, intervención no aplicada |
| suite hermética | 1015 passed, 1 skipped, 79 deselected |
| pruebas focales | 21 passed |
| commits feature | `97ade3c`, `7d4e2e8` |
| revisión productiva funcional | `0cea0617` antes del corte documental final |
| backup post-validación | `/opt/orbital/backups/mova-fpl/20260830T223739Z` |

La deliberación prefirió `primary_alternative` sobre una wildcard temprana, pero Critic bloqueó
cualquier promoción porque GW2 no estaba liquidada y la fase no permitía acciones irreversibles.
También bloqueó explícitamente todos los chips. El preflight confirmó siete gates cerrados y no
inició el browser.

## Lectura correcta

Esta evidencia prueba que los dos roles agénticos pueden operar end-to-end y fallar cerrados. No
prueba todavía la calibración necesaria para promoción: Researcher v2 tiene una sola GW medida y
la corrida fue parcial frente a los umbrales 90% cobertura, 80% evidencia y tres GWs. Readiness
permanece A0 con 8 gates en pass, 6 pending y 0 blocked.

## Pendiente

- reunir tres GWs v2 independientes y mejorar cobertura sin rebajar el policy;
- liquidar GW2 y regenerar el ciclo antes de evaluar cualquier acción de GW3;
- completar rehearsals R2/R3 y backup off-host/ciclos PostgreSQL;
- resolver la promoción sólo mediante readiness y aprobación explícita.
