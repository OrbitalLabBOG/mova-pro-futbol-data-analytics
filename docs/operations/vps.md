---
type: runbook
name: "MOVA FPL — operación del stack VPS"
created: 2026-08-22
updated: 2026-08-27
tags: [mova, fpl, vps, docker, systemd, observability]
status: active
---

# MOVA FPL — operación del stack VPS

## Estado seguro por defecto

El despliegue inicial corre en `shadow`, nivel `A0`, `compliance=pending`, con
`MOVA_ENABLE_BROWSER_WRITES=0` y el `kill_switch=true` en `ops.db`. Los collectors usan GET o
lectura browser pública. Levantar el stack o habilitar timers **no autoriza cambios en el equipo FPL**.

Supabase no participa del runtime: la operación, evidencia, alertas y auditoría viven en el
VPS. Supabase se reserva para seguimiento externo de construcción del proyecto.

## Topología y paths

| Recurso | Path/endpoint |
| --- | --- |
| checkout aprobado | `/opt/orbital/services/mova-fpl` |
| configuración | `/etc/mova-fpl/runtime.env` |
| control plane | `/var/lib/mova-fpl/db/ops.db` |
| PostgreSQL shadow | `/var/lib/mova-fpl/postgres/` (red Docker interna, sin puerto host) |
| datos/modelos/traza | `/var/lib/mova-fpl/db/` y `/var/lib/mova-fpl/artifacts/` |
| data service raw | `/var/lib/mova-fpl/artifacts/data-service/` |
| analytics service | `/var/lib/mova-fpl/artifacts/analytics-service/` |
| contexto estratégico | `/var/lib/mova-fpl/artifacts/strategic-context/` |
| cola de research | `/var/lib/mova-fpl/artifacts/research/` |
| auth Codex dedicada | `/var/lib/mova-fpl/codex-home/auth.json` (fuera de backups) |
| perfil browser | `/var/lib/mova-fpl/browser-profile` (`0700`, sin backup general) |
| backups | `/opt/orbital/backups/mova-fpl/<UTC>/` |
| dashboard | `127.0.0.1:8787` del VPS |
| noVNC | `127.0.0.1:6080` del VPS, solo cuando se activa el perfil browser |

La imagen engine contiene Python 3.13.5, CBC y SQLite 3.53.4. Ninguna herramienta del host
abre las bases: el SQLite 3.45.1 del VPS falla el gate deliberadamente.

## Build e instalación inicial

```bash
cd /opt/orbital/services/mova-fpl
sudo deploy/bin/bootstrap-host.sh
export MOVA_GIT_SHA="$(git rev-parse --short HEAD)"
export MOVA_IMAGE_TAG="$MOVA_GIT_SHA"
sudo sed -i "s/^MOVA_GIT_SHA=.*/MOVA_GIT_SHA=$MOVA_GIT_SHA/; s/^MOVA_IMAGE_TAG=.*/MOVA_IMAGE_TAG=$MOVA_IMAGE_TAG/" /etc/mova-fpl/deploy.env
docker compose --profile research build api worker research
docker compose --profile jobs run --rm --no-deps worker python -m mova_fpl.ops.cli migrate
docker compose up -d --wait postgres
mova postgres migrate
docker compose up -d api
curl --fail http://127.0.0.1:8787/readyz
sudo deploy/bin/install-systemd.sh /opt/orbital/services/mova-fpl
```

Cuando el tag ya está escrito en `/etc/mova-fpl/deploy.env` y se opera Compose manualmente,
cargarlo antes de `build`, `up` o `run`:

```bash
set -a
source /etc/mova-fpl/deploy.env
set +a
docker compose up -d --no-deps --force-recreate api
```

El `env_file` del servicio configura el proceso dentro del contenedor, pero no interpola
`MOVA_IMAGE_TAG` ni `MOVA_GIT_SHA` para el CLI de Compose. Omitir este paso puede levantar la
etiqueta `local/unknown`; `mova doctor` lo detecta como `deployment_revision WARN`.

Antes de activar el primer tick, colocar por canal seguro —no Git—:

- `fpl_canonical.db` en `/var/lib/mova-fpl/db/`;
- `trace.db` en `/var/lib/mova-fpl/db/`;
- modelos `minutes/` y `points/` en `/var/lib/mova-fpl/artifacts/models/`.

## Operación diaria

```bash
# Contrato estable: el wrapper incorpora checks sanitizados del host
mova status
mova status --json
mova readiness
mova readiness --require-level A1  # exit 2 mientras falte evidencia
mova doctor --json
mova data status
mova collect all
mova analytics status
mova analytics run
mova strategy status
mova strategy research due

# Vista HTTP; abrir túnel ssh -L 8787:127.0.0.1:8787 root@72.60.245.2
curl -s http://127.0.0.1:8787/api/v1/status | python -m json.tool
curl -s http://127.0.0.1:8787/api/v1/readiness | python -m json.tool
curl -s http://127.0.0.1:8787/metrics
curl -s http://127.0.0.1:8787/api/v1/data/coverage | python -m json.tool
curl -s http://127.0.0.1:8787/api/v1/analytics | python -m json.tool

# Un tick manual, serializado e idempotente
sudo systemctl start mova-fpl-tick.service
sudo journalctl -u mova-fpl-tick.service -n 100 --no-pager

# Captura adicional auditada después de una migración en la misma hora
mova backup --force --actor codex --reason "captura post-migración" \
  --idempotency-key "backup:post-migration:<git-sha>"

# Refresco excepcional sin esperar la cadencia (auditado e idempotente)
mova tick --force --actor julian --reason "revisión preliminar GW2" \
  --idempotency-key "force:gw2-prelim:2026-08-23"

# Evidencia por correlación
curl -s 'http://127.0.0.1:8787/api/v1/jobs?limit=10' | python -m json.tool
curl -s 'http://127.0.0.1:8787/api/v1/steps?limit=50' | python -m json.tool
curl -s 'http://127.0.0.1:8787/api/v1/audit?limit=50' | python -m json.tool

# Timers y salud
systemctl list-timers --all 'mova-fpl-*'
docker compose ps
docker compose logs --tail=100 api
```

Los logs de containers rotan a 5 × 10 MiB por servicio. Los timers y fallos conservan su
diagnóstico en journald. Cada tick sella bytes fuente y hashes; `ops.db` conserva jobs,
pasos, fuentes, decisiones, controles, salud, incidentes y outbox.

Los pasos `fetch_fpl_bootstrap_events` y `fetch_fpl_fixtures` separan las dos llamadas públicas.
`/metrics` expone la duración total del último tick y la de cada paso de la última corrida que sí
refrescó; esto evita atribuir a la API FPL el tiempo consumido posteriormente por proyección y
optimización.

`mova-fpl-collector.timer` evalúa cada 15 minutos cadencias separadas para FPL, odds,
calendario y eventos. La operación, tablas, calidad y recuperación están en
[servicio autónomo de datos](data-service.md).

`mova-fpl-analytics.timer` corre cada 30 minutos. No vuelve a proyectar si el artifact y las
versiones ya fueron sellados; tampoco evalúa hasta que la API oficial marque `data_checked`.
Cada ejecución queda como job `model_analytics`, con pasos, duración, hashes e incidentes. Ver
[servicio analítico](analytics-service.md).

`mova-fpl-research.timer` evalúa cada 15 minutos, pero la cadencia efectiva es seis horas y
solo dentro de las 30 horas anteriores al deadline. Ejecuta un contenedor one-shot sin DB,
runtime env, navegador ni secretos de collector. La preparación, auth, validación y recuperación
están en [contexto estratégico](strategic-research.md).

La credencial de odds no pertenece a `runtime.env`. Se instala como
`/etc/mova-fpl/odds-api-key`, propietario `root`, grupo del worker `10001`, modo `0640`, y Compose
la monta como secreto únicamente en jobs. La configuración canónica usa
`MOVA_ODDS_API_CREDENTIAL_FILE=/run/secrets/odds_api_key`; nunca imprimir la clave para
diagnosticarla. La salud y el saldo se verifican con `mova data status` o `/metrics`.

`--force` omite únicamente el control de cadencia: no evita el lock, los resource gates,
la validación ni el modo shadow. Exige actor, razón y una clave idempotente explícitos.

`mova status` no llama la red ni escribe el ledger. `mova doctor` hace un GET público acotado y
retorna código 1 ante un `FAIL` requerido. El probe del host no lee env, cookies, logs ni HTML;
ver [contrato del operador](operator.md).

`mova readiness` tampoco muta estado. Consolida salud, settlement, team state, data, analytics,
proyección, manifest, research, incidentes, drivers y PostgreSQL en un contrato máquina. El campo
`technical_eligible_level` no cambia `action_level`, compliance, kill switch, modo ni browser
writes. La promoción siempre es explícita; `--require-level` permite que CI o un agente fallen
cerrados cuando el nivel solicitado todavía no tiene evidencia.

## Estado privado del equipo — API-first

El browser no raspa el DOM para conocer la plantilla. Con la sesión humana persistente hace
un GET autenticado, reduce la respuesta a una allowlist (IDs, posiciones, PP/SP, banco,
valor, FTs y chips) y la pasa por `stdin` al engine. El engine vuelve a validar 15 jugadores,
cuotas, rangos, capitán/vice, claves exactas y `team_id`, sella payload + manifest y registra
`team_state_snapshots`. Cookies, local storage, HTML y perfil nunca salen del contenedor.

```bash
# captura normal: primero aplica el gate adaptativo
sudo deploy/bin/collect-private-team-state.sh

# captura obligatoria pre/post acción; sigue siendo GET y no modifica FPL
sudo deploy/bin/collect-private-team-state.sh --force

# evidencia estructurada
curl -s 'http://127.0.0.1:8787/api/v1/audit?limit=20' | python -m json.tool
sudo journalctl -u mova-fpl-private-state.service -n 100 --no-pager
```

`mova-fpl-private-state.timer` evalúa el gate cada cinco minutos sin encender Chromium si el
snapshot sigue fresco. La captura efectiva ocurre cada 6 horas en operación normal, cada
hora durante las últimas 24 horas, cada 15 minutos durante las últimas 3 horas y cada 5
minutos durante los últimos 30 minutos. Una captura `--force` es obligatoria inmediatamente
antes y después de cualquier acción futura. El motor aplica el mismo límite dinámico de
frescura y el techo absoluto `MOVA_PRIVATE_STATE_MAX_AGE_SECONDS=21600`; si no se cumple usa
el fallback público. El fallo de autenticación queda aislado:
no borra el último snapshot, no habilita writes y no toca el perfil. Para reautenticar,
usar el procedimiento de login humano de la sección siguiente.

En un arranque en frío el wrapper espera explícitamente `DOMContentLoaded` y el origin FPL,
valida schema/15 picks y reintenta hasta tres veces. Una salida vacía nunca llega al ingestor.

## Controles y hard stop

Los controles son append-only y cada modificación genera un evento de auditoría.

```bash
# Pausar decisiones sin perder collector/observabilidad
docker compose --profile jobs run --rm --no-deps worker \
  python -m mova_fpl.ops.cli control kill_switch true \
  --actor julian --reason 'pausa operativa'

# Confirmar estado efectivo
curl -s http://127.0.0.1:8787/api/v1/status | python -m json.tool
```

No cambiar `browser_writes`, `mode`, `action_level` o `compliance_gate` directamente en el
archivo para saltarse el ledger. El runtime rechaza writes salvo `guarded/autonomous`, A1+
y compliance aprobado; el rollout exige además shadow suficiente y prueba de verificación.

## Backup y restore drill

```bash
sudo systemctl start mova-fpl-backup.service
latest="$(find /opt/orbital/backups/mova-fpl -mindepth 1 -maxdepth 1 -type d | sort | tail -1)"
sudo deploy/bin/restore-drill.sh "$latest"

# PostgreSQL shadow: dump custom + restauración en DB temporal
pg_latest="$(find /opt/orbital/backups/mova-fpl/postgres -mindepth 1 -maxdepth 1 -type d | sort | tail -1)"
sudo deploy/bin/postgres-shadow-restore-drill.sh "$pg_latest"
```

El backup usa SQLite Online Backup API y ejecuta `quick_check`; nunca hace `cp` de una base
viva ignorando WAL. PostgreSQL usa `pg_dump -Fc`, valida el catálogo del dump y conserva un
manifest SHA-256. El timer diario ejecuta ambos. Retención local: 35 días.
La copia off-host cifrada sigue siendo una decisión pendiente.

El import y la verificación PostgreSQL se describen en el
[runbook shadow](postgres-shadow.md). SQLite continúa como writer oficial.

## Browser y login humano

La imagen browser está aislada de API/DB, tiene un perfil exclusivo y no se inicia con el
stack normal. Cuando llegue el rollout supervisado:

```bash
sudo deploy/bin/browser-login.sh
# desde el PC del operador
ssh -N -L 6080:127.0.0.1:6080 root@72.60.245.2
```

Abrir `http://127.0.0.1:6080/vnc.html`; Julián completa login y MFA manualmente. No copiar
cookies, OTP, HTML autenticado ni el perfil a logs, Git, `ops.db` o backups. Tras cualquier
cambio de página, el executor debe tomar snapshot nuevo y verificar el estado después de
recargar. Supervisord mantiene un único Chromium normal sobre el perfil persistente y el
executor se adjunta con `--cdp 9222`; CDP no se publica. Esto conserva la sesión tras recrear
el contenedor, salvo expiración o revocación decidida por Google/FPL.

La operación repetible usa `deploy/bin/browser-session.sh`:

```bash
sudo deploy/bin/browser-session.sh status
sudo deploy/bin/browser-session.sh read   # lectura interactiva; no persistir la salida
sudo deploy/bin/browser-session.sh collect # JSON sanitizado por stdout; normalmente usar el wrapper
sudo deploy/bin/browser-session.sh stop
```

La skill canónica `.claude/skills/fpl-web-ops/SKILL.md` define los gates, la secuencia de
snapshots y el procedimiento de ejecución. Mientras los controles estén en `shadow A0`, el
browser sólo se usa para login y lectura; no se permiten clicks que muten la cuenta.

## Rollback y recuperación

1. `systemctl disable --now mova-fpl-tick.timer` para detener nuevos ciclos.
2. Mantener `ops.db`, WAL, artefactos y logs intactos.
3. Reponer el checkout y tag de imagen anterior.
4. `docker compose up -d api` y comprobar `/readyz`.
5. Correr restore drill antes de decidir una restauración material.
6. Registrar actor, motivo, SHA y evidencia en el acta de incidente.

Nunca restaurar encima de la base activa sin preservar primero el estado fallido. Nunca
habilitar browser writes como mecanismo de recuperación.
