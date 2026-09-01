---
type: runbook
name: "MOVA FPL — cockpit, triage y acceso web"
created: 2026-09-01
updated: 2026-09-01
tags: [mova, fpl, cockpit, cli, dashboard, incidents, observability]
status: active
---

# MOVA FPL — cockpit, triage y acceso web

El cockpit es una vista read-only sobre el control plane vigente. No crea otro ledger, no consulta
FPL directamente y no concede autoridad. CLI, API y dashboard comparten
`schema=mova-cockpit-v1`; el writer operativo continúa siendo `ops.db` hasta un cutover aprobado.

## Entrada rápida

```bash
# Panorama para un humano
mova cockpit

# Contrato máquina para ORBIX/Codex
mova cockpit --json

# Terminal viva; Ctrl-C termina sin mutar el runtime
mova cockpit --watch 30

# Diagnóstico general o centrado en un incidente
mova triage
mova triage --incident-id incident_...
mova triage --incident-id incident_... --json
```

La interfaz web autenticada está en `https://mova.72-60-245-2.sslip.io`. El API continúa ligado a
`127.0.0.1:8787`; Caddy termina TLS y exige autenticación antes de hacer reverse proxy. No abrir el
puerto 8787 en el firewall ni cambiar el bind para publicar el dashboard.

Las credenciales web son un secreto del host, no de Git. El operador autorizado las recupera por
SSH desde `/etc/mova-fpl/dashboard-credentials`; nunca debe copiarlas a actas, logs, Supabase,
issues o argumentos de proceso. El hash bcrypt vive en el environment root-only de Caddy.

## Qué responde el cockpit

| Bloque | Pregunta |
| --- | --- |
| `verdict/headline` | ¿hay que intervenir ahora? |
| `gameweek` | ¿qué GW, fase y deadline gobiernan el ciclo? |
| `authority` | ¿qué nivel está activo y están permitidas escrituras? |
| `functions` | ¿collector, analytics, research, browser, alertas y backups están habilitados? |
| `workflow` | ¿en qué stage está el ciclo y qué outcome produjo? |
| `economics` | ¿cuántos tokens/usos están comprometidos y quedan disponibles? |
| `quality` | ¿cómo están runtime, safety, readiness, datos, modelos y PostgreSQL? |
| `alerts` | ¿qué incidente o condición debe diagnosticar el operador? |
| `runtime` | ¿qué SHA y tick respaldan el snapshot? |

`technical_eligible_level` es evidencia, no permiso. `writes_enabled=false`, A0, kill switch o
browser writes apagado siguen dominando aunque todas las tarjetas se vean verdes.

## Triage estándar para ORBIX

1. Ejecutar `mova cockpit --json`.
2. Si `verdict=critical`, ejecutar `mova triage --incident-id ... --json` para cada P0/P1.
3. Verificar `git_sha`, deadline, safety, workflow, presupuesto y correlation/job IDs.
4. Ejecutar `mova doctor --json` si el runtime está degradado o la evidencia se contradice.
5. Leer únicamente el runbook de la capa afectada: datos, analytics, research, ejecución o
   PostgreSQL.
6. Reparar la causa; no cerrar manualmente el incidente para maquillar el dashboard.
7. Confirmar recuperación con `mova cockpit`, `mova alerts status` y el comando específico.

`mova triage` contiene datos sanitizados y comandos siguientes, pero no ejecuta reparaciones.
Conservar su `incident_id`, `job_id` y `correlation_id` al abrir una iteración de código.

## Sentinel deadline-aware

El watchdog evalúa infraestructura, cola agentic y además hitos del ciclo. La política evita
alertas durante una espera normal:

- antes de T−6h, research o deliberación degradados permanecen visibles pero no abren incidente;
- desde T−6h, research o Strategist/Critic sin terminal abren un P1 deduplicado;
- desde T−3h, contexto, envelope/validator o preflight incompletos abren P1;
- una ejecución autorizada todavía pendiente en T−3h abre P1;
- una ejecución pendiente después del deadline o un fallo terminal de ejecución abre P0;
- violaciones de dependencias se vuelven P0 dentro de T−6h.

El título canónico es `Autonomous cycle deadline risk`. Cuando los hitos se recuperan, el watchdog
resuelve causalmente el incidente y conserva auditoría. Métricas:

```text
mova_workflow_deadline_healthy
mova_workflow_seconds_to_deadline
mova_workflow_deadline_risks{severity="P0|P1"}
```

No se alerta settlement inmediatamente después del deadline: FPL puede tardar en marcar
`data_checked`. Esa transición conserva su gate propio.

## Acciones y autoridad

El dashboard no tiene POST ni botones de activación. Un `POST` al API responde
`405 read_only_control_plane`. Las mutaciones siguen separadas y exigen sus argumentos auditados:

```bash
mova control ... --actor ... --reason ...
mova execute ... --actor ... --reason ... --idempotency-key ...
mova alerts acknowledge --incident-id ... --actor ... --reason ...
```

No convertir una acción sugerida por el cockpit en autorización. Promover A1/A2/A3, habilitar
browser writes, reiniciar el host o cambiar el equipo requiere la aprobación correspondiente.

## API read-only

| Endpoint | Uso |
| --- | --- |
| `/` o `/dashboard` | interfaz humana |
| `/api/v1/cockpit` | panorama completo y estable |
| `/api/v1/triage` | paquete de diagnóstico general |
| `/api/v1/triage?incident_id=...` | diagnóstico de un incidente |
| `/api/v1/orchestration` | stages y dependencias completas |
| `/api/v1/costs` | ledger económico detallado |
| `/api/v1/incidents` | historial operativo |
| `/metrics` | Prometheus; acceso autenticado por Caddy |

Las respuestas usan `Cache-Control: no-store`, `nosniff` y nunca incluyen cookies, prompts,
tokens, webhook URL, perfil browser ni squad JSON completo.

## Caddy y recuperación

La configuración versionada del sitio vive en `deploy/caddy/mova-fpl.caddy`; el bloque efectivo
se integra al Caddyfile administrado del host. Antes de recargar:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl --fail --silent http://127.0.0.1:8787/readyz
curl --fail --silent --user "$USER:$PASSWORD" \
  https://mova.72-60-245-2.sslip.io/api/v1/cockpit
```

Pruebas obligatorias:

- sin credenciales: HTTP 401;
- credenciales válidas: dashboard 200 y `schema=mova-cockpit-v1`;
- POST autenticado: HTTP 405;
- `readyz` local continúa 200;
- Caddy y API permanecen activos después de reload.

Si Caddy falla, restaurar el backup explícito del Caddyfile y validar antes de recargar. No tocar
el bind del API como workaround.

## Alertas externas

El banner web no sustituye push. Mientras `mova alerts channel` diga `local_only`, journald es el
único destino y readiness permanece pending. Para configurar un webhook se necesita que Julián
elija destino y owner; después se provisiona `/etc/mova-fpl/alert-webhook.json` root-only y se
ejecuta una sola prueba auditada:

```bash
mova alerts test --actor julian --reason "validar canal operativo" \
  --idempotency-key "alert-live:<fingerprint>:v1"
```

No inventar un bot, chat ID, webhook o owner. `sent` prueba entrega HTTP, no lectura humana.

## Límites deliberados

- No Vercel ni GitHub Pages en v1: evitar otro origen, secretos frontend y una segunda capa de
  autenticación.
- No controles mutables desde navegador.
- No datos operativos en Supabase; sólo tracking PM.
- No alertas por condiciones longitudinales normales como research 1/3 o PostgreSQL 2/3.
