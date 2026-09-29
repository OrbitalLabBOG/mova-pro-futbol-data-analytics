---
type: operational-verification
created: 2026-09-22
status: verified-with-open-gates
---

# Recuperación de revisión causal y coherencia operativa — 22/09

Iteración autorizada por Julián sobre AC-01/03 y diagnóstico de AC-02. La autoridad
permanece shadow/A0; ninguna escritura FPL ni promoción de modelo, lección o executor.
PR [#177](https://github.com/OrbitalLabBOG/mova-pro-futbol-data-analytics/pull/177),
apilada sobre #176. Julián es owner; no existe gate de aprobación de Nicolás.

## Cambios y evidencia

- `8a9d4d8`: propuestas C2/P2 con categoría normalizada; recuperación de causal
  review fallido/crasheado, acotada y auditada; trazas nuevas respetan comparador,
  autor o unknown, transferencias/hits/chip. Collector efectivo cada 15 minutos
  con lock compartido de capacidad, sin relajar cadencias de fuentes ni TTL.
- `e15cce7`: bloqueos operativos no se atribuyen a defectos del optimizador.
  Sólo checks de legalidad de decisión, hits y comparadores conservan esa
  clasificación accionable.
- `b391745` / `ccf21d3`: API observa configuración de alertas sanitizada publicada
  por watchdog; no recibe secreto de envío. La proyección ausente/vencida falla
  cerrada. [Decisión y contrato](alert-channel-observation-20260922.md).
- `deploy/compose.capacity.yaml` versiona el override existente del host: API
  0,15 CPU, PostgreSQL 0,10, worker 0,25, research 0,15 y browser 0,25; sin aumentar
  límites. El override host se conservó y se comparó byte a byte con el perfil.

La suite final dio **1802 passed, 1 skipped, 79 deselected**. Los deselected
siguen las exclusiones del repositorio; no son pruebas ejecutadas. Se verifican
cooldown y tres intentos máximos, recuperación de running >=10 min sólo bajo lock,
inputs incompatibles, fallos antes/después de persistir, replay sin duplicados,
lock de capacidad, auth expirada con marcador persistente, atribución de traza,
y separación entre observación de alertas y capacidad de envío.

## GW5 y persistencia

El cierre factual supervisado permanece en la [acta GW5](gw05-closeout.md).
Revisión causal `causalreview_cecf3bd08717004e954216e6`; job
`job_19f24d209d9e4ecc8443384baeaacc9c` completado en intento 2 y replay `reused`.
El éxito resolvió el incidente causal. La propuesta incorrecta
`proposal_b9bba5493b35369d7108221d` fue rechazada con evaluación
`evaluation_1862bb4e588c4b13ab819bff95ee1f13`; no se alteró el review sellado.

PostgreSQL shadow importó el nuevo corte con
`pgimport_d6164f7974414ba28046880877cb39df`: 57 contratos pass (56 exactos y uno
agregado), cero fallos; content SHA256
`db412d941c12bcc54cda7c5a011f4842684248a702c758c03d49d1e6923eab54`.
La paridad corresponde al snapshot sellado, no al ledger vivo posterior.
SQLite sigue siendo writer del harness; PostgreSQL sigue writer del data service.

## Release, recuperación y sesión

Se conservó configuración previa en el directorio root-only
`/opt/orbital/backups/mova-fpl/release-20260922-8a9d4d8/`.
Backup SQLite previo a release: `20260922T151831Z`, job
`job_20eb52c7865c4ec6bf8d503cc0edd8ef`. Backup PostgreSQL terminado:
`postgres/20260922T145040Z/manifest.json` bajo el mismo root de backups MOVA.
No hubo migración de schema en esta iteración. El backup local posterior a la
verificación terminó a las 16:00:30 UTC: `20260922T160030Z`, job
`job_55e3633fdaf640a482033f60cff46ce7`, con ops/trace/canonical selladas y sin
borrados por retención. No equivale a un nuevo restore o upload off-host.

Se probó rollback del API de `e15cce7` a la imagen previa `2cd6b7a` contra los
datos actuales, seguido por retorno a `e15cce7`: `/readyz` pasó en ambos.
Esto prueba compatibilidad del API con esos datos; no es rollback total del host
ni una restauración nueva de PostgreSQL. El restore off-host 8/8 del 20/09
conserva su evidencia independiente.

Tras recrear el browser, la captura privada `job_bfd476cc780145868baa56cc358389bf`
terminó el 22/09 a las 15:25:37 UTC, con 15 jugadores válidos y sesión persistente.
La captura tras la recreación final con `ccf21d3` también pasó: job
`job_b083eb60e0354635842a00cc73d163fa`, 15:58:46 UTC, 15 jugadores y fingerprint
idéntico al estado previo. No se promete duración indefinida del login.
Timer collector efectivo `*:0/15`:
el disparo 15:30:42 terminó 15:30:59, exit 0, sin fuentes degradadas; las fuentes
que aún no cumplían su cadencia se omitieron correctamente.

## Observación de estabilidad

La ventana de 30 minutos fue declarada antes de medir, con muestras cada cinco
minutos: ready <=15 s, RAM disponible >=2 GiB, disco >=10 GiB, cero OOM/restarts,
a lo sumo un worker y heartbeat <=15 min, sin nuevos jobs fallidos sin tratar.
El archivo operativo es `stability-30m.json` en el directorio de release.
Resultado: **7/7 muestras pass**, desde 15:25:24 hasta 15:55:24 UTC sobre el
runtime `e15cce7`. Máxima respuesta ready 1,861 s; RAM mínima 4.835.651.584 bytes;
disco mínimo 40.394.100.736 bytes; heartbeat máximo 314 s; máximo un worker;
cero OOM, reinicios o nuevos jobs fallidos. El
[resumen verificable](runtime-review-recovery-20260922.json) conserva el hash del
archivo original. Es una ventana corta; no acredita estabilidad longitudinal.

Después se desplegó `ccf21d3` para corregir observabilidad del canal externo.
**Ese ajuste no hereda automáticamente los 30 minutos medidos sobre e15cce7.**
Su comprobación posterior dio doctor **24 PASS / 0 WARN / 0 FAIL**, API/browser
healthy, checkout e imagen coherentes, workflow sin violations y cola con cero
anomalías. Readiness del API: **22 pass / 4 pending / 1 blocked**, A0 elegible.
Los disparos programados posteriores también terminaron success: tick
16:00:05–16:00:18 UTC y collector 16:00:45–16:01:04 UTC. A las 16:02:11 UTC,
readiness seguía 22/4/1 y la cola sin anomalías.
El watchdog real terminó success a las 15:56:44 UTC y publicó la observación
15:56:43.657 UTC; el API reconoció los dos gates externos sin recibir secretos
ni emitir otro ping. CI sobre `ccf21d3` pasó.

Imágenes finales:

- Engine: `sha256:f65d8ce8d775802a0aad656df1b940bc337343490b8f8cd492b3f2a096079d4e`.
- Browser: `sha256:8c2d3426335861efb55e832b75a1a61427c9447686932c958b0666c265205152`.

Receipts privados: `doctor-ccf21d3.json` y `postdeploy-ccf21d3.json` en el directorio
de release. Se conserva además `deploy.env.e15cce7` para rollback de configuración.
Entre 15:52 y 15:54 hubo rechazo de conexiones SSH nuevas, sin caída del dashboard
(HTTP 200) ni reinicio del host o sshd. UFW tiene `22/tcp LIMIT`; es consistente
con rate limiting, no se atribuye causalidad definitiva sin su log. Se continuó
con multiplexación SSH. No se deshabilitó ni amplió el firewall.

Muestreo auxiliar de host durante la observación: CPU idle 62–81% y steal 11–21%
en cuatro intervalos de un segundo, sin swap-in/out en esos intervalos. Es un VPS
compartido: el steal existe y no se interpreta como CPU propia al 100%. Ningún
servicio ajeno a MOVA fue detenido o reconfigurado.

## Research: resultado y siguiente entrega

El [experimento reproducible](../../../experiments/research/20260922-recovery/README.md)
aplicó dos políticas al mismo resultado original y verificó cinco hashes de
artefactos. Sin llamadas LLM ni fetches nuevos: 12% de cobertura / dos señales
aceptadas con política anterior; 4% / cero señales con frescura vigente.
No cambia el ledger histórico ni constituye un benchmark de modelos.

Prioridad: factibilidad del alcance antes del gasto, evidencia reciente con fecha
verificable y claim preciso, reutilización validada y ensayo pareado con presupuesto
igual. También falta separar paginación y cohorte del gate longitudinal. AC-02
sigue bloqueado por calidad, no simplemente por esperar nuevas GWs.

## Ruta pendiente

1. AC-01: integrar PRs apiladas en la release canónica y observar continuidad
   programada más allá de este corte corto; mantener detección de auth expirada.
2. AC-03: cerrar contrato financiero retrospectivo con origen sellado; no relajar
   validación de plantilla valorizada ni reinterpretar trazas legacy. Recuperación
   supervisada no demuestra cierre automático.
3. AC-02: adquirir evidencia útil dentro de presupuesto y cerrar overrun sólo con
   follow-up equivalente; mantener umbrales y conflictos explícitos.
4. AC-04/05: rehearsals R2/R3 pendientes, diferenciados por capacidad y versión.
5. AC-08/09: jornada integral sin rescates y promoción explícita cuando aplique.

AC-06/07 conservan la evidencia ya aprobada de alertas y backup/restore externo.
La discrepancia API/worker de esta iteración se corrige en observabilidad; no se
borra la evidencia del destino existente ni se simula un nuevo live ping.

## Seguimiento PM

Supabase recibió el corte verificado y la actualización append-only
`7000b620-4d0d-48ec-b191-7c814ba6ff8c`. AC-01 pasó a in_progress; AC-02/03/08
conservan in_progress, con evidencia y siguiente entrega explícitas. Se
preservaron colas, responsables y fechas existentes. No se cerraron gates por
conteo de tests ni se registró un porcentaje ficticio de autonomía.
