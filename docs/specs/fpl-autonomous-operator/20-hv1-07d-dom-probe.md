---
type: evidence
name: "MOVA FPL — corte HV1-07D DOM probe y swap planner"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, browser, dom, r2, guardrails]
status: verified
---

# HV1-07D: DOM probe y planner R2

## Alcance

Este corte conecta el contrato browser con el estado autenticado sin ampliar autoridad. El probe
se ejecuta dentro del browser aislado, usa la sesión sólo para un GET privado y devuelve una
allowlist: team id, timestamp, checks, quince slots y la matriz sanitizada de controles C/VC de
los once titulares. Cookies, tokens, storage, HTML y datos del perfil no cruzan la frontera.

El planner puro recibe tres artifacts: command bundle sellado, pre-state validado y probe DOM.
Exige versiones exactas, team id correcto, 15 slots y orden idéntico. Luego calcula una secuencia
determinista de swaps posicionales sobre un selector estable, nunca refs `@eN`.

## Subcorte 2026.08.2

La observación viva confirmó `button[aria-label="Switch player"]`, el orden estable de sus quince
slots y el player sheet de cada titular. Cada sheet expone checkboxes accesibles `Captain` y
`Vice Captain`; el probe sólo abre, observa y cierra, nunca cambia sus valores. Además concilia
exactamente un C/VC con los flags del GET privado. Por eso:

- cambios de XI/banca y C/VC pueden producir un UI action plan `ready` si toda la matriz pasa;
- ausencia de un sheet, checkbox o selección coherente falla cerrado;
- `mova execute ui-plan` sólo opera sobre un intento `claimed` con lease vigente;
- `Confirm My Choices` queda deshabilitado si hay blockers;
- no existe en este corte un comando que haga clicks ni un timer executor;
- Compose conserva browser writes en cero y A0/shadow continúa vigente.

## Verificación

- pruebas focalizadas del executor y planner: 15 aprobadas;
- suite completa inicial: 930 passed, 1 skipped, 79 deselected;
- `node --check`, compileall y `docker compose config`: aprobados.

La espera del host usa la condición funcional `my-team + 15 switch controls`; no espera
`domcontentloaded`/`networkidle`, porque recursos publicitarios de terceros pueden mantener esos
eventos abiertos aunque la superficie FPL ya esté lista.

El probe ampliado se ejecutó contra la sesión productiva a las
`2026-08-30T18:31:34.571Z` y terminó `pass` para `team_id=3609854`:

- sesión autenticada;
- 15 picks del API;
- 15 player controls visibles;
- 15 switch controls visibles;
- orden posicional y `web_name` coincidentes en los 15 slots.
- 11 player sheets de titulares con ambos checkboxes semánticos;
- exactamente un capitán y un vice, conciliados con el GET autenticado.

El payload contiene únicamente la allowlist documentada. No se creó execution attempt ni se
realizó un rehearsal de escritura. Los controles permanecen shadow/A0, compliance pending, kill
switch activo y browser writes false. Falta materializar el driver host apply-once y completar
tres rehearsals controlados antes de considerar cualquier elevación de autoridad.

## Rollout

El subcorte quedó desplegado en `d52ce89`, con checkout e imagen engine coincidentes. El probe
ejecutado desde la imagen browser ya desplegada volvió a pasar a las
`2026-08-30T18:41:46.994Z`; después se detuvo el browser con salida limpia. `mova doctor` reportó
22 PASS, 0 WARN y 0 FAIL; los seis timers operativos consultados continuaron activos. Backups
posteriores: SQLite `20260830T184302Z` y PostgreSQL `20260830T184303Z`.

## Hardening del colector autenticado

La verificación posterior encontró que `collect` abría la portada de FPL y dependía de una
redirección implícita hacia `/en/my-team`. Esa redirección dejó de ser determinista: el browser
podía estar sano y autenticado, pero el gate de 15 controles expiraba en la ruta equivocada.
El hotfix `039aeeb` hace explícita la navegación a `/en/my-team` y agrega un contrato de
regresión que exige ruta, pathname y los 15 controles `Switch player`.

El cambio quedó desplegado como revisión VPS `78d58c3`. La captura read-only posterior terminó
en un intento limpio con 15 jugadores, 2 transferencias libres, los cuatro chips disponibles y
artefacto versionado; el browser volvió a estado detenido. La suite final reportó 931 passed,
1 skipped y 79 deselected. Checkout, tag y label OCI quedaron conciliados en `78d58c3`;
`mova doctor` cerró con 22 PASS, 0 WARN y 0 FAIL, siete timers programados y cero unidades
fallidas.

## Subcorte HV1-07D.3: driver host captaincy-only

El corte `a330860`, desplegado en el VPS como `c854b10`, conecta el UI action plan con un
orquestador host apply-once sin ampliar autoridad. La separación es explícita:

- `mova_fpl.ops.browser_driver` compila un instruction stream puro y finito;
- `browser-r2-driver.py` materializa únicamente checkboxes semánticos de C/VC;
- `execute-r2-browser.sh` posee el lifecycle claim/begin/finalize y nunca entrega el token al
  proceso browser;
- pre-state, probe, plan y post-state viven temporalmente bajo `/run` con `umask 077` y se borran
  al salir;
- antes de `begin`, un fallo termina `failed`; después de la frontera apply termina `ambiguous` y
  no se reintenta;
- cualquier swap de XI/banca falla con `LINEUP_DRIVER_UNPROVEN`; R3 continúa sin adapter;
- el commit exige un único botón con nombre accesible exacto y conserva `max_clicks=1`.

La integración host simulada verificó exactamente un `claim`, un `begin`, un `finalize`, dos
capturas privadas y limpieza completa, sin token en argumentos ni logs. La suite completa cerró
con **946 passed, 1 skipped y 79 deselected**; shell syntax, compileall, Compose y `diff --check`
también pasaron.

El rehearsal del VPS fue exclusivamente `--validate-only` sobre un fixture sanitizado: produjo
schema `mova-browser-r2-driver-plan-v1`, scope `captaincy_only`, nueve pasos, un solo commit y
`retry_after_commit=false`. No inició Chromium, no reclamó un execution attempt y el endpoint
continuó con `items=[]`.

Después del despliegue:

- checkout, engine label y browser label coincidieron en `c854b10`;
- `mova doctor`: 22 PASS, 0 WARN, 0 FAIL;
- API y PostgreSQL healthy, siete timers activos y cero unidades fallidas;
- browser detenido;
- `shadow/A0`, compliance pending, kill switch activo y browser writes false;
- rebuild inmediato del browser: 0 s y siete pasos cacheados después de mover el SHA debajo de la
  capa pesada.

Este corte no prueba todavía el botón real posterior a una mutación local: sin cambios pendientes
la UI no renderiza el commit. Probarlo exige una operación controlada incompatible con A0. Por eso
HV1-07 permanece parcial: faltan rehearsal de confirmación, rehearsal de lineup y la elevación de
autoridad bajo un gate explícito.

## Subcorte HV1-07D.4: adapter lineup tipado, no promovido

El planner existente ya demostraba la secuencia mínima de swaps; este subcorte completa el lado
host sin habilitarlo. El compiler valida schema, posiciones, selector allowlisted, secuencia,
replay exacto y las quince identidades visuales ligadas al probe inicial. El instruction stream:

1. selecciona origen y destino de cada swap por índice posicional;
2. exige exactamente quince controles antes de cada selección;
3. verifica el orden visual completo contra los `web_name` observados;
4. descubre exactamente un `Confirm My Choices`;
5. conserva un solo commit, sin retry, reload y GET privado posterior.

El modo productivo no puede compilar swaps y devuelve `LINEUP_DRIVER_UNPROVEN`. El único bypass
es `--validate-lineup-contract-only`, cuyo código retorna el JSON compilado antes de construir un
cliente browser. La capability publicada registra lineup `implemented`, entrypoint deshabilitado,
autonomía no promovida y `0/3` rehearsals. R3 continúa ausente.

Verificación local: 38 pruebas enfocadas; replay/selector/labels manipulados fallan cerrados;
materialización completa contra browser falso; `970 passed, 1 skipped, 79 deselected`; compileall,
shell syntax, Compose y `diff --check` aprobados. No se creó intento, no se inició browser y no se
escribió en FPL.

El rollout inicial quedó en `baf76c2`, desplegado como `c73e4109`. El smoke del VPS reprodujo
un plan lineup de siete pasos y un solo commit en modo de contrato; el mismo payload por el path
normal terminó `LINEUP_DRIVER_UNPROVEN`. `mova execute status` publicó el ledger esperado;
`mova doctor` cerró 22/0/0, API healthy, ocho timers, cero unidades fallidas, checkout/imagen
coincidentes y browser detenido. Los controles continuaron `shadow/A0`, compliance pending, kill
switch activo y browser writes false.
