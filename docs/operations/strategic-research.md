---
type: runbook
name: "MOVA FPL — contexto estratégico e investigación"
created: 2026-08-27
updated: 2026-08-28
tags: [mova, fpl, strategy, research, codex, evidence]
status: active
---

# Contexto estratégico e investigación

## Qué resuelve

Esta vertical conecta el estado real del ciclo con investigación web sin conceder autoridad
operativa al LLM:

~~~text
plan versionado
  → CycleManifest sellado
  → foco: plantilla + candidatos xP + notas oficiales FPL
  → request JSON sin secretos
  → Codex web search aislado
  → brief candidato
  → validación determinista
  → documentos, señales, conflictos y costo/uso
~~~

SQLite ops.db continúa como writer oficial hasta el cutover de HV1-02. PostgreSQL conserva
datos y analítica; Supabase es solamente PM. Ninguna señal modifica predicciones, decisiones o
el equipo por sí sola.

El servicio tiene dos capas complementarias. El collector FPL conserva cada seis horas el
campo oficial `news`, `status` y `chance_of_playing_next_round`; el worker Codex hace
investigación web profunda únicamente en ventanas de decisión. No existe un scraper de prensa
residente ni una llamada LLM por tick.

## Contratos

- season_plans: horizonte, supuestos, ventanas de chips y guardrails, por revisión.
- cycle_manifests: fuentes, team state, proyección, plan y research observados.
- research_runs: request/result, estado, hashes, tiempos y provider.
- research_documents: metadata de cada URL citada.
- research_signals: claim, entidad, dirección, confianza, TTL, conflicto y validación.
- research_conflicts: versiones incompatibles que requieren resolución explícita.
- cost_ledger: tokens reportados y subscription_usage=1; no inventa costo por token.

Un manifest se reutiliza si su contenido no cambió. Un plan idéntico no crea revisión. Una
solicitud de investigación referencia el hash exacto del manifest que recibió.
`research_summary.focus` contiene primero los 15 elementos propios y después hasta diez candidatos del
batch baseline aprobado, resueltos contra el último snapshot público. Cada sujeto lleva notas
oficiales, p_play/p60 y razón de inclusión cuando están disponibles. La corrida siguiente recibe
las señales activas anteriores y debe producir deltas, no repetir claims sin cambios.

## Operación

~~~bash
# consulta
mova strategy status
mova strategy research due

# activar una revisión explícita del plan
mova strategy plan --file /path/season-plan.json \
  --actor julian --reason "revisión del horizonte GW2–GW8"

# sellar el estado sin llamar al LLM
mova strategy prepare

# flujo manual equivalente al timer
mova strategy research enqueue
docker compose --profile research run --rm --no-deps -T research
mova strategy research import

# excepción auditada de cadencia
mova strategy research enqueue --force --actor julian \
  --reason "rueda de prensa material" \
  --idempotency-key "research:gw02:press-final"
~~~

due y una cadencia no vencida devuelven código 75. El timer evalúa cada 15 minutos, pero solo
encola dentro de las 30 horas pre-deadline y como máximo una vez cada seis horas. Entre T-120 y
T-70 minutos exige una corrida final aunque la cadencia rutinaria aún no venza; después de T-70
no inicia research nuevo. Un tick sin request pendiente no levanta el contenedor Codex. El
worker usa un lock exclusivo y procesa una solicitud; el importador procesa todos los resultados
listos.

`mova strategy status` expone el ciclo vigente y también `service`: última corrida global,
conteos por estado, documentos, señales aceptadas y conflictos abiertos. Así la apertura de una
nueva GW no convierte falsamente el health histórico en cero. Prometheus publica además
`mova_research_runs_total` y `mova_research_last_import_timestamp_seconds`.

## Aislamiento y auth

mova-research monta solamente:

- /var/lib/mova-fpl/artifacts/research como spool;
- /var/lib/mova-fpl/codex-home como CODEX_HOME persistente.

No monta repo, runtime.env, DB, modelos, perfil browser, password PostgreSQL ni key de odds.
Corre sin capabilities, con root filesystem read-only, usuario 10002 y herramientas Codex de
shell, Computer Use, browser, apps y multi-agent deshabilitadas. Solo quedan web search y la
salida estructurada.

Provisionar auth.json por un canal seguro, propietario 10002:10002, directorio 0700 y archivo
0600. Es una credencial: no imprimir, abrir en logs, copiar a Git, Supabase, artefactos de
evidencia o backups. El archivo debe persistir porque Codex puede refrescarlo. host-probe
publica únicamente auth_present=true/false.

## Criterios de aceptación

El importador rechaza y pone en cuarentena un brief si:

- supera 1 MiB o no cumple la identidad/hash del request;
- cita URL distinta de HTTPS pública, credenciales embebidas, IP privada o puerto no 443;
- usa una taxonomía desconocida, fecha futura, TTL vencido o elemento inválido;
- una señal o conflicto cita documentos ausentes.

`published_at` admite timestamp ISO 8601 con zona o fecha civil `YYYY-MM-DD`; esta última se
normaliza a medianoche UTC sin inventar una hora editorial. `generated_at` y `expires_at`
siempre requieren zona horaria.

Una señal se marca accepted solo con fuente oficial o al menos dos URLs distintas y sin
conflicto abierto. Una fuente única no oficial queda candidate. La confianza del modelo nunca
reemplaza este gate.

Límite vigente: `research_documents` sella metadata normalizada y hash del registro citado; no
hace todavía un fetch HTTP independiente ni conserva locator/excerpt verificable. Esa mejora se
reserva para hardening si la evaluación multi-GW demuestra falsos positivos o baja trazabilidad.

## Diagnóstico

~~~bash
mova strategy status
mova doctor --json
systemctl status mova-fpl-research.timer mova-fpl-research.service
journalctl -u mova-fpl-research.service -n 100 --no-pager
find /var/lib/mova-fpl/artifacts/research -maxdepth 2 -type f -printf '%P\n'
~~~

- queued persistente: revisar service, auth y último error JSON; no mostrar contenido sensible.
- rejected: revisar el error sanitizado y quarantine; no insertarlo a mano.
- auth ausente/expirado: detener el timer, renovar por canal autorizado, verificar permisos y
  reactivar.
- web/search no disponible: conservar el último brief aceptado hasta su TTL; no volverlo vigente
  artificialmente.

## Rollback

~~~bash
systemctl disable --now mova-fpl-research.timer
docker compose --profile research down
~~~

La migración es aditiva. El rollback de código conserva tablas, requests, resultados y audit.
No se borra la cola durante recuperación. Reponer la revisión anterior de checkout/imagen,
migrar solo hacia delante y ejecutar mova doctor. Nada de este flujo habilita browser writes.
