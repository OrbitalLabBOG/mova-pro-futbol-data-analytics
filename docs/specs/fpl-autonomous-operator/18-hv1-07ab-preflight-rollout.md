---
type: evidence
name: "MOVA FPL — rollout HV1-07A/B"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, autonomy, execution-plan, preflight, rollout]
status: verified
---

# Rollout HV1-07A/B: AutonomyPolicy + ExecutionPlan

## Resultado

El 30 de agosto de 2026 se desplegó la frontera determinista previa al browser sin ampliar
autoridad. La revisión productiva del VPS quedó en `04ca113`; checkout e imagen coincidieron y
el browser permaneció detenido. Los controles siguieron exactamente en:

```text
mode=shadow · action_level=A0 · compliance=pending
kill_switch=true · browser_writes=false
```

SQLite aplicó migration 009. PostgreSQL shadow aplicó 010/011 e importó con igualdad de conteos:
un `execution_plan` y 16 `execution_preflight_checks`. SQLite continúa como writer.

## Rehearsal vivo

La propuesta vigente de GW3 contenía wildcard y fue clasificada `R3`, nivel requerido `A3`. El
preflight produjo:

- plan `execplan_e10496687d3349002802e036`;
- content SHA-256 `e10496687d3349002802e0362b12dc54e7bff57de8cc76880262806d44047409`;
- team state presente, válido, fresco y con fingerprint idéntico al solve;
- manifest ligado, artifact verificado y deadline abierto;
- estado final `blocked`, sin iniciar browser ni ejecutar `apply`.

Los ocho blockers observados fueron correctos para el momento del rehearsal:

1. envelope todavía bloqueado por gates deportivos previos;
2. fase `baseline`, fuera de la ventana de ejecución;
3. incidente P1 histórico aún abierto;
4. kill switch activo;
5. browser writes deshabilitado;
6. compliance pendiente;
7. autonomía A0 insuficiente para R3;
8. modo shadow, no autonomous.

Repetir la misma idempotency key devolvió el mismo `plan_id`, `job_id`, timestamps y hashes con
`reused=true`; no creó evidencia duplicada.

## Verificación

- suite hermética: `880 passed, 1 skipped, 79 deselected`;
- `python -m compileall -q mova_fpl`: aprobado;
- `docker compose config`: aprobado;
- `mova doctor --json`: 22 PASS, 0 WARN, 0 FAIL;
- `mova postgres verify`: pass, incluyendo 1/1 planes y 16/16 checks en el import nuevo;
- API lista y métricas `mova_execution_plan_status{status="blocked"}=1`;
- backup previo al rollout: service result success;
- rollback disponible: imagen/checkpoint anterior `5508a1a`, migraciones aditivas conservables.

## Límite y siguiente gate

Este rollout no completa HV1-07. Falta un executor que consuma únicamente `authorized`, aplique
una vez, relea FPL y compare el fingerprint post-acción. Después se requieren tres rehearsals sin
duplicados ni evidencia faltante antes de elevar R2/R3. Ningún resultado de Strategist/Critic
puede habilitar esa promoción.
