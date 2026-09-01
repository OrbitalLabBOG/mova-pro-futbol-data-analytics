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

La interfaz humana está en `https://mova.72-60-245-2.sslip.io` y no requiere contraseña. Está
diseñada para el owner: una señal dominante, próxima fecha y acción requerida. Un pendiente P2
interno no alarma a Julián; sólo un P0/P1, safety inseguro o una capa core degradada cambia la
pantalla a rojo y pide avisar a ORBIX.

El API continúa ligado a `127.0.0.1:8787`. Caddy sólo publica `/` y `/dashboard`; bloquea con 404
`/api/*`, `/metrics`, health y cualquier otra ruta. No abrir el puerto 8787 ni ampliar el matcher
público para resolver una necesidad de diagnóstico.

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
| `/` o `/dashboard` | interfaz humana pública y deliberadamente mínima |
| `/api/v1/cockpit` | panorama completo y estable |
| `/api/v1/triage` | paquete de diagnóstico general |
| `/api/v1/triage?incident_id=...` | diagnóstico de un incidente |
| `/api/v1/orchestration` | stages y dependencias completas |
| `/api/v1/costs` | ledger económico detallado |
| `/api/v1/incidents` | historial operativo |
| `/metrics` | Prometheus; sólo loopback/SSH |

La tabla anterior describe el API local. Desde Internet únicamente existen las dos rutas del
dashboard; los demás endpoints responden `404` antes de llegar al servicio Python.

Las respuestas usan `Cache-Control: no-store`, `nosniff` y nunca incluyen cookies, prompts,
tokens, webhook URL, perfil browser ni squad JSON completo.

## Caddy y recuperación

La configuración versionada del sitio vive en `deploy/caddy/mova-fpl.caddy`; el bloque efectivo
se integra al Caddyfile administrado del host. Antes de recargar:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl --fail --silent http://127.0.0.1:8787/readyz
curl --fail --silent https://mova.72-60-245-2.sslip.io/
curl --silent --output /dev/null --write-out '%{http_code}\n' \
  https://mova.72-60-245-2.sslip.io/api/v1/cockpit
```

Pruebas obligatorias:

- dashboard público: HTTP 200 y resumen humano, sin JSON técnico;
- API, métricas y health públicos: HTTP 404;
- API local mantiene `schema=mova-cockpit-v1` y POST local responde 405;
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
