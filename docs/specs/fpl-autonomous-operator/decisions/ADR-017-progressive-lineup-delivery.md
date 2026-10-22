---
type: adr
name: ADR-017 — Entrega semanal progresiva de alineación
created: 2026-10-22
status: accepted-for-implementation
owner: Julian Zuluaga
---

# Decisión y autorización

El 22 de octubre Julián pidió implementar y operar hasta dejar la alineación
preliminar semanal verificada, con revisiones autónomas posteriores. Esta decisión
extiende la cadencia de ADR-014, conservando A2, `lineup-v1`, los quince actuales,
XI/banca/C/VC, cero transferencias/hits/chips y el baseline oficial sin aplicar
intervenciones LLM no aceptadas. No crea una ventana `delivery_proof` ni habilita A3.

La activación es opt-in mediante el control auditado
`delivery_policy="progressive-lineup-v1"`. Sin él permanece el dispatcher anterior.
Una publicación Git o un test no acredita activación ni guardado real.

# Recorrido

El timer existente evalúa cada cinco minutos. La política abre T−72h y cierra
T−30m. Dentro de ella, un primer ciclo puede operar inmediatamente; las revisiones
posteriores se admiten cada hora hasta T−6h, cada quince minutos hasta T−3h y cada
cinco minutos durante la ventana final. El cambio de provisional a final no espera
el cooldown anterior. Cada ciclo admitido captura el estado privado, fuerza un
solve nuevo con clave idempotente, ejecuta preflight y usa el mismo driver R2.
Todos los gates de datos, settlement previo, modelos, legalidad, cuenta/GW,
finanzas/chips, incidentes y autoridad se conservan. Estado privado <=300 s al
preflight/claim; nunca se amplían TTLs de fuentes ni cuotas de inferencia.

La fase sellada es `delivery_stage=provisional` antes de T−3h y `final` desde
T−3h hasta T−30m. El dispatcher permite revisiones incluso después de una entrega
final verificada, hasta el cierre de la ventana. El hard stop global T−15m se conserva.
El tick no cancela nuevos solves por una ejecución previa mientras la política está
activa. Cada revisión usa un nuevo envelope/plan inmutable y su estado previo exacto.

Los guardados provisionales no marcan la GW ni la decisión como ejecutadas para
settlement. Un no-op provisional conserva evidencia autenticada pero nunca cuenta
como recibo final, Save físico ni fuente de evaluación. Las consultas de recibo,
watchdog, readiness y closeout filtran explícitamente esa fase. La confirmación final
más reciente prevalece sobre una ejecución física anterior al atribuir el cierre.

# Seguridad e idempotencia

No se repite una escritura del mismo plan. Un timer paralelo no puede reservar otro
intento activo o ambiguo de la misma GW: el ledger lo comprueba transaccionalmente.
Una ambigüedad prevalece sobre verificaciones anteriores y detiene la siguiente
revisión; no se intenta otro Save para conciliarla. El claim comprueba que la política,
fase, envelope vigente y estado privado siguen coincidiendo. Una propuesta nueva o
revocación invalida el plan anterior antes de aplicar.

Cuando la cuenta ya coincide, el dispatcher sella un `unchanged_verified` nuevo
por plan y fase, sin clic Save. Se registra la hora observada para aplicar la cadencia
sin convertir un receipt antiguo en uno fresco. No se fuerzan cambios deportivos
para fabricar una prueba física.

# Evidencia, aceptación y recuperación

`execute status.delivery` publica política, última verificación (fase, hora, resultado),
prueba física de la revisión y recibo final por separado. Readiness/cockpit muestran
la ventana semanal y esos resultados. La ausencia de recibo final conserva las
alertas T−2h/P1 y T−30m/P0; una preparación provisional no las satisface.

Pruebas: guardado temprano, segunda revisión, replay sin escritura, transición a
confirmación final, final no-op después de Save, provisional no elegible para cierre,
ambigüedad posterior a Save previo, propuesta supersedida, revocación de política,
ventanas cerradas y scripts host/CLI/lease/verifier con browser fixture. Mantener
además la suite de economía, chips, causalidad y fronteras de arquitectura.

Aceptación viva: imagen/checkout coincidentes, doctor, timer y controles efectivos;
recibo provisional `saved_verified` o `unchanged_verified` con estado privado fresco
persistido. Sólo el primero acredita Save físico. La entrega final GW8 sigue siendo
un compromiso separado hasta comprobar el recibo final y el estado correspondiente.

Recuperación: pausar nuevas escrituras mediante kill switch/control auditado y detener
el timer si hace falta, manteniendo alineación, ledger y evidencias. No restaurar DB,
borrar intentos ni volver a un lector que confunda provisional con final. Si hay
ambigüedad, conciliar por el procedimiento existente antes de cualquier nueva escritura.
