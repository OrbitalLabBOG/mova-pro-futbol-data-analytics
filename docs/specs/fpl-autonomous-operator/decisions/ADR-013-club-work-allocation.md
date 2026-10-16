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

El candidato 1.14.0 añade continuidad acotada: máximo dos continuaciones por
slot amplio/refresh, separadas 45 minutos, sin continuación del slot final.
Cada hijo conserva su propio request, reserva, resultado y vínculo auditado al
padre. La creación transaccional impide duplicados y preserva presupuesto de
peor caso para los slots futuros, incluyendo reservas en vuelo. Presupuesto
incompleto o huérfano bloquea. Los sujetos previamente verificados sólo ordenan
el siguiente foco: toda evidencia debe volver a validarse; no se hereda cobertura.
Se conserva el fallo original de ADR-011. Esta política sigue inactiva y local.

La extracción distingue contenido recuperable de páginas vacías; no inventa
fechas, ausencia de lesión ni disponibilidad y no ejecuta JavaScript de páginas.
La versión activa queda en 1.10.0. Antes de despliegue/piloto hay que verificar
hashes de worker, presupuesto vivo y resultados; el cambio de assets invalida
la herencia de cualquier contrato de aceptación anterior.

## Sesiones seriales por club — candidato 1.16.0

Los pilotos 1.14 y 1.15 agotaron el guard de tokens antes de componer un brief;
1.15 intentó los once clubes, por lo que discovery completo no resolvía el
crecimiento de conversación. 1.16 abre una sesión efímera por club, en serie,
dentro de la misma request, permiso e intento. Unifica los briefs sin otro LLM
y los entrega al normalizador e importador independientes habituales. No hay
reintentos ocultos ni cambio de autoridad. La cuota compartida y ligada al
request incluye ahora lecturas, verificaciones y consultas de contexto, además
de discovery. Reiniciar el servidor MCP no reinicia esas cuotas.

Suma el consumo exacto de sesiones completadas y limita cada sesión al saldo de
la corrida. Un fallo de sesión falla el intento, sin fingir consumo cero ni
salvarlo como aceptación. Si no se despacha otro club por saldo o tiempo, los
sujetos restantes quedan not_checked y se declara el límite; no se ocultan los
intentos anteriores. La salida de otro club se rechaza. Cada contexto enviado
conserva su propio recibo/hash, y el recibo agregado declara que el contexto
completo no fue enviado. El candidato permanece inactivo hasta su evaluación.
