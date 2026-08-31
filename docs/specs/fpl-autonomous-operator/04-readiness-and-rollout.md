---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Readiness and Rollout"
created: 2026-08-21
updated: 2026-08-31
tags: [mova, fpl, readiness, rollout]
status: active-shadow
---

# Readiness y rollout

## Veredicto

**SHADOW CONTROL PLANE ACTIVE · NOT READY FOR FPL WRITES.**

El runtime reproducible, plano de control, scheduler, collector, modelos, auditoría,
backup y ejecutor browser aislado ya corren en el VPS. Los gates permanecen cerrados en
`shadow`, `A0`, `compliance=pending`, `kill_switch=true` y `browser_writes=false`.
El perfil fue autenticado bajo supervisión, corresponde a `losmillosFPL` / `entry_id=3609854`
y sobrevivió una recreación controlada del contenedor. Faltan completar research/alerting y
acumular evidencia antes de evaluar cualquier escritura externa.

La evidencia verificable del corte está en
[07-deployment-evidence.md](07-deployment-evidence.md). La matriz inferior se conserva
como baseline del diagnóstico previo al despliegue.

Desde el 30 de agosto, el veredicto también es máquina-legible mediante `mova readiness` y
`/api/v1/readiness`. El corte vivo del 31 de agosto conserva A0 técnico: 15 de 25 gates pasan,
10 esperan evidencia temporal o una integración externa autorizada y ninguno está bloqueado por
un fallo abierto. Esto no reemplaza esta política ni concede autoridad. Ver
[acta HV1-09M](57-hv1-09m-final-runtime-closeout.md).

## Checkpoint vigente — 2026-08-22

| Área | Evidencia | Estado |
| --- | --- | --- |
| Browser dedicado | Chromium normal supervisado; agent-browser se adjunta por CDP interno | ready para lectura |
| Identidad FPL | `/en/my-team` contiene `losmillosFPL` y `entry_id=3609854` | verified |
| Persistencia auth | recreación de contenedor conservó acceso autenticado | verified |
| Exposición | noVNC sólo `127.0.0.1:6080`; CDP sólo loopback del contenedor | verified |
| Escritura FPL | shadow A0, compliance pendiente, kill switch activo | blocked por diseño |

## Matriz previa al despliegue (corte 2026-08-21)

| Área | Evidencia | Estado |
| --- | --- | --- |
| Motor/reglas | 631 tests rápidos + 2 slow; decisión viva válida | ready |
| Datos históricos | 253.890 filas, 10 temporadas, integridad y claves únicas | ready |
| Collector vivo | hash + semántica PASS; 600 players/380 fixtures al corte | ready, falta deploy/observabilidad |
| Modelos | minutes/points 1.1.0 cargan y tienen training de 10 temporadas | ready como baseline |
| Agente de noticias | contrato existe; efecto del LLM no está probado | shadow only |
| Estado privado FPL | skill manual probada; API pública insuficiente para PP/SP/FT | partial |
| Ejecutor browser VPS | no hay perfil FPL ni agent-browser dedicado | missing |
| VPS | capacidad y privilegios adecuados; Python host incompatible | ready para Docker |
| Git/deploy | local ahead 5; VPS/remote en `0105452` | blocked hasta sincronizar |
| Persistencia operativa | no existe `ops.db`; SQLite host 3.45.1 no cumple el gate WAL ≥3.51.3 | missing, requiere runtime Docker fijado |
| Scheduling | cron activo, systemd disponible; no existe timer MOVA | missing |
| Observabilidad | trace analítica parcial; no hay metrics/alerts/dashboard | missing |
| Compliance | términos vigentes plantean riesgo de automatización | blocker de write |

## Inventario VPS observado

Corte remoto: `2026-08-21 15:46 UTC`, inspección read-only.

| Recurso | Estado observado | Implicación |
| --- | --- | --- |
| Host | Ubuntu 24.04.3, 2 CPU, 7.8 GiB RAM, 4.4 GiB disponibles | cabe un runtime austero; necesita admission gates |
| Disco | 96 GiB totales, ~68 GiB libres | suficiente para DB/artifacts con retención y alertas |
| Runtime | Docker 29.1.3, Compose 2.37.1, systemd 255 | base aprobada para WP-001 |
| Carga existente | 11 containers; Docker usa ~12.9 GiB images, ~2 GiB volumes | no instalar stack pesado de observabilidad |
| Persistencia | `/opt/orbital/backups` privado; no restic/borg/rclone | backup local posible, off-host pendiente |
| Scheduling | cron y systemd activos; watchdog Orbital cada 30m | adoptar units/timers, no root crontab |
| Red | servicios internos mayormente en loopback; Caddy en 80/443 | MOVA no requiere puerto público |
| Repo | MOVA no está clonado; acceso Git sí funciona | release debe sincronizar SHA y artifacts ignorados |

No se modificó el host durante esta inspección.

## Gates de release

### G0 — Spec approved

- arquitectura aprobada por Julián y Buitra;
- Q-01..Q-04 resueltas o aceptadas;
- threat model y ownership de incidentes asignados;
- ningún cambio operativo mezclado con la aprobación.

### G1 — Runtime reproducible

- Git remoto contiene el commit aprobado y VPS despliega exactamente ese SHA; hoy el remoto
  está cinco commits detrás del checkout local;
- imágenes por digest con Python 3.13/CBC, SQLite ≥3.51.3 y lockfiles;
- startup gate demuestra `sqlite_version()` corregida; ningún job productivo usa el binario
  SQLite 3.45.1 del host;
- volumes, backups, healthchecks, límites y restore drill probados;
- suite rápida y smoke live read-only pasan dentro del contenedor.

### G2 — Control plane observable

- `ops.db` migrado con WAL, foreign keys, constraints, permisos y backup consistente;
- tick idempotente, `flock`, ledger, outbox y replay probados;
- dashboard Now/Operations y alertas P0/P1 con acuse;
- caos básico: reboot, API caída, DB caída, snapshot inválido.

API, PostgreSQL, browser, outage combinado y reboot real tienen evidencia viva. El reinicio
autorizado del 31 de agosto cambió el boot ID, reanudó el scheduler y pasó 11/11 checks sin mutar
el estado FPL. `HOST_RECOVERY_DRILLS_PROVEN` está completo 5/5. G2 conserva como pendientes de
operación el destino externo de alertas y el backup cifrado off-host; no son fallos del runtime.

### G3 — Shadow season loop

- mínimo 3 GWs completas o equivalente de rehearsals con todos los estados;
- cero jobs huérfanos, decisiones irreproducibles o alertas perdidas;
- research signals y atribución funcionan, pero LLM no altera producción;
- search citations se refetchean y sellan; ningún claim aceptado depende solo de metadata
  del provider;
- budgets, retry layers, wall timeout, redaction y `cost_known` pasan drills;
- deadline drill acelerado demuestra freeze, hard stop y recuperación.

### G4 — Supervised execution

- compliance gate registrado;
- browser dedicado autenticado por Julián, sin secretos automatizados;
- fixtures DOM y tests contractuales;
- al menos 3 ejecuciones supervisadas A1/A2 con reload y evidencia;
- kill switch y recuperación de ejecución ambigua ensayados.

### G5 — Guarded

- A1 automático estable al menos 3 GWs;
- cero discrepancias post-reload y cero duplicados;
- A2 habilitado separadamente, con sensitivity gate y límites;
- toda falla conduce a estado verificado anterior antes de hard stop.

### G6 — Autonomous

- temporada estratégica, chips y FTs reconciliados;
- A3 aprobado explícitamente;
- hits/chips pasan margen, robustez, fuente y ventana reforzados;
- revisión mensual de desempeño y seguridad conserva facultad de rollback.

No se salta un gate por cercanía al deadline.

## Política de promoción del agente

Los hallazgos actuales no justifican control productivo: 18 intervenciones shadow tuvieron
media negativa y el intervalo incluye cero; pruebas named/anonymized muestran fragilidad.

Para salir de shadow:

1. causalidad y contaminación revisadas;
2. señales siempre citadas y sin confabulaciones materiales;
3. efecto local pareado, no total de temporada;
4. muestra predefinida y criterio registrado antes de evaluarla;
5. no degradación de factibilidad, calibración o incidentes;
6. aprobación humana de la nueva policy version.

Una propuesta de memoria o regla nunca se auto-promueve. Se crea candidata y pasa por el
mismo proceso.

## Reglas de hits y chips

El diseño no fija ahora los umbrales deportivos: obliga a versionarlos y medirlos. Como
gate mínimo:

- hit: ganancia neta después del coste > margen configurable en escenarios base/bajo;
- chip: ventaja vs no-chip en horizonte, ventana legal e inventario confirmados;
- transfer: beneficio robusto a minutos/fixture y reconciliación exacta de SP/FT;
- cualquier conflicto de disponibilidad significativo bloquea A3;
- máximo una ejecución irreversible por revisión y GW.

## Rollback

| Cambio | Rollback |
| --- | --- |
| modelo | volver al último `production` por hash; no reentrenar de urgencia |
| policy/prompts | pin anterior; revisions existentes permanecen inmutables |
| app | imagen digest anterior y migration compatibility verificada |
| browser | deshabilitar executor y pasar a supervised/manual |
| nivel de autonomía | bajar A3→A2→A1→A0 en control plane |
| sistema completo | kill switch global; conservar último equipo verificado |

El rollback de software no intenta revertir automáticamente una transferencia o chip ya
confirmado. Esos efectos son del juego y se tratan como incidente/estado nuevo.

## Readiness checklist por GW

- [ ] deadline oficial confirmado y countdown correcto;
- [ ] snapshots obligatorios frescos, válidos y sellados;
- [ ] team state reconciliado, incluidos PP/SP/FT/chips;
- [ ] fuentes de noticias cubiertas y conflictos resueltos/declarados;
- [ ] modelos/rules/config/prompt hashes permitidos;
- [ ] decisión factible y sensitivity gate verde;
- [ ] modo, compliance y action level permiten la acción;
- [ ] browser sano y sesión corresponde a `entry_id=3609854`;
- [ ] no existe ejecución previa ambigua;
- [ ] hay tiempo para ejecutar y verificar antes de hard stop;
- [ ] alerta P0 tiene ruta de acuse disponible;
- [ ] kill switch probado y accesible.

## Decisión vigente

La implementación y operación `shadow A0` están activas. Sigue sin estar autorizada la
ejecución sobre FPL. Cualquier promoción requiere evidencia de los gates G3/G4, decisión
registrada sobre compliance y aprobación explícita separada.
