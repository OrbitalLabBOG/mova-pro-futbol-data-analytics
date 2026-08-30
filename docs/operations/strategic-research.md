---
type: runbook
name: "MOVA FPL — contexto estratégico e investigación"
created: 2026-08-27
updated: 2026-08-30
tags: [mova, fpl, strategy, research, codex, evidence]
status: active
---

# Contexto estratégico e investigación

## Qué resuelve

Esta vertical conecta el estado real del ciclo con investigación web sin conceder autoridad
operativa al LLM:

~~~text
plan versionado
  + decisiones/reviews previos + lecciones validadas
  → memoria estratégica longitudinal sellada
  → CycleManifest sellado
  → foco: plantilla + candidatos xP + notas oficiales FPL
  → request JSON sin secretos
  → Codex web search aislado
  → brief candidato + coverage explícita
  → fetch HTTPS independiente y excerpt/locator sellado
  → validación determinista
  → documentos, señales, conflictos, cobertura, utilidad y costo/uso
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
- cycle_manifests: fuentes, team state, proyección, plan, memoria estratégica y research observados.
- research_runs: request/result, estado, hashes, tiempos, provider y cobertura por corrida.
- research_documents: URL canónica/final, fetch, hashes, excerpt mínimo y locator verificable.
- research_signals: claim, entidad, dirección, confianza, TTL, conflicto y validación.
- research_conflicts: versiones incompatibles que requieren resolución explícita.
- cost_ledger: tokens reportados y subscription_usage=1; no inventa costo por token.

Un manifest se reutiliza si su contenido no cambió. Un plan idéntico no crea revisión. Una
solicitud de investigación referencia el hash exacto del manifest que recibió.
`memory_summary` se reconstruye determinísticamente en cada `prepare`: conserva hasta cuatro
revisiones de plan, ocho decisiones y ocho reviews de GWs estrictamente anteriores, y veinte
lecciones validadas no retiradas. Incluye comparación de revisiones, cobertura, estado de
promoción y hashes de evidencia; no copia evidencia extensa, chain-of-thought ni historial de
chat. Su propio SHA-256 permite demostrar exactamente qué memoria recibió Strategist.
`research_summary.focus` contiene primero los 15 elementos propios y después hasta diez candidatos del
batch baseline aprobado, resueltos contra el último snapshot público. Cada sujeto lleva notas
oficiales, p_play/p60 y razón de inclusión cuando están disponibles. La corrida siguiente recibe
las señales activas anteriores y debe producir deltas, no repetir claims sin cambios.

## Operación

~~~bash
# consulta
mova strategy status
mova strategy research due
mova strategy research coverage
curl -s http://127.0.0.1:8787/api/v1/research/coverage | python -m json.tool

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
listos. El límite del worker es ocho minutos y systemd conserva diez minutos para importación y
cleanup; timeout o salida 0 sin artefacto se registran como errores tipados y nunca como brief.

Antes de publicar el resultado, el worker aplica una reparación estructural determinista. Canoniza
URLs HTTPS, elimina documentos duplicados, descarta referencias que no apuntan a un documento del
mismo brief y reconstruye `coverage.subjects` exactamente en el orden del foco sellado. Una fila sin
evidencia se descarta o degrada a `not_checked`; nunca se agrega fuente, claim o señal. Además,
`generated_at` lo fija el reloj del worker al finalizar porque es metadata de ejecución confiable,
no contenido editorial del modelo. El reporte sanitizado queda en
`research/logs/<run_id>.normalization.json` con conteos, sin URLs ni texto de evidencia.

`mova strategy status` expone el ciclo vigente y también `service`: última corrida global,
conteos por estado, documentos, señales aceptadas y conflictos abiertos. Así la apertura de una
nueva GW no convierte falsamente el health histórico en cero. Prometheus publica además
`mova_research_runs_total`, `mova_research_last_import_timestamp_seconds`,
`mova_research_coverage_ratio`, `mova_research_evidence_ratio`,
`mova_research_measured_gameweeks`,
`mova_strategic_memory_status`, `mova_strategic_memory_items` y
`mova_strategic_plan_revision`. Un estado `empty` es válido al inicio de temporada; `invalid` o
`missing` exige volver a sellar el manifest antes de confiar en ese contexto.

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
- el request archivado ya no reproduce su hash, manifest o ciclo sellado;
- coverage omite, duplica o inventa sujetos fuera de `research_summary.focus`.

`published_at` admite timestamp ISO 8601 con zona o fecha civil `YYYY-MM-DD`; esta última se
normaliza a medianoche UTC sin inventar una hora editorial. `generated_at` y `expires_at`
siempre requieren zona horaria.

En briefs v2, search solo descubre URLs. El importador vuelve a obtener cada página con HTTPS,
valida cada salto contra SSRF, limita cuerpo a 2 MiB, permite únicamente texto/HTML/JSON y
localiza literalmente el `evidence_text` sobre texto normalizado. Conserva solo el excerpt de
máximo 800 caracteres, locator y hashes; no archiva la página completa. Los fetches usan ocho
workers como máximo y timeout individual de ocho segundos, con salida en orden determinista.

Una señal v2 se marca `accepted` solo cuando el locator quedó verificado y existe fuente oficial
verificada o al menos dos URLs verificadas, sin conflicto abierto. Una cita no recuperable,
fuente única no oficial o conflicto queda `candidate`. La confianza del modelo nunca reemplaza
este gate. Briefs v1 históricos permanecen legibles como `legacy_unmeasured/unverified`, pero no
cuentan para el gate de cobertura.

`mova strategy research coverage` mide por GW foco revisado, evidencia sellada, conflictos y
utilidad. La promoción continúa bloqueada hasta observar al menos tres GWs medidos con cobertura
≥ 90 %, evidencia ≥ 80 % y cero conflictos no resueltos en la última corrida de cada ciclo.

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
- `resultado de research cruza el cutoff`: confirmar primero `generated_at` y después fechas de
  documentos. Un timestamp futuro del modelo se evita con el reloj del worker; una fuente realmente
  posterior al deadline sigue siendo rechazo correcto.
- un rechazo terminal mueve resultado y request a `quarantine`; el timer no vuelve a consumir
  Codex. Un replay requiere una nueva solicitud auditada, no copiar el request al inbox.
- coverage `insufficient_gameweeks`: condición esperada antes de tres ciclos v2; no rebajar el
  policy ni contar briefs legacy como evidencia.
- `evidence_*` fallido: revisar `fetch_status`, `fetch_error_code`, MIME/redirect y locator; una
  cita del proveedor no autoriza marcar el documento como verificado.
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
