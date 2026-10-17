---
type: pm-update-preview
name: MOVA FPL — corte de harness para publicación posterior
created: 2026-10-05
status: draft-not-published
rag: false
owner: julian
---

# Preview PM — no publicado

Proyecto: `cbd36dc4-0c1a-45ad-9134-1019e99639e4`.
Este texto es un borrador local. Antes de publicar, verificar la aceptación final
[acta de release](harness-release-20261004-dcf98b8.md), releer el objeto/acceso
vivos y reconciliar cualquier cambio desde el corte observado del 29/09.
No crea tareas, cambia responsables ni concede acceso.

## Texto propuesto para current_status

MOVA FPL tiene acd84a9 instalado (PR195), suite 2.025 passed / 1 skipped /
79 deselected y CI SUCCESS. La iteración implementó nueve gaps de datos,
observabilidad, recuperación y browser, y verificó el contrato existente de
intentos acotados. Cinco pruebas DR originales del SHA final PASS:
API 5/5 (25 s), PostgreSQL 8/8 (19 s), browser 9/9 (17 s), combinado 13/13
(57 s) y restore externo 8/8 (380 s). Rollback de código/configuración
realmente ejercitado, sin reemplazar bases. Estabilidad final PASS: 1870.49 s, cuatro muestras y un tick
nuevo completado, posterior al último drill disruptivo. Hash SHA256:
`692363eb7e0a1ccbb4a78d3ef1f91fdda4663de5f569a923488f6d91a09a92af`.

La autenticación y el contrato DOM están verificados. Capitanía y lineup
cuentan con 1/3 ciclos del driver R2 .10.2, mediante probe read-only: no hubo
Save. Runtime healthy y doctor 25 PASS / 0 WARN / 0 FAIL; nivel A0/shadow,
kill switch true, browser writes false y compliance pending. Readiness:
21 pass / 5 pending / 1 blocked; research histórico 4 jornadas medidas / 0 passing.

Siguen pendientes la decisión sobre cohorte prospectiva ADR-011, follow-ups
metered equivalentes dentro del límite original, ciclos reales distintos,
ejecución controlada con recarga/post-state, closeout natural y promoción.
Reboot necesita autorización explícita y evidencia nueva; reconstrucción de
host vacío conserva un RTO objetivo sin ensayo válido. No se activó el
Researcher candidato ni se aumentaron allowances o encolaron nuevos jobs LLM.

## Texto propuesto para project_updates

Título: **Harness acd84a9 verificado; autonomía conserva gates pendientes**.

Contenido: usar el current_status anterior y enlazar PR195, el acta final y la
[matriz H01–H13](harness-autonomy-audit-20261004.md#matriz-de-cierre-de-la-iteración--runtime-acd84a9).
Estabilidad verificada entre `2026-10-05T08:04:28.050055+00:00` y
`2026-10-05T08:35:38.538257+00:00` (UTC), con el hash anterior.
El acta conserva estados intermedios sólo como historia fechada.

## Cambio propuesto de R2

Objeto: `e716c251-bdd3-4ee4-957a-e553d300104f`.
Estado propuesto: **in_progress**; el motivo checkbox missing fue superado
con captura privada y probe física del ciclo 2026-27-gw06, importadas como
rehearsal_8af6285e4047cfa8680a7598 (capitanía) y
rehearsal_a4e4ab3959a4ec808cca304d (lineup).

Agregar a la descripción una nota de progreso fechada: contrato DOM
fpl-pick-team-a11y-2026.10.1 y driver fpl-r2-host-driver-2026.10.2; cobertura
1/3 por capacidad. Mantener pendientes otros dos ciclos independientes y
Save/reload/post-state bajo gates y autoridad explícitos. No sustituir la
historia de fallos ni marcar la tarea done.

Epic, research, lifecycle, release longitudinal, jornada completa, R3 y
promoción conservan sus estados abiertos. Responsables, colas, fechas y
porcentajes permanecen tal como estén en Supabase al autorizar la publicación.
