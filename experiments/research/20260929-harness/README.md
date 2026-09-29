---
type: experiment
name: MOVA harness integrity — offline research corpus and regression evidence
created: 2026-09-29
status: implementation-validation
---

# Integridad del harness y laboratorio offline

Base: 6caf461 (código runtime e903983 más acta de despliegue). Rama:
`codex/mova-harness-integrity-20260929`. El worktree original conserva sus cambios previos.

`sources.json` contiene seis extractos de la corrida
`research_96ecea3c56544f9e08c6d0e3910922e7`. Se consultó el endpoint oficial de documentos y
se verificó el SHA256 de cada artifact físico antes de extraer texto/metadata pública.
La marca de fecha verificada proviene del artifact; published_at/observed_at/tier del
registro operativo. No se volvió a descargar web ni se incluyeron credenciales o estados
privados. `corpus.json` sella el hash del conjunto, corte, sujetos extraídos del catálogo original y ocho etiquetas
revisables: rol oficial, banco, claim médico insuficiente, antigüedad, captura posterior,
reporte secundario sin corroboración, conflicto explícito y sujeto no mencionado.

```bash
python -m experiments.research.replay_corpus experiments/research/20260929-harness
pytest -q
python -m compileall -q mova_fpl
docker compose config --quiet
node --check deploy/research/codex-worker.mjs
```

El replay reutiliza los validadores productivos y rechaza cambios de hashes. Ocho casos y
el check de silencio pasan; red/LLM/runtime mutations = 0. Las etiquetas de conflicto se
aportan como inputs; no se pretende resolver automáticamente cronología ni validar
semántica completa. La captura histórica no se mueve para fingir disponibilidad predeadline.

1.11.0 está registrada para experimentar, con el mismo modelo, calidad, scope y guard que
1.10.0, cambiando sólo la agenda de cobertura. Sigue activa 1.10.0. La comparación online
pendiente requiere dos brazos equivalentes de hasta 1M cada uno y presupuesto disponible
tras conservar capacidad operativa. Snapshot 2026-09-29 03:11 UTC: 2.310.934 tokens GW;
par de 2M dejaría 310.934, por lo que no se ejecutó ni amplió capacidad.

El conjunto de regresiones incluye chips/vice/autosubs/hits, p60 faltante, financiación
observada y contrafactual, banco/precios/corte falsificados, wildcard y Free Hit pendiente;
ventanas, dependencias, revisión sin hipótesis y contradicciones; presupuesto/consumo/
contexto incompatibles; DOM de XI alterado/ausente, commit ambiguo, respuesta tardía y
leases inválidos/expirados. Estos contratos no acreditan una escritura real ni una GW nueva.

Los resultados finales de suite y smoke se registran en `validation.json`.
