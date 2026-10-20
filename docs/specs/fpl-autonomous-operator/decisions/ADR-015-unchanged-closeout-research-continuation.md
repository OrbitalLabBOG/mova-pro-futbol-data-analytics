---
type: adr
name: ADR-015 — Cierre de no-op y continuación acotada de research
created: 2026-10-20
status: accepted-for-implementation
owner: Julian Zuluaga
---

# Decisión

Julián autorizó corregir cierre/evaluación y retomar investigación pendiente,
probando punta a punta sin romper la entrega GW8. Esta entrega conserva A2,
`lineup-v1`, sus ventanas y todos los límites económicos y de ejecución.
No cambia modelos, fichajes, chips, autoridad ni cohortes de aceptación.

## Entrega sin cambios

Un no-op sólo recibe evidencia `mova-unchanged-delivery-v1` después del preflight
completo y una captura privada exacta de antigüedad máxima 300 segundos.
El recibo liga plan, envelope, candidato seleccionado, estado privado, hashes,
ventana y verificaciones. Se persiste en artifacts y en el job delivery existente;
no se fabrica un execution attempt, un Save ni un rehearsal físico.
El cierre financiero v2 admite este origen, revalida los archivos y el ledger,
y consume exactamente el candidato y estado certificados, aunque do_nothing y
baseline tengan la misma huella. El XI se compara como conjunto y la banca por
orden. Los receipts antiguos sin este contrato y las pruebas delivery_proof no
acreditan un cierre final. Se mantienen settlement oficial y batch causal como
requisitos; no se rellena retrospectivamente evidencia inexistente.

## Investigación con continuación

Researcher 1.14.0 conserva modelo, permisos, herramientas, timeout y cuotas de
1.12.0. Elimina la instrucción contradictoria de atender sólo 2–3 dudas y dejar
sin cubrir el resto. El objetivo de trabajo es todo el foco, sin convertir
falta de evidencia en una conclusión de ausencia de novedades.

Después de un import válido parcial, el timer crea un hijo ligado al hash del
resultado previo, con IDs pendientes y fuentes anteriores como pistas. Conserva
el foco completo y vuelve a verificar independientemente cada documento que
quiera acreditar. Cada run, cargo, error y conflicto anterior se conserva.
La aceptación ADR-011 sigue seleccionando el primer run operativo: continuar
no sustituye un fallo ni registra una nueva cohorte.

Cada slot admite hasta tres runs operativos, sujeto a presupuesto real y reserva
del techo por job para slots futuros. Quedan diez minutos de reserva antes del
corte T−70m. Un fallo terminal no genera continuaciones. Completo, tope de slot,
reserva de presupuesto, deadline o evidencia padre inválida son estados distintos
y observables en research due; sólo el primero acredita completar el foco.
La falta de cobertura sigue bloqueando las acciones que dependan de ella.

Una continuación manual de prueba requiere la excepción auditada `enqueue --force`
con `--run-id` del padre importado, actor, razón y clave. Conserva cutoff,
integridad, presupuesto/reserva y límite de rondas, y no duplica un hijo existente.
No mueve la ventana normal del timer ni concede escrituras en FPL.

## Verificación y rollback

Probar dispatch no-op → recibo durable → package financiero y rechazo de
alteraciones/pruebas; request → import parcial → hijo de pendientes → import
completo, sin borrar el padre; límites y fallos sin nueva inferencia. Conservar
las pruebas host/CLI de guardado A2. Ejecutar suite, Docker smoke, doctor y
verificación viva después del deploy. El rollback es el checkout/imagen previo;
no hay migraciones nuevas ni cambios a los controles de GW8.

## Progreso acumulado independiente

El importador continúa verificando exactamente el foco completo de cada run;
`not_checked` nunca se convierte en una verificación nueva por haber evidencia
anterior. El reporte operativo `mova-research-campaign-v1` reconstruye qué sujetos
ya tienen evidencia independiente aún vigente, identificando corrida/documentos
originales. Verifica hashes físicos, publicación/fetch predeadline, calidad de
origen, identidad y contexto oficial sin cambios. Incertidumbre posterior,
expiración, cambio de club/posición/noticias/status/chance o archivo alterado
vuelven a poner el sujeto en pendientes. Las señales materiales conservan su TTL.
El reporte separa sujetos con fuente verificada de sujetos con dudas resueltas.

Esta lectura acumulada no participa en ADR-011 ni en la promoción A3: la primera
corrida operativa y todos sus fallos permanecen intactos. Tampoco concede writes.
Permite usar las llamadas siguientes para lo pendiente, sin repetir el trabajo
válido ni inflar la calidad de una corrida. Las ventanas de refresh/final siguen
siendo obligatorias y conservan el avance vigente de las anteriores.
