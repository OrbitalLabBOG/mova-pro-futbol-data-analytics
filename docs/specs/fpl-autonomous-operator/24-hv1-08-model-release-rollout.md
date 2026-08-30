---
type: evidence
name: "MOVA FPL — rollout del release controlado de modelos"
created: 2026-08-30
updated: 2026-08-30
tags: [mova, fpl, hv1-08, model-release, shadow, rollback, vps]
status: verified-shadow
---

# HV1-08 — release controlado de modelos

## Resultado

El mecanismo de release quedó desplegado y observable en el VPS sin crear ni promover un
candidato ficticio. `accepted` continúa siendo solo memoria; el nuevo lifecycle puede activar un
bundle real únicamente después de `prepare → shadow → promote`, con rollback append-only.

| Evidencia | Resultado |
| --- | --- |
| Commit de desarrollo | `20c2417` |
| Commit productivo inicial | `e43e933` |
| Suite hermética | 927 passed, 1 skipped, 79 deselected |
| SQLite | 3.53.4; migrations 1–13 |
| PostgreSQL shadow | 17.11; migrations 1–15 |
| Import shadow | `pgimport_136aa603bf744635a1f320647c960592`; 50/50 tablas pass |
| Doctor post-deploy | 22 PASS, 0 WARN, 0 FAIL |
| Controles | `shadow`, `A0`, compliance pending, kill switch true, browser writes false |
| Release vivo | 0 releases, 0 eventos, sin puntero activo, shadow inactive |

## Prueba funcional

`mova analytics project` produjo para GW3 un baseline aprobado y odds shadow de 623 jugadores.
La respuesta declaró explícitamente:

```json
{
  "active_model_bundle": {
    "release_id": null,
    "source": "runtime_config",
    "minutes": "1.1.0",
    "points": "1.1.0"
  },
  "model_release_shadow": {"status": "inactive", "release_id": null}
}
```

Los endpoints `/api/v1/model-bundle-releases` y
`/api/v1/model-bundle-release-events` respondieron listas vacías. Prometheus publicó cero para
los cinco estados, cero eventos y `mova_model_bundle_pointer_present 0`. Esto demuestra que el
despliegue del mecanismo no se confunde con una promoción.

Las pruebas cubren hash adulterado, propuesta no elegible, retry idempotente, gate insuficiente,
promoción aprobada, rollback y restauración de un release previamente superseded. Analytics y el
tick de decisión resuelven la misma versión activa y validan hashes antes de inferencia.

## Backups y rollback

- pre-deploy SQLite: `/opt/orbital/backups/mova-fpl/20260830T181429Z`;
- pre-deploy PostgreSQL: `/opt/orbital/backups/mova-fpl/postgres/20260830T181440Z`;
- post-deploy SQLite: `/opt/orbital/backups/mova-fpl/20260830T181710Z`;
- post-deploy PostgreSQL: `/opt/orbital/backups/mova-fpl/postgres/20260830T181713Z`;
- imagen/checkout anterior: `1e80955`.

Las migraciones son aditivas. Un rollback de aplicación repone la imagen anterior sin borrar las
tablas nuevas. Un rollback de modelo usa `mova improve release rollback` y conserva todos los
eventos.

Durante el recreate, el primer probe HTTP ocurrió antes de que la API terminara de iniciar y el
script cortó antes de reactivar timers. La API alcanzó healthy segundos después; los seis timers
se reactivaron y verificaron individualmente antes de los smokes. No hubo escritura browser,
ejecución FPL ni ampliación de autonomía.
