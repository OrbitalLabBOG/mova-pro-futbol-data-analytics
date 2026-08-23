---
type: runbook
name: "MOVA FPL — operación del stack VPS"
created: 2026-08-22
updated: 2026-08-22
tags: [mova, fpl, vps, docker, systemd, observability]
status: active
---

# MOVA FPL — operación del stack VPS

## Estado seguro por defecto

El despliegue inicial corre en `shadow`, nivel `A0`, `compliance=pending`, con
`MOVA_ENABLE_BROWSER_WRITES=0` y el `kill_switch=true` en `ops.db`. El collector usa solo
GET públicos. Levantar el stack o habilitar timers **no autoriza cambios en el equipo FPL**.

Supabase no participa del runtime: la operación, evidencia, alertas y auditoría viven en el
VPS. Supabase se reserva para seguimiento externo de construcción del proyecto.

## Topología y paths

| Recurso | Path/endpoint |
| --- | --- |
| checkout aprobado | `/opt/orbital/services/mova-fpl` |
| configuración | `/etc/mova-fpl/runtime.env` |
| control plane | `/var/lib/mova-fpl/db/ops.db` |
| datos/modelos/traza | `/var/lib/mova-fpl/db/` y `/var/lib/mova-fpl/artifacts/` |
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
docker compose build api
docker compose --profile jobs run --rm --no-deps worker python -m mova_fpl.ops.cli migrate
docker compose up -d api
curl --fail http://127.0.0.1:8787/readyz
sudo deploy/bin/install-systemd.sh /opt/orbital/services/mova-fpl
```

Antes de activar el primer tick, colocar por canal seguro —no Git—:

- `fpl_canonical.db` en `/var/lib/mova-fpl/db/`;
- `trace.db` en `/var/lib/mova-fpl/db/`;
- modelos `minutes/` y `points/` en `/var/lib/mova-fpl/artifacts/models/`.

## Operación diaria

```bash
# Vista ejecutiva; abrir túnel ssh -L 8787:127.0.0.1:8787 root@72.60.245.2
curl -s http://127.0.0.1:8787/api/v1/status | python -m json.tool
curl -s http://127.0.0.1:8787/metrics

# Un tick manual, serializado e idempotente
sudo systemctl start mova-fpl-tick.service
sudo journalctl -u mova-fpl-tick.service -n 100 --no-pager

# Evidencia por correlación
curl -s 'http://127.0.0.1:8787/api/v1/jobs?limit=10' | python -m json.tool
curl -s 'http://127.0.0.1:8787/api/v1/audit?limit=50' | python -m json.tool

# Timers y salud
systemctl list-timers --all 'mova-fpl-*'
docker compose ps
docker compose logs --tail=100 api
```

Los logs de containers rotan a 5 × 10 MiB por servicio. Los timers y fallos conservan su
diagnóstico en journald. Cada tick sella bytes fuente y hashes; `ops.db` conserva jobs,
pasos, fuentes, decisiones, controles, salud, incidentes y outbox.

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
```

El backup usa SQLite Online Backup API y ejecuta `quick_check`; nunca hace `cp` de una base
viva ignorando WAL. El manifest contiene SHA-256 y versión SQLite. Retención local: 35 días.
La copia off-host cifrada sigue siendo una decisión pendiente.

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
