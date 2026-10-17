---
type: adr
name: ADR-014 — Entrega autónoma acotada de alineación
created: 2026-10-17
status: accepted-for-implementation
owner: Julian Zuluaga
---

# Decisión de implementación

El 17 de octubre Julián pidió implementar el plan y empezar por conectar el
scheduler con el guardado, con pruebas punta a punta. La primera entrega es
`lineup-v1`: conservar los quince jugadores, cero transferencias, cero hits,
cero chips, y optimizar XI, orden de banca y C/VC con el motor existente.
La transferencia gratuita del plan general queda pendiente de su propio
ejecutor y verificación económica; A3 no se habilita con esta entrega.

Un dispatcher host independiente evalúa el scope cada cinco minutos. Sólo
entra en T−3h…T−30m, captura estado privado, fuerza un solve nuevo, sella
preflight y prepara un intento. El wrapper R2 reclama el lease bajo locks,
relee estado y autoridad, guarda una vez, recarga y verifica picks, orden,
C/VC y que banco/coste/contador/chips no hayan cambiado. Ambigüedad o una
ejecución ya verificada bloquean nuevos intentos en esa GW. No se instala
Docker socket en el engine ni se sustituye el guardado visual por HTTP POST.

Research y deliberación siguen disponibles, medidos y sin aceptación nueva.
El baseline acotado no aplica sus intervenciones. Un conflicto LLM conserva
su diagnóstico, pero no invalida automáticamente el baseline de datos
oficiales. Scope del engine, decisión legal, inputs causales, estado privado
fresco y coincidente, deadline, incidentes y autoridad siguen bloqueando.

Readiness conserva las métricas históricas de research, rehearsals y DR.
Para A2 bajo `lineup-v1`, los contadores de tres GWs de lectura y aceptación
LLM se sustituyen por prueba de guardado R2 real de la misma revisión con
verificación posterior. Esta prueba no aprueba research ni A3. La evidencia
de recuperación host sigue visible y no se reetiqueta como válida para otra
revisión; salud real, incidentes y backup continúan observados por doctor.

La entrega exige `saved_verified` o `unchanged_verified`; faltar cualquiera
en T−2h escala P1, en T−30m P0. `skipped_policy` ya no cubre ese compromiso
cuando el scope está configurado. La ausencia de LLM no genera por sí sola
una falla del baseline.

## Autoridad pendiente de activación

La prueba viva inicial usa aprobación auditada `delivery_proof`, ligada a una
GW y con `approved_at`/`expires_at` de máximo una hora. Sólo la invocación
explícita `delivery-cycle.sh --proof` puede usarla. Puede guardar una alineación
provisional antes de settlement/ventana final, conservando esos checks como
warnings, nunca como aprobados; exige modelos sellados, los quince jugadores
originales, estado privado recién capturado, cero transfers/hits/chips y los
mismos controles de autoridad. El lease termina al expirar la aprobación.
Su Save verificado acredita el driver, pero no cierra la GW ni satisface el
receipt final. El timer regular espera mientras esté activa y después conserva
su decisión de T−3h. Una prueba ambigua detiene también la entrega posterior.

La autorización de implementar no fabrica un guardado real ni registra
aceptación contractual. Antes de activar deben existir release comprobada,
controles auditados del owner (`delivery_scope=lineup-v1`, `A2`, modo
autónomo, browser writes y kill switch), y `compliance_gate=approved`.
El estado inicial de todos ellos permanece cerrado. El gate contractual se
conserva separado porque los [términos oficiales de FPL](https://fantasy.premierleague.com/help/terms)
restringen el acceso automatizado; la decisión del owner no implica permiso
concedido por Premier League. No se automatizan contraseñas, MFA ni evasión
de bloqueos de acceso.

## Aceptación y rollback

Pruebas de dispatcher/CLI/host con browser fixture; revocación de scope,
datos inválidos, ventana cerrada, duplicados, cambio de economía/chips y
save ambiguo. Después: imagen/revisión coincidentes, doctor y prueba viva
acotada. Hasta que exista esa prueba, el estado es implementación probada,
no autonomía demostrada.

Para detener futuras acciones, activar kill switch o retirar delivery_scope
y detener el timer. Conservar intentos, receipts y evidencia. Nunca repetir
Save para resolver una respuesta perdida sin conciliar el estado real.

Recuperación: después de un solve/preflight nuevo, el dispatcher reconcilia el
watchdog antes de preparar el intento. Un fallo demostrado antes de begin no
se borra y sólo puede reintentarse desde un plan fresco; un resultado ambiguo
impide incluso esta ruta. La alerta P1 de recibo ausente se mantiene visible,
pero no bloquea su propia recuperación R0/R2 de `lineup-v1` en la misma GW
cuando ésa es su única causa. P0, otros ciclos, causas mixtas, datos inválidos,
revocación de autoridad y hard stop conservan bloqueo.
