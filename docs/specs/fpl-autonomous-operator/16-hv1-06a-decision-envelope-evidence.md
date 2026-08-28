---
type: evidence
name: "HV1-06A — DecisionEnvelope y Validator determinista"
created: 2026-08-28
updated: 2026-08-28
tags: [mova, fpl, harness, decision-envelope, validation]
status: deployed_verified
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

## Rollout verificado en VPS

| Evidencia | Resultado |
| --- | --- |
| Implementación versionada | `0de0aeb` |
| Implementación desplegada | `19e1986` |
| SQLite | migration 007 aplicada; `quick_check=ok` |
| PostgreSQL 17 shadow | migration 008 aplicada; import y verify `pass` |
| Mirror nuevo | 1 envelope, 3 candidatos, 11 checks |
| Doctor con red | 22 PASS, 0 WARN, 0 FAIL |
| Status | `healthy`, sin incidentes ni jobs fallidos en 24 h |

La corrida forzada `force:hv1-06a:gw03:19e1986` usó el estado autenticado de 15 jugadores,
2 FTs, manifest `e0de5f…c271` y los modelos 1.1.0. La salida del baseline conservó la propuesta
WildCard de 12 movimientos y 51,19 xP para poder medirla, pero el envelope
`12ef9f…f7b8a` quedó correctamente `blocked` por:

1. `PRIOR_GAMEWEEK_SETTLED`: GW2 seguía sin asentarse y aún había partidos sin iniciar;
2. `ANALYTICS_APPROVED_CAUSAL`: todavía no existía batch aprobado para GW3;
3. `IRREVERSIBLE_ACTION_WINDOW`: el ciclo estaba en `baseline`, fuera de ventana operativa.

El tick terminó `completed`, no degradado: bloquear una propuesta inmadura es el resultado sano.
La API devolvió los tres candidatos y once checks; Prometheus publicó
`mova_decision_envelope_status{status="blocked"}=1` y `mova_decision_blocking_checks=3`.
No hubo escrituras browser ni cambio de autonomía: `shadow/A0`, kill switch activo.
