---
title: Asignación acotada por club y checkpoint de cuota
status: experimental-local
owner: MOVA Fantasy
updated: 2026-10-16
---

# ADR-013: asignación de descubrimiento por club

La investigación GW7 agotó discovery sin recorrer el foco. El candidato 1.13.0
reemplaza la selección libre de dos o tres dudas por primera pasada determinista
por club, con prioridad de plantilla propia. El tool exige el club asignado y
rechaza repeticiones prematuras. El radar global sólo consume presupuesto que
no esté reservado para grupos pendientes y tiene máximo una consulta.

La cuota consumida se guarda antes de abrir red en un checkpoint por request,
compartido entre sus intentos. Un cambio del request o checkpoint inválido
bloquea, nunca reinicia cuota. El checkpoint no prueba evidencia ni aceptación.
El ledger operativo y de presupuesto sigue en ops.db; no se amplían tokens,
usos, deadline, permisos, número de intentos ni autoridad de intervención.

El trabajo entre slots sigue pendiente: requiere una campaña con entradas,
persistencia y criterios propios, manteniendo cada intento original y el fallo
de la primera corrida de ADR-011. Esta etapa no cambia la cadencia productiva.

La extracción distingue contenido recuperable de páginas vacías; no inventa
fechas, ausencia de lesión ni disponibilidad y no ejecuta JavaScript de páginas.
La versión activa queda en 1.10.0. Antes de despliegue/piloto hay que verificar
hashes de worker, presupuesto vivo y resultados; el cambio de assets invalida
la herencia de cualquier contrato de aceptación anterior.
