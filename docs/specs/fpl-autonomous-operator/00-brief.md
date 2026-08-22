---
type: project
name: "MOVA FPL Autonomous Operator 2026/27 — Brief"
created: 2026-08-21
updated: 2026-08-21
tags: [mova, fpl, autonomy, brief]
status: proposed
---

# Brief

## Objetivo

Construir un operador que gestione `losmillosFPL` jornada a jornada: detecta el siguiente
deadline, recolecta y valida datos, investiga novedades, proyecta, optimiza, aplica la
política de largo plazo, prepara o ejecuta la decisión permitida, demuestra que persistió,
liquida el resultado y aprende sin contaminar el baseline.

El resultado buscado es **autonomía operativa total como capacidad**, con activación
gradual por nivel de riesgo y con evidencia suficiente para explicar, reproducir y ajustar
cualquier decisión meses después.

## Hechos verificados al corte

Corte: `2026-08-21 10:27 America/Bogota`.

| ID | Hecho |
| --- | --- |
| H-01 | El bootstrap oficial reportó 600 jugadores, 20 clubes, 38 jornadas y deadline GW1 `2026-08-21T17:30:00Z`; su SHA-256 fue `6d131a19ac2b8ea925538fd0ab6109464f80fb0e5faa471c8e8555030f87dbfd`. |
| H-02 | El catálogo cambió de 599 a 600 jugadores entre dos verificaciones consecutivas. Una corrida solo es reproducible si congela su snapshot. |
| H-03 | El collector vigente pasó validación de hash y semántica; el motor produjo una decisión válida con modelos `minutes/1.1.0` y `points/1.1.0`. |
| H-04 | La suite completa pasó: 631 pruebas rápidas y 2 lentas; el almacén canónico tiene 253.890 filas, 61 columnas, 10 temporadas, claves lógicas únicas e integridad SQLite correcta. |
| H-05 | La plantilla GW1 montada conserva 15 jugadores, £100.0m, restricciones válidas y huella `5e39cc0f12c84566`. |
| H-06 | La API pública no expone de forma confiable precio de compra/venta ni saldo exacto de transferencias libres; esos valores requieren estado autenticado o reconciliación contable. |
| H-07 | La traza local ya registra corridas, decisiones, modelos, benchmarks e intervenciones, pero no jobs, fuentes, ejecución web, verificaciones, incidentes ni alertas. |
| H-08 | El backtest del agente LLM no demuestra mejora: la muestra pareada es pequeña, con tendencia negativa y alta varianza. El total de temporada no sirve como estimador causal por dependencia de camino. |
| H-09 | Supabase se reserva exclusivamente para seguimiento PM de la construcción. El runtime FPL no lo consulta ni escribe; operación, evidencia y observabilidad viven en el VPS. |
| H-10 | El VPS `72.60.245.2` permite SSH, Docker 29.1.3, Compose 2.37.1, systemd 255 y escritura operativa; tiene 2 CPU, 7.8 GB RAM y ~68 GB libres. |
| H-11 | El VPS usa Python 3.12 y el repo exige Python 3.13.5; el repo remoto está cinco commits detrás del local. Docker y sincronización Git son gates de despliegue. |
| H-12 | El servicio VPS `premier-league-api` mezcla temporadas, conserva 841 jugadores y 147 fallos, y puede reportar éxito con cero historia nueva. No es fuente viva autoritativa de 2026/27. |
| H-13 | El Chrome/OpenClaw existente no tiene sesión FPL verificada ni `agent-browser`; reutilizarlo mezclaría identidades y dominios de fallo. |
| H-14 | Los términos FPL vigentes prohíben usar sistemas automatizados para acceder y extraer información, exigen control personal de la cuenta y contemplan suspensión o descalificación. La activación externa necesita una decisión de riesgo separada. |
| H-15 | El binario SQLite 3.45.1 del host está dentro del rango afectado por el bug upstream de WAL-reset corregido en 3.51.3. Producción debe usar y verificar SQLite ≥3.51.3 dentro de la imagen; el binario del host no opera `ops.db`. |

Los conteos y hashes son evidencia del corte, no constantes del sistema.

## Alcance

Incluye el diseño de:

1. ciclo autónomo basado en estado y deadline dinámico;
2. recolección inmutable, validación semántica y detección de drift;
3. investigación trazable de noticias y alineaciones probables;
4. uso del motor determinista y del contrato acotado `Intervention`;
5. estrategia de transferencias, chips y riesgo a largo plazo;
6. adaptador de ejecución web reemplazable, idempotente y verificable;
7. plano de control local en `ops.db`, analítica en SQLite y artefactos por hash, todo en el VPS;
8. Docker, temporizadores systemd, health checks, kill switch y recuperación;
9. logs, métricas, trazas, tableros, alertas, incidentes y post-gameweek;
10. rollout `shadow → supervised → guarded → autonomous`.

## Fuera de alcance de esta entrega

- implementar código, Dockerfiles, Compose, timers o dashboards;
- crear tablas operativas en Supabase o conectar el runtime FPL con Supabase;
- desplegar o sincronizar el VPS;
- recolectar credenciales, cookies, contraseña, OTP o MFA;
- cambiar plantilla, alineación, capitán, transferencias o chips;
- declarar aceptado el riesgo de los términos FPL;
- promover el agente LLM o un modelo nuevo;
- automatizar comunicación externa.

## Resultado observable de la iniciativa futura

Para cada GW debe existir una cadena completa y reproducible:

`deadline → snapshots → señales → intervención → proyección → decisión → validación → ejecución → verificación → resultado → atribución`.

Cada eslabón referencia al anterior mediante IDs y hashes. Una ejecución sin cadena completa
se considera fallida aunque la UI parezca correcta.

## Principios

1. El deadline se descubre; nunca se codifica en cron.
2. El motor determinista decide; el LLM aporta señales acotadas.
3. Toda entrada decisiva queda congelada antes de optimizar.
4. Ninguna escritura externa se reintenta a ciegas.
5. El estado observado después de recargar manda sobre el mensaje de éxito.
6. La ausencia de evidencia equivale a no ejecutado.
7. UTC se usa internamente; Bogotá es solo presentación.
8. Modelar y entrenar son ciclos distintos de decidir.
9. El modo seguro ante duda es pausa y lectura, no mutación.
10. La autonomía se gana por evidencia y se puede revocar en un solo control.

## Métricas de éxito

| ID | Métrica | Objetivo |
| --- | --- | --- |
| M-01 | Gameweeks con ciclo completo antes del deadline | 38/38 o todas las restantes tras activación |
| M-02 | Mutaciones duplicadas o posteriores al hard stop | 0 |
| M-03 | Decisiones no reproducibles desde manifest y hashes | 0 |
| M-04 | Ejecuciones sin recarga, comparación y evidencia | 0 |
| M-05 | Fuentes obligatorias fuera de frescura en freeze | 0; si ocurre, ciclo bloqueado |
| M-06 | Incidentes críticos detectados antes del deadline | 100% |
| M-07 | Intervenciones del agente con atribución contrafactual | 100% de las que cambien decisión |
| M-08 | Secretos o cookies en Git, DB, logs o telemetría | 0 |

## Preguntas de aprobación, no de arquitectura

| ID | Pregunta | Gate |
| --- | --- | --- |
| Q-01 | ¿Se acepta el riesgo contractual o se obtiene permiso/criterio especializado para automatizar FPL? | Cualquier automatización externa |
| Q-02 | ¿Qué nivel máximo se activa primero: supervised o guarded? | Rollout posterior a shadow |
| Q-03 | ¿Cuál será el canal de alerta con acuse para P0/P1? | Operación desatendida |
| Q-04 | ¿Se autoriza backup off-host y cuál será su destino cifrado? | No bloquea shadow local; sí recuperación ante pérdida total del VPS |
