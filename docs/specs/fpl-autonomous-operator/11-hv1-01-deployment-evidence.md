---
type: deployment-evidence
name: "HV1-01 — contrato operativo y rollout VPS"
created: 2026-08-23
updated: 2026-08-23
tags: [mova, fpl, harness, operator, vps, evidence]
status: accepted
---

# HV1-01 — evidencia de cierre

## Entrega

- Commit productivo: `8462d122e4f74e4a3104da12eeeacfd9eaddc848`.
- Release del paquete: `0.3.0`.
- Contrato: `mova-fpl-operator-v1`, versión `1.0`.
- Comandos: `mova status [--json]` y `mova doctor [--json] [--no-network]`.
- Superficies adicionales: `/api/v1/status`, wrapper `/usr/local/bin/mova`, probe sanitizado
  del host y skill `mova-fpl-operator`.
- No hubo migración, modificación de `ops.db`, cambio de datos, cambio de controles ni acción
  browser.

## Evidencia de calidad

| Gate | Resultado |
| --- | --- |
| suite hermética local | 656 passed, 79 deselected |
| GitHub Actions PR | success, run `32656255547` |
| GitHub Actions `main` | success, run `32656303259` |
| Python | 3.13.5 |
| SQLite de imagen | 3.53.4 |
| build/smoke Docker local | success |
| skills nativa y canónica | `quick_validate` success |
| Markdown, JSON, Bash y compileall | success |

## Rollout VPS

El checkout avanzó por fast-forward limpio desde `d5e9d25` hasta `8462d12`. La imagen nueva se
construyó y pasó preflight contra los volúmenes productivos antes de sustituir el API:

```text
15 PASS · 1 WARN · 0 FAIL
WARN esperado: checkout nuevo / imagen activa anterior
```

Después de recrear el API con `mova-fpl-engine:8462d12`, instalar el wrapper y regenerar el probe:

```text
MOVA FPL · HEALTHY
GW 2 · baseline · deadline 2026-08-28T17:30:00Z
Equipo 15/15 · 1 FT · £0.0m · team state valid
Fuentes 1 · modelos 4 artefactos / 0 registrados
shadow / A0 · compliance pending · kill_switch=true · browser_writes=false

MOVA doctor · HEALTHY
16 PASS · 0 WARN · 0 FAIL
```

El API quedó `healthy`, los cinco units/timers requeridos `active`, el backup reciente presente,
las bases canónica/traza válidas, las familias `minutes` y `points` disponibles, el perfil browser
persistente presente y la API oficial FPL accesible.

La validación cruzada detectó que el API inicialmente solo montaba `db/`: el CLI observaba cuatro
artefactos y el probe, mientras HTTP reportaba cero/no observable. Se añadieron mounts de solo
lectura para `artifacts/` y `runtime/`; el engine sigue sin Docker socket, D-Bus ni acceso al perfil.

## Hallazgo de rollout

La primera recreación manual usó `mova-fpl-engine:local` con revisión `unknown` porque el proceso
de Compose no había cargado `/etc/mova-fpl/deploy.env`. El nuevo `doctor` lo detectó como
`deployment_revision WARN`; se cargó el env explícitamente y se recreó el API con el tag aprobado.
No hubo indisponibilidad sostenida, pérdida de datos ni fallo requerido. El runbook VPS conserva
el comando correcto para futuras intervenciones.

## Rollback

- Imagen anterior conservada: `mova-fpl-engine:684e5da`.
- Copia previa del descriptor: `/etc/mova-fpl/deploy.env.pre-hv1-01`.
- No se requiere rollback de datos porque HV1-01 es compatible con las migrations 1–3.

## Deuda explícita transferida a HV1-02

Los cuatro artefactos productivos existen en disco, pero `model_releases` aún no contiene sus
registros. `status` distingue correctamente `4 artefactos / 0 registrados`; el import y registro
durable pertenecen al cutover PostgreSQL de HV1-02.
