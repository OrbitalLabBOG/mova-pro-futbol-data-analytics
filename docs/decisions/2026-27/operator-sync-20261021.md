---
type: verification
name: MOVA FPL — sincronización del operador, research y sesión
created: 2026-10-21
updated: 2026-10-21
status: verified-with-pending-delivery
---

# Corte verificado del 21 de octubre

Revisión operativa observada: `a6966aa6a5a3d5f62e6fdd8021097d37cd172bd3`.
Consulta de salud del 21/10 a las 15:10 Colombia; revisión posterior de sesión a las 15:22.
Esta acta documenta implementación y hechos observados; no despliega código,
no cambia permisos ni acredita la entrega final de GW8.

## Implementación contrastada

| Ruta | Fuente | Comportamiento |
| --- | --- | --- |
| Entrega | `deploy/bin/delivery-cycle.sh`, `mova_fpl/ops/delivery.py` | Timer de 5 min; autoridad y scope; lectura privada fresca; tick/dispatch; wrapper R2 sólo para intento preparado |
| Escritura R2 | `deploy/bin/execute-r2-browser.sh` y driver | Lease, locks antes del claim, begin/commit único, reload y estado financiero/chips; no retry Save ambiguo |
| Readiness | `mova_fpl/ops/readiness.py`, `execution.py` | Separa scope autorizado, prueba física de revisión vigente y recibo final; conserva diagnósticos generales |
| No-op/cierre | `unchanged_delivery.py`, `review.py`, `db.py` | Recibo sellado, hashes y frescura; cierre financiero v2 admite coincidencia verificada sin inventar Save físico |
| Research | `strategy.py`, `research_continuation.py`, `research_campaign.py` | Pendientes acumulados, fuentes independientes, límites atestados, refresh y presupuesto compartido |
| Worker | `deploy/research/codex-worker.mjs`, `research-context.mjs`, `research-evidence-tool.py` | Prompt de continuación en app-server activo; identidad completa sellada; resultado candidato sujeto a importación |
| Sesión | `browser-session.sh`, `collect-private-team-state.sh`, Compose | Perfil montado protegido, Chromium keep-running, collector adaptativo; autenticación humana si el proveedor la requiere |

PR209/210 corrigieron cierre/evaluación y continuidad. PR211 abrió T−72 h y retiró
el máximo artificial de tres corridas/reserva especulativa. La primera prueba
falló por logical token guard: la continuación estaba en legacy mientras app-server
seguía radar global. PR212 corrigió la ruta activa. El rechazo por worker drift
no se eludió: PR213 permite reemplazar sólo una request fallida incompatible,
conservando quarantine, cargo, receipts y padre importado. PR214 añadió identidad
completa y cierre con límites acreditados; PR215 conserva la ambigüedad antigua
hasta una lectura con el lector corregido, aunque otro run legacy omita verificar.

## Resultado vivo y límites

- CI 39535006246 de PR215: 2213 passed, 79 deselected; imagen smoke success.
  Suite local: 2212 passed, 1 skipped, 79 deselected. Doctor postdeploy: 25 PASS / 0 WARN / 0 FAIL.
- Salud a las 15:10: healthy, cero incidentes y outbox pendientes, cola íntegra,
  cuatro fuentes del data service healthy, estado privado fresco y 15 jugadores.
  Backups dentro del RPO de 7 h. No acredita reconstrucción de host vacío.
- A2/autonomous con `delivery_scope=lineup-v1`, writes habilitados, kill switch
  off y compliance approved. Mismos 15, XI/banca/C/VC; cero transfers/hits/chips.
  R3 y aceptación general no se promueven desde este scope.
- `research_6660a1085255ada7fe624fef1be50995`: timer normal sin force ni permiso
  humano adicional; importado, 191303 tokens exactos. Retomó el pendiente Palmer.
  `research_focus_investigated_with_limits` termina correctamente el slot amplio.
- Campaña: 25 procesados, 22 con evidencia, 21 resueltos. Cole Palmer, Bobby Thomas y
  John Egan conservan límites de fuentes; Mamadou Sangaré tiene una duda de
  titularidad con evidencia de una fuente. `complete_with_limits` no es cobertura
  verificada completa ni aceptación longitudinal A3. Refresh T−6 h/T−2 h pendientes.
- Cuota GW8: 4M, comprometidos 2.984.371, restantes 1.015.629, cero reservas huérfanas.
  El intento fallido `research_f40c7d8971db1377294ed2f2469979ef` y su cargo
  conservador de 500k se preservan; no confundir uso observado incompleto con cargo exacto.
- Sesión a las 15:22: Chromium healthy/running, perfil persistente montado con permisos 0700,
  keep-running=1 y restart=unless-stopped. Último GET privado válido a las 14:47 de Colombia.
  Persistencia sobrevive a recrear el contenedor, salvo revocación/expiración
  del proveedor. Contraseña/MFA/CAPTCHA/consentimiento no son desatendidos.
- Retención, alertas/readiness de los cambios del 19/10 permanecen instalados.
  El live-ping Slack del 19/10 y replay sin envío son antecedentes; esta revisión
  no manda mensajes adicionales ni repite pruebas externas.

## Pendiente antes de declarar entrega

`delivery.live_proof=null` y `delivery.final_receipt=null` en el corte observado.
`BOUNDED_LINEUP_SAVE_PROVEN` sigue pendiente aunque autoridad y runtime estén sanos.
No reutilizar una prueba del 17/10 como prueba física de la revisión actual.

Deadline GW8 confirmado en API oficial: 23/10/2026 17:30 UTC, 12:30 Colombia.
Entrega regular 14:30…17:00 UTC, 09:30…12:00 Colombia; hard stop 17:15 UTC.
Refresh research 11:30/15:30 UTC, 06:30/10:30 Colombia, sujetos a cuotas vigentes.
Verificar `saved_verified` o `unchanged_verified` y estado privado persistido.
El segundo no demuestra clic Save. No fabricar cambios deportivos, nuevas ventanas
`delivery_proof`, retries ambiguos ni duplicados. No backfillear cierres GW6/7 sin recibos.

## Evidencia y continuidad

Evidencia privada sanitizada en el host del operador:
`/home/julianzu/code/artifacts/mova-fpl/research-autonomy-20261020/`:
`acceptance.json`, `heartbeat-20261021-final.log`, `manual-20261021-status.log`,
`manual-20261021-cockpit.log`, `auth-execution-status.log`, tests/CI y rollouts.
No contiene cookies ni exportación del perfil. Los JSON operativos no se publican aquí.

Referencias: [ADR014](../../specs/fpl-autonomous-operator/decisions/ADR-014-bounded-lineup-delivery.md),
[ADR015](../../specs/fpl-autonomous-operator/decisions/ADR-015-unchanged-closeout-research-continuation.md),
[ADR016](../../specs/fpl-autonomous-operator/decisions/ADR-016-autonomous-research-campaign.md),
[PR215](https://github.com/OrbitalLabBOG/mova-pro-futbol-data-analytics/pull/215).
El commit documental que publique este corte no sustituye el SHA operativo anterior.
El rollback de código conserva imágenes/revisión previas y nunca restaura el ledger
para borrar fallos. Esta sincronización no requiere recrear contenedores ni reloguear.
