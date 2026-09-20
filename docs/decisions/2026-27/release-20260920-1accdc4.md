---
type: release-evidence
name: "MOVA FPL — release recuperada 1accdc4"
created: 2026-09-20
updated: 2026-09-20
tags: [mova, fpl, release, recovery, research]
status: observed
---

# Release 1accdc4 — 20 de septiembre de 2026

## Alcance y procedencia

El commit `1accdc447bb9a492d3a6c11662e21b52e90d574d` tiene como padres
`c86e76e` (PR #170) y `a8cfa7d` (checkout previo del VPS). Integra los tres commits
locales de recuperación del host, versiona los dos scripts de captura privada que
seguían modificados en ese checkout y conserva el `compose.override.yaml` local sin
agregarlo a Git. Los hashes de ambos scripts desplegados coincidían byte a byte con
el commit antes y después del checkout. El Git stash `pre-release-hotfixes-20260920`
conserva además el parche anterior en el host.

La release añade pistas acotadas de fuentes verificadas para la siguiente corrida
de research y un desglose de cobertura por club en futuros briefs v2. No cambia el
gate 90/80, el presupuesto, modelos, autoridad ni escrituras FPL. Una pareja real
`broad → refresh/final` todavía no ha ejercido esta mejora; no se atribuye ahorro
ni una GW passing.

## Punto de retorno y artefactos

- Checkout anterior: `a8cfa7d5d8f4c4d7a0e2529e624fefbd59967d99`.
- Backup operativo pre-release: `/opt/orbital/backups/mova-fpl/20260920T213544Z`,
  job `job_a8595a082042478f98a28f57e3959aa9`, completado.
- Copia root-only de `deploy.env`, `compose.override.yaml` y scripts host:
  `/opt/orbital/backups/mova-fpl/release-20260920T2136Z-1accdc4/` (directorio 0700).
- Imagen engine `1accdc4`: `sha256:6746ec92bcedc5fb5110118f61c2b554d9d8c15804f8c89f2bbae0c4db7a39e2`.
- Imagen browser `1accdc4`: `sha256:f680e61ac5024fb7d05890f8eff37df2b08ddbd98fce78c18e4cd25755c82635`.
- Imagen research `1accdc4`: `sha256:4e7a476b4e2d489822478591402f3e802538651406af4369441897ca80accee3`.
- Imágenes anteriores `a8cfa7d` conservadas localmente. No se ejecutó un rollback
  disruptivo: la recuperación efectiva todavía debe probarse en una ventana aparte.

El rollback técnico consiste en restaurar el `deploy.env` respaldado, cambiar el
checkout a `a8cfa7d`, restaurar los dos scripts host respaldados y recrear API y
browser con Compose y la etiqueta anterior. Verificar `/readyz`, sesión privada y
doctor antes de declarar recuperación. El backup de datos sólo se restaura ante
necesidad de datos; revertir código no justifica sobreescribir el writer actual.

## Verificación ejecutada

En worktree limpio de release: `1757 passed, 1 skipped, 79 deselected`,
`compileall`, `node --check`, `bash -n`, `docker compose config --quiet` y
`git diff --check`; CI de PR #170 pasó. En el VPS, checkout, `MOVA_GIT_SHA`,
`MOVA_IMAGE_TAG` y API/browser coinciden en `1accdc4`. Se construyeron las tres
imágenes y el módulo del worker research pasó `node --check` dentro de su imagen
sin red ni credenciales montadas.

Tras recrear browser con su perfil persistente, una captura forzada de solo lectura
se ingirió como `job_7fd374caca344a1eaf47cd9d09f2449b`: equipo `3609854`,
15 jugadores, ciclo GW6 y calidad aceptada. El doctor del 20/09 21:40:06 UTC
dio `healthy`, 24 PASS, 0 WARN y 0 FAIL, con checkout/imagen `1accdc4`.
El tick posterior terminó `success`; reutilizó idempotentemente el job completado
del slot, sin abrir trabajo duplicado. API `/readyz` respondió `ready`, Caddy validó,
la página pública devolvió 200 y `/api/v1/cockpit` externo devolvió 404.
`mova strategy prepare` selló un manifiesto GW6 con 25 sujetos y cero pistas heredadas
(no existe todavía un brief de ese ciclo); `research due` confirmó
`outside_research_window`, sin iniciar agente. El timer privado ejecutó dos
veces más con `snapshot_fresh` y sin relanzar Chromium.

El corte de las 21:50:51 UTC repitió doctor `healthy`, 24 PASS, 0 WARN, 0 FAIL;
la cola agentic informó cero anomalías y cero requests huérfanos. Los ticks
programados de las 21:45 y 21:50 terminaron con exit 0 y jobs completos; ambos
omitieron refresh por cadencia, lo cual prueba continuidad del scheduler, no una
nueva captura pública. A las 21:50, API usaba ~154 MiB/512 MiB y browser
~624 MiB/1.22 GiB; ambos contenedores estaban healthy. Esta observación de
~13 minutos no sustituye la ventana prolongada de AC-01.2.

## Observación pendiente

La release conserva A0/shadow, kill switch activo, `browser_writes=false` y
compliance pendiente. Se deben observar ciclos posteriores de tick, collector,
analytics y research; una ejecución `skipped_cadence` o `reused` no prueba una
recolección completa. AC-01 todavía requiere la ventana definida de estabilidad
y un ensayo de rollback; AC-02 requiere cobertura real posterior a esta release.
