---
type: release-evidence
name: "MOVA FPL — Researcher contextual y radar global"
created: 2026-09-20
updated: 2026-09-20
tags: [mova, fpl, research, release, evidence]
status: observed
---

# Researcher contextual — 20 de septiembre de 2026

## Alcance instalado en A0/shadow

El manifest de research sella plan estratégico, los 15 propios con proyecciones
resueltas por ID, diez candidatos, 667 IDs del catálogo FPL, 50 fixtures y hasta
80 alertas globales. Incluye pistas de señales de las tres GWs anteriores, sin
tratarlas como evidencia. La request, el resultado, la cobertura, el costo y los
receipts físicos quedan enlazados por hashes. El worker puede explorar fuera del
foco, pero el importador solo acepta un claim si su identidad, tema, fuente y
fecha verificable satisfacen la política sellada. `2026.09.2` añade vigencia por
tipo de claim y evita que una alineación histórica se presente como rol actual.
Los plugins y la búsqueda de skills del host se desactivan en el Codex aislado.

No se modificaron permisos FPL, modelo, decisiones, controles A0/shadow ni el
gate 90/80. La cadencia normal sigue automática por timer; una ejecución fuera
de ventana exige actor, razón e idempotency key.

## Evidencia de la primera corrida real

La excepción auditada `research:gw06:global-refactor-20260920` produjo
`research_73c7968ad6c2c3c71c4fc22fc7515a6d` con request de 63.465 bytes y
política `2026.09.1`. Importó seis documentos, ocho señales y un conflicto;
solo dos señales fueron aceptadas, seis quedaron candidatas. La cobertura
verificada fue 3/25 (12 %): tres propios y ningún candidato del modelo.
El texto del agente decía 9/25, pero el contador determinista lo corrigió a 3/25.
Una fuente del 5/09 sobre titularidad habría pasado `2026.09.1`; motivó el
endurecimiento `2026.09.2`. No se reescribe la evidencia histórica del run.

La llamada reportó 246.505 tokens de entrada y 7.074 de salida en 162,3 segundos:
253.579 en total, 93.579 por encima del límite por job de 160.000. La reserva
`budget_84eab76009624c2ddda2b674` se liquidó con el consumo real. El Codex CLI
solo publica el conteo al final: preautorización, timeout y prompt **no** son un
freno físico exacto de tokens. El overrun permanece abierto hasta una revisión
durable y una corrida posterior comparable dentro del límite; no se cambia el
límite para ocultarlo. La desactivación de plugins/skills es una mitigación de
contexto, aún sin ahorro cuantificado en vivo.

## Despliegue y retorno

La primera revisión viva fue `5e64ddc`: checkout, etiqueta de engine/research y
API coincidieron; `/readyz` respondió `ready`, la imagen research pasó
`node --check`, y la request real se autorizó/importó. Backups previos:
SQLite `/opt/orbital/backups/mova-fpl/20260920T231320Z` (job
`job_4e172d693b314c3dbe266371f01efea7`), PostgreSQL
`/opt/orbital/backups/mova-fpl/postgres/20260920T231324Z` y configuración
root-only `/opt/orbital/backups/mova-fpl/research-release-20260920-d8416fe/`.
El punto de código anterior era `1accdc4`. Revertir código no justifica restaurar
el writer de datos.

La segunda revisión aplica vigencia por claim y elimina contexto de plugins.
Su SHA, pruebas y salud viva se registran en la bitácora de release al verificar
el despliegue. No se ejecuta otra corrida forzada solo para consumir tokens:
GW6 aún está fuera de la ventana ordinaria y GW5 no tiene cierre oficial
`finished/data_checked` en el corte observado. La próxima corrida comparable
debe medir cobertura, señales globales y tokens bajo `2026.09.2`.

## Gates pendientes

AC-02 no pasa con 12 % de cobertura y un overrun. Hacen falta tres GWs
independientes con los umbrales vigentes, evidencia causal y costo controlado.
La promoción de autoridad A1 y escrituras FPL además requiere la aprobación
técnica de Nicolás y el gate de cumplimiento. Hasta entonces la release es
operativa en A0/shadow, no autónoma para ejecutar cambios de equipo.
