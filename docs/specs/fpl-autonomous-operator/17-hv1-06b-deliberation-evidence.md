---
type: evidence
name: "HV1-06B — Strategist y Critic acotados"
created: 2026-08-28
updated: 2026-08-28
tags: [mova, fpl, harness, strategist, critic, deliberation, shadow]
status: deployed_verified
---

# HV1-06B — evidencia de implementación

## Resultado

El harness ya puede interpretar un `DecisionEnvelope` con dos roles LLM acotados sin delegarles
la construcción de plantillas ni autoridad sobre FPL. Strategist compara exactamente
`do_nothing`, `milp_baseline` y `primary_alternative`; Critic preserva los hard blockers y emite
un veredicto. La única salida accionable futura es un `Intervention` validado, que en este corte se
normaliza siempre como `shadow_only=true` y `applied=false`.

## Corte aplicado

- contrato request/result versionado y JSON Schema compatible con Structured Outputs;
- un solo worker Codex one-shot para research o deliberación, con prompts y capacidades
  separados; deliberación no recibe web search, DB, navegador, shell ni delegación;
- allowlist de jugadores, multiplicadores `0..1.5`, máximo 12 ajustes, chips, locks y riesgo;
- obligación de conservar cada blocker determinista con el mismo código y severidad;
- estados `queued`, `accepted`, `review_required`, `blocked`, `rejected` y `failed`;
- persistencia append-only de deliberación, riesgos, uso, hashes y artefactos;
- SQLite migration 008 y PostgreSQL migration 009;
- CLI `mova strategy deliberate status|enqueue|import`, API read-only y métricas Prometheus;
- una sola request por activación del timer para limitar concurrencia y gasto.

## Verificación local

```text
pytest -q
867 passed, 1 skipped, 79 deselected
```

La suite cubre identidad y hashes, cobertura exacta de candidatos, jugadores desconocidos,
multiplicadores, chips, locks, blockers omitidos, cuarentena, persistencia idempotente, métricas,
contrato del worker y serialización de timestamps tipados por SQLite.

## Ensayos vivos y correcciones

La primera deliberación (`deliberation_c58affd27c31fc776e5ed5cc64bc5d9a`) demostró el flujo
end-to-end y quedó `blocked`, pero Critic señaló `BUDGET` en `do_nothing`: el plantel costaba
£100.3M a precio actual. La evidencia no se editó. La auditoría confirmó que era un falso
positivo: FPL permite esa apreciación y el equipo conservaba banco no negativo.

Se reemplazó esa comprobación por conciliación financiera reproducible:

```text
banco esperado = banco previo + ventas a precio FPL − compras a precio actual
```

`free_hit` usa valor liquidable de plantilla + banco; cold start usa el presupuesto inicial. El
validador también compara el diff real de elementos con las transferencias declaradas. Durante
el replay, un `datetime` devuelto por SQLite expuso un segundo borde: el envelope se normalizó a
valores JSON antes de hashearlo y persistirlo. Ambos fallos quedaron en jobs/incidentes como
evidencia; ninguno tocó FPL.

La corrida corregida produjo:

| Evidencia | Resultado |
| --- | --- |
| Checkout/imagen VPS | `891ac38` / `891ac38` |
| Job | `job_5d9fa06455b04ec0994faef53aca45b7`, completed |
| Manifest | `manifest_3ec188d7459e4f3086f37e5317d410be`, revision 4 |
| Envelope | `envelope_78147b987e065d751a5178c1`, blocked |
| Deliberation | `deliberation_a77107877ab802a9242c2b193ed3ab48`, blocked |
| Candidato preferido | `primary_alternative` |
| Critic | `block`, confianza 0.93 |
| Intervention | hash `44899f79…d1dcce`, `applied=false` |
| Uso | GPT-5.4, 14.763 input + 2.121 output tokens, suscripción ChatGPT |

Los tres candidatos quedaron sin violaciones del engine:

- `do_nothing`: £100.3M de valor actual y £0.0M de banco, legal;
- `milp_baseline`: wildcard, £97.4M y £2.6M de banco;
- `primary_alternative`: sin chip, £95.2M y £5.0M de banco.

El envelope quedó bloqueado únicamente por `PRIOR_GAMEWEEK_SETTLED` e
`IRREVERSIBLE_ACTION_WINDOW`. Critic conservó ambos y añadió tres advertencias estratégicas; ya
no existe el riesgo espurio `BUDGET`. Prometheus reportó `blocked=1` y dos riesgos bloqueantes.

## Persistencia, salud y rollback

La API expuso dos deliberaciones históricas y nueve riesgos. El import PostgreSQL
`pgimport_a75af942e1244958bd5b18fddf1ac4ee` terminó y verificó todos los targets: dos
deliberaciones y nueve riesgos coinciden entre SQLite writer y PostgreSQL shadow.

`mova doctor --json` cerró con 22 PASS, 0 WARN y 0 FAIL; migrations SQLite 1..8 y PostgreSQL
1..9 están aplicadas, API/PostgreSQL saludables, worker Codex provisionado y checkout/imagen
alineados. Los controles permanecen `shadow/A0`, kill switch activo, browser writes desactivado
y contenedor browser detenido.

Rollback: volver al checkout/imagen anterior conserva tablas aditivas y evidencia histórica;
detener el worker impide deliberaciones nuevas. Ningún rollback requiere modificar la cuenta FPL
porque HV1-06B no posee una primitiva de escritura.
