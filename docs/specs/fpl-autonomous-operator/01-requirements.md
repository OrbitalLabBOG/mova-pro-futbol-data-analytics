---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Requirements"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, requirements, autonomy]
status: proposed
---

# Requisitos

`MUST` bloquea release; `SHOULD` exige excepción escrita; `MAY` es opcional.

## Funcionales

| ID | Pri. | Requisito verificable |
| --- | --- | --- |
| REQ-F-001 | MUST | Descubrir temporada, siguiente GW y deadline desde el bootstrap vigente en cada `tick`; nunca depender de fechas estáticas. |
| REQ-F-002 | MUST | Congelar cada respuesta fuente con bytes, SHA-256, URL, estado HTTP, `observed_at`, temporada, GW y parser version. |
| REQ-F-003 | MUST | Validar conteos, claves, esquema, rangos y coherencia cruzada antes de marcar un snapshot como utilizable. |
| REQ-F-004 | MUST | Reconciliar plantilla, XI, banca, capitán, vice, banco, PP/SP/CP, FTs y chips; los valores privados prevalecen cuando estén disponibles. |
| REQ-F-005 | MUST | Clasificar noticias en señales estructuradas con fuente, fecha, sujeto, claim, confianza, TTL, evidencia, hash y conflicto. |
| REQ-F-006 | MUST | Aplicar noticias únicamente mediante `Intervention`; el agente no puede escribir una `Decision` ni forzar plantilla, XI o capitán. |
| REQ-F-007 | MUST | Invocar la única función `mova_fpl.engine.runner.decide()` con estado y configuración congelados. |
| REQ-F-008 | MUST | Registrar versiones y hashes de Git, reglas, datos, modelos, configuración, prompts y decisión. |
| REQ-F-009 | MUST | Validar 15/11, formación, capitán/vice, presupuesto, club limit, FTs, hits y elegibilidad del chip antes de cualquier propuesta o ejecución. |
| REQ-F-010 | MUST | Mantener plan rodante de FTs, valor de plantilla, riesgos, blancos/dobles y ocho chips, sin obligar el uso de un chip solo porque esté permitido. |
| REQ-F-011 | MUST | Exponer un puerto de ejecución externo con implementaciones `disabled`, `human` y `browser`; el motor no importa browser tooling. |
| REQ-F-012 | MUST | Ejecutar solo una decisión inmutable `eligible`, dentro de ventana y nivel autorizado, con comparación previa exacta. |
| REQ-F-013 | MUST | Después de escribir, esperar confirmación específica, recargar, releer y comparar estado; una captura previa no prueba persistencia. |
| REQ-F-014 | MUST | Liquidar cada GW con puntos, autosubs, capitán efectivo, hits y estado real; cerrar atribución con/sin intervención. |
| REQ-F-015 | MUST | Permitir replay sin red ni browser desde el manifest de una corrida. |
| REQ-F-016 | MUST | Implementar `pause`, kill switch y circuit breaker globales y por nivel de acción. |
| REQ-F-017 | MUST | Ejecutar una sola máquina de estados idempotente por `(season, gw)`; ticks concurrentes no duplican trabajo. |
| REQ-F-018 | SHOULD | Generar un acta legible con cambio vs decisión anterior, incertidumbre, fuentes decisivas, escenarios y razones de no actuar. |

## Calidad y tiempo

| ID | Pri. | Requisito verificable |
| --- | --- | --- |
| REQ-Q-001 | MUST | Un `tick` repetido con las mismas entradas produce el mismo estado y no repite efectos. |
| REQ-Q-002 | MUST | Toda hora persistida usa UTC en ISO-8601 con `Z` o epoch explícito y toda fecha visible indica zona. |
| REQ-Q-003 | MUST | La decisión final se congela por defecto en T-60m, se ejecuta en T-45m, se verifica en T-30m y entra en hard stop en T-15m. |
| REQ-Q-004 | MUST | La API FPL usada en freeze tiene edad ≤15m y las noticias obligatorias ≤60m; si no, se bloquea el write. |
| REQ-Q-005 | MUST | El ciclo completo sin investigación web pesada termina en ≤10m p95 en el VPS objetivo. |
| REQ-Q-006 | MUST | Todo modelo productivo es inmutable, cargable, con métricas, training window, git SHA y checksum; no se entrena durante una decisión. |
| REQ-Q-007 | MUST | El optimizador infactible, un parser con drift o una discrepancia de UI falla cerrado, sin relajar restricciones. |
| REQ-Q-008 | MUST | Cada componente tiene healthcheck, límites CPU/memoria, timeout, retry budget y shutdown limpio. |
| REQ-Q-009 | SHOULD | Tests de contrato reproducen fixtures y DOM grabados sin tocar FPL. |
| REQ-Q-010 | SHOULD | El sistema puede reconstruirse en un VPS limpio desde Git y artefactos versionados sin depender del Python o SQLite del host. |
| REQ-Q-011 | MUST | Toda conexión productiva a `ops.db`, incluidos backup y checkpoint, usa SQLite ≥3.51.3; el arranque registra la versión y falla cerrado si no cumple. |

## Seguridad, cumplimiento y privacidad

| ID | Pri. | Requisito verificable |
| --- | --- | --- |
| REQ-S-001 | MUST | No guardar ni automatizar contraseña, OTP o MFA; si se solicitan, el ciclo pasa a `blocked_auth`. |
| REQ-S-002 | MUST | Cookies y perfil del browser permanecen fuera de Git, DB, logs y backups generales, con permisos mínimos y directorio dedicado. |
| REQ-S-003 | MUST | `ops.db`, artefactos y configuración viven en paths dedicados del VPS, sin puertos de base de datos y con propietario/permisos mínimos. |
| REQ-S-004 | MUST | Secretos de fuentes/LLM solo existen en archivos del VPS montados al contenedor requerido; nunca en Git, DB, dashboard, reportes o telemetría. |
| REQ-S-005 | MUST | Screenshots y HTML se tratan como evidencia sensible, se redactan y almacenan en ubicación privada. |
| REQ-S-006 | MUST | Toda mutación externa requiere `compliance_gate=approved`, autonomía habilitada y nivel de acción permitido. |
| REQ-S-007 | MUST | Dependencias e imágenes se fijan por versión/digest y se conservan lockfiles/SBOM. |
| REQ-S-008 | MUST | El servicio browser no expone CDP ni puertos públicos y corre separado de otras identidades. |
| REQ-S-009 | MUST | Ningún dato de rumor de baja confianza puede producir `lock_out`, chip o hit por sí solo. |
| REQ-S-010 | MUST | El runtime no importa SDK de Supabase ni conoce su URL/keys. Supabase recibe únicamente seguimiento PM por un flujo externo y separado. |

## Observabilidad y operación

| ID | Pri. | Requisito verificable |
| --- | --- | --- |
| REQ-O-001 | MUST | Propagar `trace_id`, `run_id`, `cycle_id`, `job_id`, season y GW entre scheduler, collector, research, engine, browser y verifier. |
| REQ-O-002 | MUST | Emitir logs JSON estructurados con redacción y sin campos de alta cardinalidad como labels de métricas. |
| REQ-O-003 | MUST | Exponer métricas de última ejecución exitosa, duración, frescura, deadline, validación, decisión, ejecución y recursos. |
| REQ-O-004 | MUST | Persistir en `ops.db` el ledger de jobs y transición de estados, incluso si dashboard, logs o exportación de métricas fallan. |
| REQ-O-005 | MUST | Alertar P0/P1 con deduplicación, acuse y enlace al runbook y ciclo afectado. |
| REQ-O-006 | MUST | Tablero principal muestra countdown, fase, frescura, decisión/diff, modo, gate, ejecución, incidentes y modelo. |
| REQ-O-007 | MUST | Toda alerta tiene owner, severidad, condición, ventana, acción y criterio de cierre. |
| REQ-O-008 | SHOULD | Exponer métricas Prometheus-compatible e IDs de correlación sin depender de un backend externo; cualquier exporter futuro será opcional y reemplazable. |
| REQ-O-009 | SHOULD | Calcular drift de esquema, población, predicción, calibración, disponibilidad y efecto de intervenciones. |
| REQ-O-010 | SHOULD | Producir postmortem automático de GW con resultado, contrafactuales y cambios de estrategia propuestos, nunca auto-promovidos. |

## Restricciones de autonomía por acción

| Nivel | Acciones | Activación mínima |
| --- | --- | --- |
| A0 | recolectar, investigar, decidir, simular | shadow + gate de fuente aplicable |
| A1 | XI, banca, capitán y vice | compliance aprobado + guarded + verificación completa |
| A2 | transferencias sin hit | A1 estable + margen y sensibilidad aprobados |
| A3 | hits y chips | autonomous + gate reforzado y ausencia de conflicto |

Una autorización de nivel superior incluye las inferiores, pero el kill switch puede
deshabilitar cualquier nivel por separado.
