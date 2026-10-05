---
type: adr
name: ADR-011 — aceptación prospectiva de research por contrato
created: 2026-10-04
status: proposed-not-approved
---

# ADR-011 — Cohorte prospectiva para aceptar research

## Contexto comprobado

`OpsDB.research_coverage` agrupa la última corrida importada de cada ciclo de
todo el historial. Sólo pasa si hay al menos tres ciclos medidos y pasan todos.
La corrección de paginación es válida; también hace que un fallo histórico
impida aceptar una versión futura por tres nuevas GWs passing. Actualmente hay
cuatro medidas y cero passing. Los conflictos sin fechas o evidencia originales
no pueden resolverse inventando fuentes ni rehaciendo hoy una GW histórica.

La hoja de ruta AC02.3 habla de tres GWs passing. El operador debe mostrar la
diferencia con el gate implementado hasta que exista una decisión registrada.

## Propuesta para decisión del owner

Separar el historial operacional completo de la aceptación prospectiva de un
contrato de agente. Conservar el primero sin reetiquetar, borrar o reimportar
GWs antiguas. La aceptación sigue exigiendo tres GWs distintas, 90% cobertura,
80% evidencia y cero conflictos aplicables en cada una; no se acepta un promedio.

Antes de la primera inferencia de la cohorte, registrar un contrato inmutable:

- season y GWs objetivo concretas; al menos tres y ninguna medida retrospectivamente;
- versión de agente, prompt/contexto, quality policy, output schema, routing,
  model/effort, Codex, implementación y hashes del manifiesto de aceptación;
- selección de corrida por slot definida antes del resultado, incluyendo intento
  fallido, rechazado, no ejecutado o consumo incierto; no escoger sólo el mejor import;
- ventanas, presupuestos, número máximo de intentos y regla de abandono;
- tratamiento de conflicto actual y de señal histórica potencialmente reutilizada;
- actor, razón, timestamp de aprobación y hash; no se edita un contrato ya iniciado.

La cohorte contiene todas las GWs predeclaradas. Un fallo permanece visible y
bloquea esa aceptación; crear otra cohorte requiere decisión trazable, no una
ventana móvil que vaya descartando fallos. Un cambio material del contrato
invalida la comparabilidad y necesita una nueva preregistración.

El reporte histórico mantiene cuatro medidas/cero passing del corte auditado.
El reporte prospectivo empieza `not_registered`, después `in_progress`, y sólo
pasa con todos los resultados previstos y checks completos. La falta de una
GW no se convierte en cero ni passing. Experimentos y replay quedan excluidos.

Conflictos antiguos permanecen abiertos o clasificados como insuficientes con
sus pruebas originales. Ninguna señal derivada de ellos se activa o reutiliza
sin validación temporal independiente aplicable al nuevo as-of. La cohorte no
declara resuelta una contradicción ni afirma un hecho deportivo nuevo.

## Alternativas

1. Mantener el criterio actual: válido como auditoría completa del historial,
   pero no ofrece una vía de aceptación de una versión corregida sin reparar
   evidencia histórica que puede ser irrecuperable.
2. Tomar las tres últimas GWs passing: rechazada; permite selección posterior
   del éxito y ocultar fallos por desplazamiento de ventana.
3. Rehacer GWs antiguas: rechazada para aceptación viva; evidencia actual no
   puede demostrar disponibilidad/frescura anterior al deadline histórico.

## Requisitos antes de implementación

Decisión explícita del owner sobre esta propuesta, contrato versionado, reportes
histórico/prospectivo separados, conservación de conflictos y fallos, criterios
de selección deterministas, validación de causalidad y regresiones del gate.
Actualizar skill, runbook, PM y `readiness.next_action` para explicar el contrato
aprobado. Este ADR no está aprobado, no registra una cohorte y no cambia código,
presupuesto, permisos, estados de evidencia ni niveles A1/A2/A3.

## Consecuencias

Se obtiene una ruta futura evaluable sin borrar la calidad histórica del
sistema. No se acelera el calendario ni se sustituye la prueba de utilidad
causal o ejecución browser. La promoción conserva compliance y autoridad
explícitos después de los gates aplicables.
