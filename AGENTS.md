# AGENTS.md — MOVA Fantasy Fútbol

Este repositorio es la fuente técnica del operador FPL de MOVA. Su única superficie viva es
`mova_fpl/`; no reconstruyas ni importes el motor histórico retirado.

## Orientación

- Arquitectura vigente: `docs/architecture/decision-engine.md`.
- Operación por jornada: `docs/operations/gameweek.md`.
- Control plane del VPS: `docs/operations/vps.md`.
- Hoja de ruta del harness: `docs/specs/fpl-autonomous-operator/10-autonomous-harness-v1.md`.
- Decisiones de temporada: `decisions/fpl/<season>/`.

Lee solo el documento necesario para la tarea. El código, schemas y controles desplegados
ganan frente a cifras o planes históricos.

## Invariantes

1. Todo dato analítico temporal entra por `Store.as_of(season, gw)`; no desactives su
   verificación causal.
2. `mova_fpl.engine.runner.decide()` es el único punto de decisión para vivo y backtest.
3. El engine no escribe en FPL. El browser es un executor aislado y cualquier mutación exige
   gates, decisión sellada y verificación posterior.
4. El planificador autoriza chips y el optimizador ejecuta; no mezcles esas autoridades.
5. El agente modifica entradas acotadas, nunca fuerza plantilla, XI o capitán por fuera del
   optimizador.
6. Bases, cookies, modelos binarios, logs y outputs viven fuera de Git. Versiona manifests,
   hashes y actas textuales sin secretos.
7. Supabase es PM-only. La operación y sus datos viven en el VPS.

## Desarrollo

Instala con `python -m pip install -e '.[test]'` y ejecuta `pytest -q`. Este gate debe pasar
desde un clone limpio. Las pruebas `integration_data` requieren ingesta y modelos locales;
las `slow` recorren temporadas completas.

Antes de cambiar fronteras, consulta `tests/test_architecture_boundaries.py`,
`tests/test_readonly_http.py`, `tests/test_no_secrets.py` y
`tests/test_repository_hygiene.py`. Después de un cambio ejecuta la prueba más cercana y el
gate hermético completo.

El deploy usa `compose.yaml`, `deploy/docker/` y `deploy/systemd/`. No edites secretos ni
perfiles autenticados; los ejemplos de entorno son contratos, no valores productivos.

## Legado

El estado anterior a la limpieza está sellado en
`archive/pre-harness-cleanup-2026-08-23`. Consultarlo no autoriza copiar código al producto.
Los scripts FPL históricos contienen leakage estructural documentado; una idea solo vuelve
si se reimplementa causalmente dentro de las fronteras vigentes y con pruebas.
