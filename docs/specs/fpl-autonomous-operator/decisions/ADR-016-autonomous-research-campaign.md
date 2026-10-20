---
type: adr
name: ADR-016 — Investigación autónoma por GW sin validación adicional
created: 2026-10-20
status: accepted-for-implementation
owner: Julian Zuluaga
---

# Decisión

Julián pidió que el researcher complete cada GW sin validaciones adicionales,
simplificando restricciones operativas que lo mantienen detenido. Researcher1.15
abre su campaña desde T−72h y el timer conserva cada15min la continuación de
pendientes. Se elimina el máximo artificial de tres corridas por slot y la reserva
especulativa del techo por job para slots futuros. No se amplían cuotas ni costos:
la cola y autorización física mantienen límites job/GW/mes y usos, locks y cutoff.
La continuación sólo admite trabajo si queda el techo de un job en GW y mes.
Se conserva el margen de diez minutos antes del corteT−70m y los refresh T−6h/T−2h.

El presupuesto pasa a ser compartido: una investigación temprana puede reducir
lo disponible para refresh. Cost report y due muestran el bloqueo real sin pedir
validación humana por cada corrida. No se garantiza cobertura completa si se
agota la cuota, falla autenticación o no existe evidencia verificable.

## Investigación y certeza

Se priorizan sujetos sin evidencia frente a dudas de profundidad. Campaña conserva
`status`, `completed_subjects` y preguntas abiertas: no se declaran resueltas por
alcanzar cobertura. Añade `investigation_status`, `pending_evidence_subjects` y
`open_questions`. Si todos tienen fuentes válidas pero quedan dudas, informa
`complete_with_uncertainty`; el controller termina ese slot y el próximo refresh
revisita las preguntas. Sin evidencia independiente continúa parcial. Ningún
estado concede ejecución, aceptación A3 ni convierte incertidumbre en señal.

Los padres1.13/1.14 permanecen inmutables; su evidencia puede seguir siendo válida
y la política operativa actual puede continuarlos sin editar requests ni cargos.
Se preservan hashes, fuentes/identidad, publicación y TTL, presupuestos y todos
los fallos. ADR-011 y su cohorte no se reescriben. No afecta modelos, FPL Save,
A2 lineup-v1, transferencias, hits o chips.

## Evidencia requerida

Probar encolado normal T−70h sin force/owner, más de tres continuaciones con
presupuesto, bloqueo al faltar un job de cuota, fuentes viejas/alteradas y padres
v1 inmutables. Probar fin con cobertura completa y dudas visibles, y reanudación
de dudas en refresh. Suite completa, imágenes, doctor y timer real en VPS.
Rollback por checkout/imagen previo, sin migraciones ni borrado del ledger.
