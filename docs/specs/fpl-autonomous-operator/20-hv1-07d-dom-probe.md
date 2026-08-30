---
type: evidence
name: "MOVA FPL — corte HV1-07D DOM probe y swap planner"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, browser, dom, r2, guardrails]
status: candidate
---

# HV1-07D: DOM probe y planner R2

## Alcance

Este corte conecta el contrato browser con el estado autenticado sin ampliar autoridad. El probe
se ejecuta dentro del browser aislado, usa la sesión sólo para un GET privado y devuelve una
allowlist: team id, timestamp, checks y quince slots `{position, element, web_name, indexes,
label_matches}`. Cookies, tokens, storage, HTML y datos del perfil no cruzan la frontera.

El planner puro recibe tres artifacts: command bundle sellado, pre-state validado y probe DOM.
Exige versiones exactas, team id correcto, 15 slots y orden idéntico. Luego calcula una secuencia
determinista de swaps posicionales sobre un selector estable, nunca refs `@eN`.

## Frontera de seguridad

La observación viva confirmó `button[aria-label="Switch player"]` y el orden estable de sus
quince slots. No confirmó aún controles semánticos estables para capitán y vice. Por eso:

- cambios sólo de XI/banca pueden producir un UI action plan `ready`;
- un cambio de C/VC produce `blocked`;
- `Confirm My Choices` queda deshabilitado si hay blockers;
- no existe en este corte un comando que haga clicks ni un timer executor;
- Compose conserva browser writes en cero y A0/shadow continúa vigente.

## Verificación candidata

- pruebas focalizadas del executor y planner: 12 aprobadas;
- suite completa: 898 passed, 1 skipped, 79 deselected;
- `node --check`, compileall y `docker compose config`: aprobados.

La espera del host usa la condición funcional `my-team + 15 switch controls`; no espera
`domcontentloaded`/`networkidle`, porque recursos publicitarios de terceros pueden mantener esos
eventos abiertos aunque la superficie FPL ya esté lista.

El estado de esta acta pasa a `verified` únicamente después de construir la imagen browser en el
VPS, ejecutar un probe autenticado `pass`, revisar que el payload sea sanitizado y volver a
detener el browser. Eso tampoco equivale a un rehearsal de escritura.
