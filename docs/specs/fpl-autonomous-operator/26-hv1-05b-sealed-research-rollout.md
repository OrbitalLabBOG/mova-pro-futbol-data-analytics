---
type: evidence
name: "HV1-05B — Evidencia web sellada y cobertura explícita"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, hv1-05, research, evidence, coverage, vps]
status: deployed-shadow-partial
---

# HV1-05B — Evidencia web sellada y cobertura explícita

## Resultado

El servicio de research opera con contrato `mova-research-brief-v2`. Web search descubre URLs,
pero ninguna cita entra como evidencia por sí sola: el importador recupera cada página mediante
HTTPS público, verifica un fragmento literal sobre texto normalizado y sella únicamente excerpt,
locator y hashes. La señal continúa sin autoridad sobre modelos, decisión o ejecución.

El corte está desplegado y verificado en infraestructura, pero HV1-05 permanece parcial. La
primera corrida v2 real fue rechazada correctamente por una referencia inconsistente y por tanto
no cuenta como GW medida. El gate exige tres jornadas v2 válidas.

## Contrato implementado

- URL HTTPS canónica, sin credenciales, puertos arbitrarios, IP privada ni tracking conocido;
- resolución DNS pública y validación de cada redirect antes de conectar;
- MIME acotado a HTML/XHTML/text/JSON, cuerpo máximo 2 MiB y timeout de ocho minutos para el
  agente, ocho segundos por fetch;
- hasta ocho fetches concurrentes, resultado normalizado en orden determinista;
- almacenamiento `minimal_excerpt`, máximo 800 caracteres; no conserva la página completa;
- una señal v2 solo puede ser `accepted` con locator verificado y fuente oficial verificada o
  dos documentos verificados, sin conflicto abierto;
- coverage exacta de cada elemento del foco con estado, fuentes, grupo y utilidad;
- briefs v1 históricos quedan `legacy_unmeasured/legacy_unverified`;
- CLI `mova strategy research coverage`, API `/api/v1/research/coverage` y métricas Prometheus;
- un rechazo terminal mueve request y resultado a cuarentena para impedir retries/costo infinito.

## Versiones y migraciones

| Entrega | Branch | VPS main |
| --- | --- | --- |
| fetch/locator, coverage, API/CLI y adapters PostgreSQL | `6869cc0` | `b185af66` |
| schemas Structured Outputs estrictos | `fd11b5a` | `1ed3b543` |
| timeout/output ausente fail-closed | `ee57683` | `2a115762` |
| timeout Compose alineado a 480 s | `9665746` | `e561d99c` |
| cuarentena terminal de request | `6573232` | `1f5bde0e` |

- SQLite: migration `015`, aplicada.
- PostgreSQL: migration `017`, aplicada.
- Shadow import inicial: `pgimport_e33459be247b4165b9baacdd563de3ff`.
- Shadow import final: `pgimport_b7cbdb3446404cb5af05b470ed4d7bfe`.
- Paridad final: 52 tablas, 51 exactas + 1 por invariantes, cero fallos.

## Corrida real controlada GW3

| Campo | Resultado |
| --- | --- |
| Run | `research_b04f466ca5bca55ec669e1b9031329b4` |
| Motivo | rollout v2 read-only, forzado e idempotente fuera de ventana |
| Presupuesto | reserva/charge conservador de 120.000 tokens; sin costo USD inventado |
| Foco | 25 sujetos |
| Brief producido | 23 documentos, 11 señales, 3 conflictos, 25 filas de coverage |
| Resultado import | `rejected` |
| Causa | un conflicto citó una URL que no estaba en `documents` |
| Persistencia | resultado y request en `quarantine`; inbox 0 |
| Efecto operativo | ninguno; cero documentos/señales v2 importados |

La corrida encontró dos fallos de harness antes de producir el brief. Primero, dos propiedades
nullable no estaban incluidas en `required`, requisito de Structured Outputs. Segundo, Compose
sobrescribía el timeout de ocho minutos con 300 segundos y el worker trataba una salida 0 sin
artefacto como éxito. Ambos quedaron corregidos y cubiertos por tests. El tercer intento del mismo
run produjo el JSON en menos de ocho minutos; el importador detectó la inconsistencia relacional y
lo rechazó. No se editó ni insertó manualmente el resultado.

El rechazo reveló además que un request terminal permanecía en inbox y habría podido reintentar
Codex por timer sin una nueva reserva. La revisión final lo corrige y limpia requests terminales
antiguos. Este comportamiento se probó con replay: segunda importación procesa cero artefactos.

## Verificación final

| Check | Resultado |
| --- | --- |
| Suite local | `997 passed, 1 skipped, 79 deselected` |
| Docker Compose | config válida; timeout efectivo `480000` |
| Doctor VPS | 22 PASS, 0 WARN, 0 FAIL |
| PostgreSQL verify | pass, 52 tablas verificadas |
| API | healthy en revisión `1f5bde0e` |
| Timers | 8 activos; 0 unidades MOVA fallidas |
| Research spool | inbox 0; request/result terminales en quarantine |
| Coverage | 0 GWs medidas, 1 GW legacy; `insufficient_gameweeks` |
| Controles | `shadow/A0`, `kill_switch=true`, `browser_writes=false`, compliance pendiente |
| Backups | pre `20260830T210109Z`; post `20260830T212832Z` |

## Estado y próximo gate

La infraestructura prevista por HV1-05 está implementada: evidencia independiente, provenance,
coverage, utilidad, costos, PostgreSQL shadow, API, métricas, skill y recuperación terminal. No se
promueve todavía porque no existe una corrida v2 importada. El siguiente intento debe ocurrir en
la ventana normal, con un nuevo run auditado; debe demostrar que cada señal, conflicto y fila de
coverage referencia exclusivamente documentos inventariados. Después se acumulan tres GWs y se
evalúan cobertura ≥ 90 %, evidencia ≥ 80 % y cero conflictos abiertos antes de cualquier cambio
de autoridad.
