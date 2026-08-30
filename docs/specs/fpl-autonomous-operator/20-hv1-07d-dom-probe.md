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
- suite completa: 930 passed, 1 skipped, 79 deselected;
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
