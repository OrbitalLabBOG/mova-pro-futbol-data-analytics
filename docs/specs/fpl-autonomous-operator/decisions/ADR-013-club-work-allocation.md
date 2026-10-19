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

## Campaña de completitud — candidato 1.18.0

Petición de Julián del 16 de octubre: iterar sobre los pendientes y hacer
observable por qué se detiene. Los slots refresh/final anteriores limitaban las
búsquedas a cinco/cuatro para un foco de once clubes; 1.18 sella hasta dos
consultas por club (máximo 32) y 32 documentos en todos los slots. Conserva
presupuesto de tokens, permisos, plazo y validación independiente.

Dentro de un intento realiza hasta dos pasadas seriales. La segunda sólo recibe
sujetos sin evidencia respaldada por checks independientes del intento actual;
una afirmación del LLM no los elimina de la cola. Cambia de estrategia de noticia
a crónica/alineación reciente cuando falta cobertura. Contexto histórico nunca
se convierte en disponibilidad médica actual. La lectura conserva pistas por
apellido que el verificador existente ya admite, sin cambiar su autoridad.

Cada sesión publica progreso durable ligado a run/attempt: pendientes, en
investigación, revisados sin evidencia, evidencia verificada y fuentes agotadas,
con intentos y último rechazo de verificación por sujeto. Una sesión despachada
no cuenta como revisión terminada. `mova strategy research progress` presenta
ese trabajo separado de los ratios importados y el motivo del próximo despacho.
Presupuesto/plazo/cupo documental y agotamiento de búsquedas son paradas
explícitas; jamás se traducen a no_material_news o éxito de calidad.

La continuación entre jobs mantiene el máximo de dos hijos por slot, con cinco
minutos de cooldown y conservación transaccional de presupuesto futuro. Los
fallos originales y contratos de aceptación anteriores permanecen intactos.
100% revisado no equivale a 90% de cobertura/80% evidencia: ambos gates se
conservan. Estado al preparar el candidato: activo 1.10, pruebas reales y
promoción pendientes; no se aumenta autonomía FPL.

La revisión de identidad detectó además que el nombre legal de Igor Thiago no
coincide con su alias deportivo. 1.18 puede resolver `web_name` del foco sellado
únicamente si su secuencia de tokens pertenece a un único ID del catálogo
completo; usa la misma resolución en tool e importador. Alias ambiguos (p. ej.
Gabriel/Enzo) o ausentes del nombre oficial se rechazan. Los requests anteriores
sin completion_campaign mantienen exactamente su resolución previa.
