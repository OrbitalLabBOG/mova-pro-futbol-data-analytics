---
type: runbook
name: "MOVA FPL — policy de autonomía y preflight"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, execution, preflight, autonomy, guardrails]
status: active
---

# Policy de autonomía y preflight

HV1-07A/B introduce la frontera durable previa al browser. HV1-07C añade la reserva apply-once,
lease, límite de ambigüedad y verificador post-reload. HV1-07D.3 conecta un driver host acotado a
capitanía con fail-closed estricto. HV1-07D.4 añade el instruction stream tipado de XI/banca,
todavía detrás de un gate físico de rehearsal. HV1-07F hace ese gate durable y resistente a
reintentos. Los controles A0 y el contenedor browser conservan
las escrituras apagadas; instalar el driver no concede autoridad.

## Contrato

```text
DecisionEnvelope inmutable
  + manifest y team state releídos
  + controles append-only
  + deadline/incidentes/ejecución previa
  → AutonomyPolicy determinista
  → ExecutionPlan blocked | authorized | noop
```

El artifact cumple
[`execution-plan-v1.schema.json`](../specs/fpl-autonomous-operator/contracts/execution-plan-v1.schema.json).
Conserva hashes de envelope/manifest, fingerprints pre/post, diff exacto, deadline, controles,
gates y clave idempotente. `authorized` significa maduro para un executor futuro; por sí mismo no
produce escrituras.

## Operar

```bash
mova execute status
mova execute preflight \
  --actor codex \
  --reason "rehearsal shadow antes del deadline GW3" \
  --idempotency-key "execution-preflight:2026-27:gw03:rehearsal-01"

curl -s http://127.0.0.1:8787/api/v1/execution-plans?limit=5 | jq
curl -s http://127.0.0.1:8787/api/v1/execution-preflight-checks?limit=50 | jq
curl -s http://127.0.0.1:8787/metrics | grep '^mova_execution_'
```

### Ledger de rehearsals

Un rehearsal sólo cuenta si un artifact `mova-browser-rehearsal-evidence-v1` está dentro de
`MOVA_ARTIFACT_ROOT`, reproduce su `content_sha256`, referencia artifacts fuente existentes con
hash físico correcto, usa la versión vigente del contrato y declara `writes_attempted=false`.
El camino preferido para capitanía sella directamente el probe sanitizado generado por el host:

```bash
deploy/bin/browser-session.sh probe \
  > /var/lib/mova-fpl/artifacts/browser-probes/2026-27-gw03-captaincy.json
mova execute rehearsal-captaincy-probe \
  --source /var/lib/mova-fpl/artifacts/browser-probes/2026-27-gw03-captaincy.json \
  --cycle-id 2026-27-gw03 \
  --actor mova-operator \
  --reason "probe semántico read-only conciliado" \
  --idempotency-key "rehearsal:2026-27:gw03:captaincy:r2-2026.08.2"
deploy/bin/browser-session.sh stop
```

El importador aplica una allowlist estricta al JSON del probe, exige sesión, 15 picks/controles,
orden posicional, once player sheets y selecciones C/VC conciliadas con el GET privado. Abrir y
cerrar esos sheets no cambia el equipo ni pulsa `Save`. El wrapper reserva stdout exclusivamente
para el JSON; mensajes de Compose van a stderr para que un primer build/recreate no contamine el
artifact.

El mismo probe de pick-team puede sellar evidencia independiente de lineup: valida los quince
slots, identidades, índices de ambos controles y orden visual, sin ejecutar swaps ni pulsar
`Save`. El probe de transfers exige al menos un target explícito, quince picks, búsqueda,
controles de salida, ambos poderes y `Make Transfers`; observarlos no equivale a pulsarlos.

```bash
mova execute rehearsal-capability-probe \
  --source /var/lib/mova-fpl/artifacts/browser-probes/2026-27-gw03-pick-team.json \
  --cycle-id 2026-27-gw03 --capability lineup \
  --actor mova-operator --reason "DOM de lineup read-only conciliado" \
  --idempotency-key "rehearsal:2026-27:gw03:lineup:r2-2026.08.2"

deploy/bin/browser-session.sh probe-transfers 4,82,84 \
  > /var/lib/mova-fpl/artifacts/browser-probes/2026-27-gw03-r3.json
mova execute rehearsal-capability-probe \
  --source /var/lib/mova-fpl/artifacts/browser-probes/2026-27-gw03-r3.json \
  --cycle-id 2026-27-gw03 --capability r3 \
  --actor mova-operator --reason "superficie R3 read-only conciliada" \
  --idempotency-key "rehearsal:2026-27:gw03:r3:r3-2026.08.1"
deploy/bin/browser-session.sh stop
```

Estos ensayos prueban cobertura física de lectura y tamper resistance, no el commit. No cambian
`host_entrypoint_enabled`, `autonomy_promoted`, A0 ni controles. Las tres GWs son necesarias pero
no suficientes para promover una capacidad; la aprobación y el entrypoint siguen siendo gates
independientes. Para otras fuentes ya selladas se usa:

```bash
mova execute rehearsal \
  --file /var/lib/mova-fpl/artifacts/browser-rehearsals/2026-27-gw03-captaincy.json \
  --actor mova-operator \
  --reason "probe semántico read-only conciliado" \
  --idempotency-key "rehearsal:2026-27:gw03:captaincy:r2-2026.08.2"

curl -s http://127.0.0.1:8787/api/v1/browser-rehearsals?limit=20 | jq
curl -s http://127.0.0.1:8787/metrics | grep '^mova_browser_rehearsals'
```

El numerador de readiness es `COUNT(DISTINCT cycle_id)` por capacidad y versión contractual.
Un retry, una clave nueva o una segunda evidencia de la misma GW no aumenta el conteo. Los fallos
se conservan para auditoría pero no cuentan. Cambiar la versión del contrato reinicia su evidencia
efectiva; nunca se heredan rehearsals de un DOM/driver anterior.

`preflight` persiste evidencia y exige actor, razón y clave. Repetir la clave devuelve el mismo
plan. Una nueva observación usa una clave nueva y supersede el plan anterior, sin editar historia.
El import PostgreSQL shadow copia planes y checks como evidencia consultable; SQLite continúa
siendo el writer hasta el cutover general de HV1-02.

Desde HV1-07C cada tick que produce un `DecisionEnvelope` ejecuta también el preflight con una
clave derivada del envelope. Esto crea evidencia `blocked`, `noop` o `authorized`; nunca reclama
un lease ni inicia el navegador por sí solo.

## Lifecycle apply-once

```text
authorized plan
  → prepared
  → claimed (token opaco, lease 30..600 s)
  → applying  ← desde aquí todo fallo es write-ambiguous
  → verified | ambiguous
```

Los estados `failed`, `blocked` y `expired` sólo son terminales antes de `applying`. Un token se
guarda únicamente como SHA-256 y se entrega una vez; `begin`, `finalize` y `fail` lo leen por
`stdin`, nunca como argumento. Un segundo claim falla. Otro idempotency key no puede reservar el
mismo plan.

```bash
mova execute prepare \
  --plan-id execplan_... \
  --adapter browser \
  --actor mova-executor \
  --reason "R2 promovido y gates revalidados" \
  --idempotency-key "execution:2026-27:gw03:r2:01"

mova execute claim \
  --execution-id execution_... \
  --actor mova-executor \
  --reason "inicio del adapter"

printf '%s' "$CLAIM_TOKEN" | mova execute begin \
  --execution-id execution_... --pre-state /run/mova/pre-state.json \
  --actor mova-executor --reason "GET privado pre-write idéntico" \
  --claim-token-stdin

printf '%s' "$CLAIM_TOKEN" | mova execute finalize \
  --execution-id execution_... --post-state /run/mova/post-state.json \
  --actor mova-executor --reason "GET privado posterior al reload" \
  --claim-token-stdin
```

No guardar `CLAIM_TOKEN` en shell history, logs, artifacts ni PostgreSQL. El wrapper productivo
lo mantiene en memoria/pipe y borra los JSON temporales sanitizados al terminar.

`prepare` vuelve a validar deadline, estado privado, incidentes y controles. Además sella un
`browser-command-bundle-v1`. R2 contiene siete operaciones: pre-read, XI/banca, C, VC, commit,
reload y post-read. R3 añade staging exacto de transfers/chip, preview y una sola confirmación
irreversible. El contrato R3 existe, pero el adapter productivo sigue ausente: `prepare` con
`adapter=browser` lo bloquea y capabilities conserva el entrypoint apagado.

Después del claim, el host debe recolectar nuevamente el estado privado y el probe sanitizado.
El compilador no acepta un intento `prepared`, un lease vencido ni una versión DOM distinta:

```bash
mova execute ui-plan \
  --execution-id execution_... \
  --pre-state /run/mova/pre-state.json \
  --dom-probe /run/mova/dom-probe.json
```

El resultado sólo puede ser `ready` o `blocked`; compilarlo todavía no hace clicks. Liga cada
cambio de C/VC al índice posicional del jugador, abre su player sheet por
`button[data-pitch-element="true"]` y exige un checkbox con nombre accesible exacto `Captain` o
`Vice Captain`. El `begin` debe ocurrir después de esta compilación y de una última revalidación;
a partir de `applying`, cualquier incertidumbre se clasifica `ambiguous` y no se reintenta.

El wrapper host es el único entrypoint del driver promovido:

```bash
deploy/bin/execute-r2-browser.sh \
  --execution-id execution_... \
  --actor mova-executor \
  --reason "capitanía R2 promovida"
```

El wrapper reclama una sola vez, recoge pre-state/probe en un directorio `0700`, valida el plan
antes de `begin`, cruza explícitamente la frontera `applying`, ejecuta y finaliza contra un GET
privado posterior al reload. Antes de `begin`, el error termina `failed`; desde `begin`, termina
`ambiguous`, abre la reconciliación existente y nunca reintenta el commit. El proceso browser no
recibe el claim token. C/VC es el único scope habilitado por el entrypoint. XI/banca ya compila
una secuencia finita de pares `select_swap_origin/target`, reproduce el target por posición y
exige que los quince nombres observados queden en el orden esperado antes del commit. La
ejecución normal todavía devuelve `LINEUP_DRIVER_UNPROVEN`; sólo
`--validate-lineup-contract-only` compila ese stream y siempre termina antes de iniciar browser.
El nombre accesible del commit debe aparecer exactamente una vez tras el cambio local; si no,
`FPL_COMMIT_CONTROL_UNPROVEN` detiene la ejecución.

Para inspección R3 segura, el host acepta sólo una allowlist numérica de elementos objetivo y
emite estado sanitizado. Esta operación no hace clicks:

```bash
deploy/bin/browser-session.sh probe-transfers 572,610
deploy/bin/browser-session.sh stop
```

El resultado `mova-browser-transfer-dom-probe-v1` debe conciliar los quince picks autenticados,
controles visibles, targets del bootstrap, búsqueda, poderes y `Make Transfers`. La UI puede
duplicar `Remove player` entre pitch y tabla; el gate exige al menos quince, nunca exactamente
quince. El contrato host resultante sólo puede validarse offline:

```bash
deploy/bin/browser-r3-driver.py \
  --ui-plan /run/mova/r3-ui-plan.json \
  --validate-contract-only
```

No hay un comando `execute-r3-browser.sh`. Crearlo o habilitar R3 exige tres rehearsals
verificables, promoción explícita del capability y aprobación separada de controles A3.

## Riesgo y autoridad

| Riesgo | Acciones | Nivel mínimo |
| --- | --- | --- |
| R0 | diff vacío; lectura/no-op | A0 |
| R2 | XI, banca, capitán o vice | A2 |
| R3 | transfer, hit o chip | A3 |

Una acción solo queda `authorized` con: envelope staged, manifest ligado, team state válido,
fresco y sin cambio, fase entre preflight y execution window, deadline abierto, cero P0/P1, kill
switch apagado, browser writes habilitado, compliance aprobado, nivel suficiente, modo
`autonomous` y ausencia de ejecución previa. En `guarded` explicita aprobación humana pendiente y
permanece bloqueada.

`noop` nunca se envía al browser. `verified` exige que el GET privado posterior al reload
reconstruya exactamente el fingerprint de la decisión. Un mismatch queda `ambiguous`, abre un P0
y prohíbe retry automático. Transfers, hits y chips no tendrán un rollback automático ficticio.

`begin` vuelve a comparar el fingerprint del pre-state recién observado con el fingerprint
autorizado. `OBSERVED_PRE_STATE_CHANGED` termina el intento como `blocked` antes de `applying`;
no basta con que el snapshot persistido previo siga coincidiendo. El comportamiento de deriva DOM
y save ambiguo se ensaya sin browser con `mova drill browser-failure --actor ... --reason ...
--idempotency-key ...`.

## Recuperación

- `TEAM_STATE_FRESH` o `TEAM_STATE_FINGERPRINT_MATCH`: refrescar estado privado, regenerar
  manifest/envelope y usar una clave nueva.
- `EXECUTION_WINDOW`: esperar la fase; no alterar reloj ni phase persistido.
- `NO_OPEN_P0_P1`: resolver el incidente con evidencia antes de reintentar.
- gates de controles: cambiar controles solo mediante `mova control`, con actor y razón.
- hash inválido: bloquear, restaurar artifact/DB desde backup y verificar antes de decidir.

Rollout inicial: `shadow / A0`, `kill_switch=true`, `browser_writes=false`. Por tanto, un plan con
acciones debe quedar bloqueado; ese es el rehearsal seguro esperado.

## Observabilidad

- API: `/api/v1/execution-attempts`, `/api/v1/execution-attempt-events` y
  `/api/v1/browser-rehearsals`;
- Prometheus: `mova_execution_attempt_status`, `mova_execution_attempts_total` y
  `mova_browser_rehearsals{capability=...}`;
- SQLite migrations 010/016: intentos, transiciones y evidence ledger append-only;
- PostgreSQL shadow migrations 012/018: espejo consultable, nunca writer;
- artifacts: `execution-commands/<cycle>/` y `execution-evidence/<cycle>/`.

El snapshot accessibility vivo se valida por nombres accesibles y no por refs `@eN`, que son
efímeros. El contrato requiere sesión autenticada, deadline, cuatro chips y 15 controles
`Switch player`. Que el DOM pase este check sólo habilita el adapter a seguir validando; no
concede autoridad.

El probe estructurado se ejecuta desde el host y devuelve exclusivamente una allowlist
sanitizada. No incluye cookies, storage, perfil ni HTML crudo:

```bash
deploy/bin/browser-session.sh probe | jq
```

Cruza los 15 picks del GET autenticado con los 15 slots visibles y sus nombres de jugador. La
secuencia de lineup se calcula como swaps posicionales mínimos sobre
`button[aria-label="Switch player"]`; antes de cualquier acción, el orden DOM debe ser idéntico al
pre-state. El probe abre y cierra, sin seleccionar, los player sheets de los once titulares y
comprueba los checkboxes semánticos C/VC. También exige exactamente un capitán y un vice, ambos
idénticos al GET privado. Si falta cualquier control o existe deriva, el UI action plan queda
`blocked` con `CAPTAIN_CONTROL_UNPROVEN` o `VICE_CAPTAIN_CONTROL_UNPROVEN`, o falla cerrado por
pre-state mismatch. El driver host puede materializar C/VC. El stream de lineup puede validarse
sin navegador, pero el entrypoint real lo rechaza. Faltan los rehearsals controlados del commit y
de lineup, y A0 bloquea toda ejecución real.

`mova execute status` expone capacidades y evidencia reciente sin secretos: contrato, versión,
entrypoint, autonomía y GWs distintas observadas/requeridas para captaincy, lineup y R3. En el
corte actual captaincy tiene entrypoint pero autonomía no promovida; lineup y R3 tienen contrato
implementado, entrypoint deshabilitado y el conteo durable parte de `0/3` hasta importar evidencia
real. Ninguno de estos contadores cambia controles ni promueve autonomía.
