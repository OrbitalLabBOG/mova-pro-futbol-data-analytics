---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Data and Observability"
created: 2026-08-21
updated: 2026-08-23
tags: [mova, fpl, sqlite, vps, observability]
status: proposed
---

# Datos y observabilidad

## Frontera de datos

Todo el runtime vive en el VPS. Supabase se usa únicamente como tablero PM de construcción
del proyecto, actualizado por fuera del servicio. El código FPL no conoce su URL, SDK ni
credenciales.

| Capa | Contenido | Autoridad |
| --- | --- | --- |
| `fpl_canonical.db` | `player_gameweek`: 253.890 filas, 61 campos, 10 temporadas; fixture embebido | entrenamiento y backtest |
| `trace.db` | corridas, decisiones, benchmarks, modelos e intervenciones experimentales | evaluación deportiva |
| `ops.db` | ciclos, jobs, fuentes, gates, ejecución, alertas y auditoría | operación autónoma |
| artefactos locales | bytes fuente, manifests, proyecciones, modelos, actas, DOM y capturas | replay y evidencia |
| logs/health | journal, JSON rotado, métricas y muestras de salud | diagnóstico y alerta |

No se amplía `player_gameweek` con datos operativos. `trace.db` no se usa como scheduler.
Una decisión reconciliada puede exportarse desde `ops.db` hacia `trace.db` mediante un job
de settlement; nunca se hace dual-write durante el deadline.

## Decisión: SQLite local, no Postgres

`ops.db` usa SQLite ≥3.51.3 en modo WAL. Es suficiente porque:

- existe un solo VPS y un solo scheduler activo;
- el volumen esperado es bajo: decenas de ciclos y miles de jobs/señales, no millones de
  escrituras concurrentes;
- el browser devuelve resultados al engine y jamás escribe la base directamente;
- systemd + `flock` evitan ticks solapados;
- `BEGIN IMMEDIATE`, constraints y claves de idempotencia protegen cada transición;
- elimina otro contenedor, puerto, credencial, backup y consumo permanente de RAM.

Postgres se reconsidera solo si aparece un segundo host escritor o concurrencia real que no
pueda serializarse. Esa migración queda detrás de un repository port; no se anticipa ahora.

El SQLite 3.45.1 instalado en el host **no es apto para este runtime**: pertenece al rango
afectado por el bug upstream de WAL-reset corregido en 3.51.3. La imagen engine debe incluir
y comprobar una versión corregida. Worker, API, checkpoint, integrity checks y backup usan
esa misma familia de binarios/librería; ningún unit invoca `/usr/bin/sqlite3` sobre
`ops.db`.

## Layout del VPS

```text
/opt/orbital/services/mova-fpl/       # checkout aprobado + compose
/etc/mova-fpl/                        # config y secrets 0600
/var/lib/mova-fpl/
├── db/
│   ├── fpl_canonical.db              # read-only para runtime
│   ├── trace.db                      # laboratorio/settlement
│   └── ops.db                        # control plane WAL
├── agent/
│   ├── inbox/                        # ResearchRequest sellados
│   ├── processing/                   # claims atómicos
│   ├── outbox/                       # ResearchResult sellados
│   ├── quarantine/                   # outputs rechazados
│   └── codex-home/                   # 0700; fuera de backup general
├── artifacts/
│   ├── sources/
│   ├── datasets/
│   ├── projections/
│   ├── models/
│   ├── decisions/
│   ├── research/
│   └── evidence/
└── browser-profile/                  # 0700; fuera de backup general
/opt/orbital/backups/mova-fpl/        # backups consistentes + checksums
```

Los `.db` y `.joblib` actuales están ignorados por Git. El primer release debe producir un
bundle firmado por manifest y copiarlo al VPS; clonar el repositorio no basta.

## Esquema conceptual de `ops.db`

Tipos SQLite estrictos donde aplique, timestamps UTC ISO-8601, precios en décimas enteras,
foreign keys activas y estados protegidos por `CHECK`.

### Configuración y ciclo

| Tabla | Propósito | Invariante |
| --- | --- | --- |
| `schema_migrations` | versión local del esquema | version unique, checksum |
| `runtime_controls` | mode, action level, compliance y kill switches | historia append-only/effective_at |
| `seasons` | reglas y temporada | season_code unique, rules hash |
| `gameweek_cycles` | agregado operativo por GW | unique season+gw; deadline; phase; revision |

### Jobs y salud

| Tabla | Propósito | Invariante |
| --- | --- | --- |
| `job_runs` | ledger de tick/collector/research/model/browser/settlement | idempotency key unique; attempt/status/times |
| `job_steps` | fases internas y duración | job+step+attempt unique |
| `health_samples` | CPU, memoria, disco, DB/browser/source health | retención acotada |
| `audit_events` | cambios de control y acciones humanas | append-only, actor y reason |

### Entradas y lineage

| Tabla | Propósito | Invariante |
| --- | --- | --- |
| `source_snapshots` | metadata de entradas inmutables | source+sha unique; URI; freshness/quality |
| `research_signals` | claims citados, TTL y conflicto | player/claim/source/observed versionado |
| `agent_runs` | task/backend/model y consumo de cada corrida | run+attempt unique; hashes y status |
| `research_queries` | queries ejecutadas y discovery | run+query hash unique |
| `research_documents` | evidencia web normalizada | canonical URL+hash; tier/TTL/storage policy |
| `research_signal_sources` | corroboración many-to-many | signal+document unique |
| `research_conflicts` | claims incompatibles | group/severity/status/resolution versionados |
| `team_state_snapshots` | squad, XI, PP/SP/CP, FT, chips | fingerprint + source + observed_at |
| `dataset_releases` | dataset entrenable sellado | sha, as_of cutoff, leakage audit |
| `model_releases` | artifacts de modelo | model+version unique; dataset, metrics y sha |
| `projection_runs` | metadata de matrices xP | manifest/hash; detalle en Parquet/SQLite artifact |

Implementación: el adapter browser produce `mova-fpl-private-team-state-v1` con allowlist
exacta. El engine rechaza claves adicionales, valida identidad/cuotas/rangos, persiste un
artefacto inmutable y registra su path, SHA-256 y estado de calidad. El fingerprint excluye
`observed_at` para detectar que el estado no cambió, mientras cada captura conserva una
observación propia para que frescura y disponibilidad sigan siendo medibles.

### Decisión y ejecución

| Tabla | Propósito | Invariante |
| --- | --- | --- |
| `intervention_runs` | intervención estructurada y citada | payload/rationale sha; policy version |
| `decision_runs` | revisiones de la decisión | cycle+revision unique; manifest y fingerprint |
| `decision_players` | 15/XI/banca/C/VC/transfers normalizados | decision+element unique; roles/checks |
| `web_executions` | envelope e intento externo | decision+action level unique mientras esté activo |
| `verification_checks` | assertions post-reload | execution+check unique; expected/observed/pass |
| `incidents` | fallo, severidad, owner y resolución | timeline y referencias al ciclo/job/execution |
| `outbox_events` | alerta local pendiente/enviada/confirmada | event key unique; attempt/ack |

La lineage detallada vive en el manifest de decisión: lista los hashes de snapshots,
dataset, modelos, proyecciones, prompt/config e intervención. Se evita crear varias tablas
de unión hasta que una consulta operacional real las justifique.

## Ajustes SQLite obligatorios

Al abrir `ops.db`:

```text
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
PRAGMA synchronous=FULL;        # control y writes externos
```

- un solo proceso engine escribe;
- `mova-api` abre `mode=ro` + `query_only=ON`; comparte archivos WAL pero no código de write;
- el arranque ejecuta `SELECT sqlite_version()` y rechaza versiones menores a 3.51.3;
- transacciones cortas, sin HTTP/browser dentro;
- `INSERT ... ON CONFLICT` o unique constraints para idempotencia;
- `PRAGMA quick_check` diario e `integrity_check` en backup/restore;
- checkpoint WAL después de ciclos cerrados y antes de backup.

## Manifest de corrida

Cada decisión referencia un JSON canónico:

```json
{
  "schema_version": "mova-fpl-run-v1",
  "season": "2026-27",
  "gw": 2,
  "deadline_at": "...Z",
  "cutoff_at": "...Z",
  "git_sha": "...",
  "image_digest": "...",
  "rules_sha256": "...",
  "config_sha256": "...",
  "prompt_sha256": "...",
  "dataset_release": {"version": "...", "sha256": "..."},
  "model_releases": [{"name": "minutes", "version": "1.1.0", "sha256": "..."}],
  "source_snapshots": [{"source": "fpl_bootstrap", "sha256": "...", "uri": "..."}],
  "projection_sha256": "...",
  "intervention_sha256": "...",
  "decision_fingerprint": "..."
}
```

El manifest se almacena como artefacto y su hash en `decision_runs`. Es la raíz de replay e
idempotencia.

## Frontera entrenamiento ↔ operación

```text
operación pre-deadline
    ↓ (solo lectura para decidir)
decisión y ejecución
    ↓
resultado final reconciliado
    ↓
export de settlement
    ↓
dataset_release candidato + leakage audit
    ↓
model candidate → backtest/shadow → promote
```

Noticias, señales, estado privado o puntos aún provisionales no entran automáticamente a
entrenamiento. La promoción ocurre después de settlement y crea un dataset nuevo; nunca
reescribe una release anterior.

## Backups y recuperación

Un timer systemd diario ejecuta, bajo el mismo `flock` y dentro de `mova-engine`:

1. `quick_check`;
2. checkpoint WAL con SQLite ≥3.51.3 y sin writer concurrente;
3. SQLite Online Backup API/`.backup` para `ops.db` y `trace.db`;
4. copia del canonical DB, manifests, modelos y evidencia decisiva;
5. SHA-256 de cada archivo y manifest del backup;
6. restore smoke sobre directorio temporal;
7. retención propuesta: 14 diarios y 8 semanales.

No se copia una base viva con `cp` ignorando WAL. El perfil browser/cookies se excluye: su
recuperación es reautenticación humana. Al estar todo en un solo VPS, una falla total de
disco sigue siendo riesgo residual hasta autorizar backup off-host.

## Observabilidad local

No se instala inicialmente Prometheus, Grafana, Postgres, Redis ni un collector OTel. El VPS
no tiene hoy esa plataforma y ya ejecuta once contenedores. La primera versión ofrece:

1. ledger durable en `ops.db`;
2. logs JSON correlacionados por IDs;
3. `health_samples` con retención;
4. API privada `mova-api` con `/healthz`, `/readyz`, `/metrics` y dashboard mínimo;
5. watchdog systemd independiente que puede alertar aunque el stack esté caído;
6. `sysstat` y métricas Docker/host como diagnóstico complementario.

El endpoint `/metrics` es Prometheus-compatible para conectar un backend después sin cambiar
el dominio.

### Cadencia adaptativa del estado privado

El timer despierta cada cinco minutos, pero el gate consulta únicamente el bootstrap público
y no inicia el browser mientras la última observación autenticada siga fresca. La política
comparte una sola función entre collector y motor de decisión:

| Distancia al deadline | Captura privada máxima |
| --- | ---: |
| Más de 24 horas o settlement | 6 horas |
| Últimas 24 horas | 1 hora |
| Últimas 3 horas | 15 minutos |
| Últimos 30 minutos | 5 minutos |

La observación debe corresponder a la misma temporada y GW y tener calidad `valid`. Una
captura inmediata `--force` se ejecuta antes y después de cualquier acción, sin depender del
reloj. Evaluar el gate no abre Chromium; una captura debida inicia el browser aislado, hace
el GET autenticado, importa el artefacto y lo detiene. El techo configurable de 6 horas es
fail-safe y el motor usa siempre el menor valor entre ese techo y la cadencia de la fase.

### Logs

Campos mínimos:

`timestamp`, `severity`, `service`, `run_id`, `cycle_id`, `job_id`, `season`, `gw`, `phase`,
`event`, `status`, `duration_ms`, `snapshot_sha`, `model_version`,
`decision_fingerprint`, `error_code`.

Docker rota `json-file` por servicio; journald conserva diagnóstico del timer/watchdog. Los
eventos críticos también se guardan en `audit_events`/`incidents`, porque el journal actual
solo retiene siete días.

Nunca registrar cookies, tokens, HTML completo, passwords, OTP/MFA ni profile paths
exportables.

### Métricas

| Métrica | Uso |
| --- | --- |
| `mova_tick_last_success_unixtime` | scheduler muerto |
| `mova_deadline_timestamp_seconds` | countdown |
| `mova_job_runs_total{job,status}` | tasa de éxito/fallo |
| `mova_job_duration_seconds{job}` | p50/p95 |
| `mova_source_age_seconds{source}` | frescura |
| `mova_source_quality{source}` | gate de datos |
| `mova_decision_feasible` | validez |
| `mova_execution_attempts_total{level,result}` | seguridad de writes |
| `mova_execution_verified` | persistencia real |
| `mova_hard_stop_active` | protección |
| `mova_open_incidents{severity}` | carga operativa |
| `mova_vps_memory_available_bytes` / `disk_free_bytes` | capacidad local |

No usar run, job, player, URL, hash ni fingerprint como labels. Esos valores van en logs y
ledger.

## SLO y gates

| ID | Objetivo | Alerta/bloqueo |
| --- | --- | --- |
| SLO-01 | último tick exitoso <10m | P1; P0 dentro de T-90m |
| SLO-02 | deadline descubierto y consistente en dos lecturas | bloqueo si cambia materialmente |
| SLO-03 | bootstrap/fixtures ≤15m al freeze | bloqueo de write |
| SLO-04 | fuentes noticiosas obligatorias ≤60m | bloqueo/degradación declarada |
| SLO-05 | decisión válida antes de T-60m | P0 en T-60m |
| SLO-06 | persistencia verificada antes de T-30m | P0; conservar estado anterior |
| SLO-07 | cero mutaciones nuevas después de T-15m | P0 |
| SLO-08 | cero ejecuciones externas duplicadas | P0 |
| SLO-09 | 100% de writes con evidencia post-reload | ciclo fallido si no |
| SLO-10 | `quick_check` diario y backup restaurable | P1 si falla |

## Tablero local

Acceso solo por `127.0.0.1` + túnel SSH, salvo decisión posterior. Vistas:

1. **Now:** countdown, fase, modo, compliance, kill switch, frescura y última verificación.
2. **Decision:** squad diff, xP, transfer/hit/chip, señales y sensibilidad.
3. **Operations:** jobs, retries, browser, SQLite, recursos y backups.
4. **Learning:** forecast vs resultado, calibración, shadow y atribución.
5. **Audit:** revisions, envelope, checks, evidencia e incidentes.

## Retención

| Dato | Retención propuesta |
| --- | --- |
| decisiones, manifests, modelos usados y evidencia de write | temporada + 24 meses |
| snapshots usados por decisión | temporada + 24 meses |
| snapshots no decisivos | 180 días |
| `ops.db`, auditoría e incidentes | 3 temporadas |
| logs JSON/journal | 7–30 días según capa |
| `health_samples` | 180 días |
| perfil/cookies | mientras la cuenta esté activa; sin backup general |
