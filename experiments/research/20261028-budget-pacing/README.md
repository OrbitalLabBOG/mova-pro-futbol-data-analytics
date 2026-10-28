---
title: Researcher 1.18 — cierre por presupuesto y enmienda prospectiva
status: deployed_live_validated
date: 2026-10-28
---

# Resultado

Researcher 1.18 está desplegado en `799a2220ddb92f8342faeb09380f6c951b6b3f14`,
integrado a main por PR #224 (`ab5bd1a`). Envía una única instrucción `turn/steer`
al alcanzar el 50% del límite lógico para finalizar el JSON con evidencia verificada
y pendientes explícitos. Conserva el corte duro de 900.000 tokens, cuenta cacheados
y mantiene consumo incierto tras una interrupción. El aviso no garantiza que el
modelo obedezca ni que se alcance la calidad final: el corte duro sigue activo.

## Diagnóstico preservado

GW9 run `research_68f49c4d532745518e9ef663b7576b3c`, bajo `959825f`, agotó sus dos
intentos por `logical_token_guard` el 28 de octubre. La repetición del contexto en
llamadas sucesivas consumió el presupuesto antes de producir un brief. No había
aviso de cierre previo. No se corrigió un error de suma ni se aumentaron cuotas.

| Intento | Input observado | Output observado | Cacheado incluido en input |
| --- | ---: | ---: | ---: |
| `attempt_6d4eb54f056e4b859bf1aa622af2d6c3` | 924324 | 2446 | 868352 |
| `attempt_41fd54c2c3284c36a2a502e3db73f5f3` | 921866 | 1770 | 871680 |

Son contadores observados antes de cancelar, no liquidaciones exactas de inferencias
interrumpidas. El historial, los receipts y los cargos originales permanecen.
No se reencoló el slot operacional rechazado ni se convirtió en éxito retrospectivo.

## Prueba viva independiente

Dos experimentos manuales, no importados como señales operativas, terminaron en un
solo intento con liquidación exacta. Ambos recibieron y reconocieron el aviso.

| Corrida | Revisión | Tokens exactos | Sujetos con evidencia / foco |
| --- | --- | ---: | ---: |
| `research_79e95a3ca97f67c087ff0ae08161af12` | `80d3a26` | 591148 | 8 / 25 |
| `research_f47716941581c5d4d742619246e04ece` | `799a222` | 622218 | 9 / 25 |

El segundo experimento valida la revisión final, que además exige identidad real
del agente en la prueba de enmienda. Los resultados son parciales; no acreditan
90% de cobertura, 80% de evidencia de campaña ni ejecución autónoma. Los sujetos
restantes permanecen pendientes. El total de experimentación fue 1.213.366 tokens;
quedaron 1.786.634 del presupuesto registrado de GW9 al liquidarlos, sin ampliación.

Fuentes del VPS: `artifacts/research/archive/<run>.evaluation.json`, los resultados
sellados y los receipts/logs bajo `/var/lib/mova-fpl/artifacts/research/`.

## Cohorte conservada mediante la excepción autorizada

Julián autorizó expresamente «Autorizar enmienda prospectiva auditada». La operación
se registró a las 18:31:07 UTC del 28 de octubre, antes de ventanas e inferencias.

- Cohorte original: `acceptance_a823bd798e83614f5ea1cb89899519f8`.
- Hash original preservado: `1f185e5f1d76628176c8dc245a0bbc5fe56e6be4778e6d33ca15f08866605055`.
- Enmienda: `amendment_1b92fc6ada8f541abc2c34e79fbb7910`.
- Hash efectivo: `49ea592df53140e5305d57b093d09614c76a83d9bbcd3eecb45a4427f6626f2f`.
- Prueba vinculada: `research_f47716941581c5d4d742619246e04ece`.
- Lectura viva a las 19:26 UTC: `in_progress`; GW10, GW11 y GW12 `pending`, sin
  corridas ni razones de fallo. Mismas fechas, cuotas, criterios y selección.

La fila original es inmutable; la enmienda ocupa un registro adicional inmutable.
El comando bloquea segunda enmienda, ventanas iniciadas, cualquier corrida previa
(incluso experimental), cambios de modelo/cuotas/criterios y prueba incierta o de
otra versión. SQLite migración 24; PostgreSQL shadow migración 27. No hubo nueva
cohorte, promoción A3, transferencias, chips ni Save de prueba.

## Verificación y límites

Suite completa: **2315 passed, 1 skipped, 79 deselected**. CI test e image-smoke de
la revisión final pasaron; `node --check` y `compileall` también. Los tests incluyen
corte duro si se ignora el aviso, identidad de turno, cierre concurrente, consumo
cacheado, inmutabilidad, causalidad, límites de alcance e idempotencia.

El backup previo de SQLite quedó verificado en `20261028T181527Z`; el servicio de
backup SQLite/PostgreSQL terminó success. Se conservaron imagen y configuración
previas para recuperación. Un rollback posterior a la enmienda debe detener nuevas
inferencias y reconciliar el contrato; no borrar la revisión ni restaurar datos
viejos encima de la evidencia nueva.

El seguimiento posterior detectó observación DR antigua tras el cambio de revisión.
A las 19:31 UTC API y browser ya mostraban la revisión correcta y el chequeo DR
se volvió a ejecutar con success. El watchdog cerró el incidente `incident_acfef05f8b7b4c719e1933725d79f1a6` a las
19:32:45 UTC con `fresh DR observation recovered`. Se preservó su historial.

El import shadow `pgimport_37ac7ffa5ddb47bb991469355bfe03cf` incorporó la enmienda:
60 tablas verificadas (59 exactas, una agregada), cero fallos de paridad. Las
comprobaciones posteriores no cuentan como investigación ni ejecución autónoma.

La prueba autónoma de GW10–12 sigue pendiente de sus ventanas reales. Ningún ensayo
manual ni health check sustituye esa evidencia futura.
