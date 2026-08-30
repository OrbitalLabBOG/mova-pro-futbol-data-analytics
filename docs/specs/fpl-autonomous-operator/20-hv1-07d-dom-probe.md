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

## Verificación

- pruebas focalizadas del executor y planner: 12 aprobadas;
- suite completa: 898 passed, 1 skipped, 79 deselected;
- `node --check`, compileall y `docker compose config`: aprobados.

La espera del host usa la condición funcional `my-team + 15 switch controls`; no espera
`domcontentloaded`/`networkidle`, porque recursos publicitarios de terceros pueden mantener esos
eventos abiertos aunque la superficie FPL ya esté lista.

El corte productivo quedó en `edb2e0a`, con checkout e imágenes engine/browser coincidentes. El
probe autenticado observado a las `2026-08-30T17:02:28.541Z` terminó `pass` para `team_id=3609854`:

- sesión autenticada;
- 15 picks del API;
- 15 player controls visibles;
- 15 switch controls visibles;
- orden posicional y `web_name` coincidentes en los 15 slots.

El payload fue revisado y contiene únicamente la allowlist documentada. Después del probe, el
browser terminó `Exited (0)` y noVNC quedó detenido. API lista, siete timers activos, doctor 22
PASS / 0 WARN / 0 FAIL y controles sin cambios: shadow/A0, compliance pending, kill switch activo
y browser writes false. No se creó execution attempt ni se realizó un rehearsal de escritura.
