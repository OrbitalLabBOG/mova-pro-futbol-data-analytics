---
type: evidence
name: "HV1-06A — DecisionEnvelope y Validator determinista"
created: 2026-08-28
updated: 2026-08-28
tags: [mova, fpl, harness, decision-envelope, validation]
status: verified_local
---

# HV1-06A — evidencia de implementación

## Problema observado

El tick almacenaba xP, chip y fingerprint extrayéndolos del Markdown. El campo
`decision_runs.manifest_sha256` recibía el hash del acta y no el hash semántico del
`CycleManifest`. Además, una propuesta GW3 con Wildcard y 12 movimientos podía quedar `staged`
aunque la GW2 no estuviera asentada y no existiera proyección causal para GW3.

## Corte aplicado

- bundle JSON determinista desde el mismo `decide()` productivo;
- tres escenarios obligatorios: estado observado, baseline y alternativa;
- once checks tipados con severidad y códigos estables;
- persistencia transaccional e idempotente del envelope, candidatos, 15 jugadores y checks;
- hash real del manifest en `decision_runs.manifest_sha256`;
- estados `blocked/staged/superseded`, sin autoridad browser;
- mirror PostgreSQL aditivo, endpoints read-only y métricas Prometheus;
- semántica de hits unificada como cantidad de transferencias pagadas, descontando cuatro puntos
  por cada una bajo las reglas vigentes.

## Verificación local

```text
pytest -q
852 passed, 1 skipped, 79 deselected
```

Casos explícitos:

- mismos inputs producen exactamente el mismo envelope y SHA;
- GW previa no asentada + analytics ausente + acción irreversible produce `blocked`;
- un ciclo listo en `preflight` produce `staged`;
- la persistencia repetida reutiliza el mismo envelope;
- candidatos=3, jugadores=15 y checks=11;
- `1 hit` liquida `−4 puntos`, no `−1`.

## Estado de rollout

La evidencia viva del VPS, SHA desplegado, migraciones aplicadas y resultado de `doctor` se añade
después del rollout. Hasta entonces el corte permanece `verified_local`.
