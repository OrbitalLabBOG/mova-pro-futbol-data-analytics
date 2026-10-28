---
title: Candidato aislado de cierre por presupuesto research
status: implementation_awaiting_live_validation
date: 2026-10-28
---

# Resultado y límite de esta prueba

El candidato añade un único aviso `turn/steer` al alcanzar el 50% del límite
lógico. Pide finalizar el JSON con evidencia ya verificada y pendientes explícitos.
Conserva el corte duro, cuenta tokens cacheados y mantiene consumo incierto tras
interrupción. El 50% es una hipótesis conservadora pendiente de validación con el
modelo real; no garantiza cobertura ni que la respuesta parcial supere el importador.

Tras aprobación explícita del owner, el cambio se integró en el código de Researcher
1.18.0. Aún no está desplegado. Los tests usan un hijo JSON-RPC determinista; no
consumen inferencia ni acreditan aceptación research.

## Diagnóstico observado

Runtime observado: `959825fec862b5844a41e70a3e14af676679ce59`.
GW9 run `research_68f49c4d532745518e9ef663b7576b3c` agotó sus dos intentos
por `logical_token_guard` el 28 de octubre. El límite era 900.000 tokens.

| Intento | Input observado | Output observado | Cacheado incluido en input |
| --- | ---: | ---: | ---: |
| `attempt_6d4eb54f056e4b859bf1aa622af2d6c3` | 924324 | 2446 | 868352 |
| `attempt_41fd54c2c3284c36a2a502e3db73f5f3` | 921866 | 1770 | 871680 |

Estos son contadores observados antes de cancelar, no liquidaciones exactas de
una inferencia interrumpida. La repetición del contexto en llamadas sucesivas
consume el presupuesto. El controlador actual sólo interrumpe al llegar al límite;
no envía aviso previo para cerrar. No se detectó un error de suma que justifique
subir la cuota o descontar cacheados.

Fuentes: eventos y receipts existentes en `/var/lib/mova-fpl/artifacts/research/`.
El historial de los dos errores permanece intacto; no se reencoló el slot.

## Cohorte protegida

Consulta viva del API a las 18:03 UTC del 28 de octubre:

- Cohorte: `acceptance_a823bd798e83614f5ea1cb89899519f8`.
- Manifiesto: `1f185e5f1d76628176c8dc245a0bbc5fe56e6be4778e6d33ca15f08866605055`.
- Estado `in_progress`; GW10, GW11 y GW12 `pending`, sin corridas ni razones de fallo.
- Todos los hashes de implementación y assets locales coinciden con el manifiesto
  original. Esa comprobación precedió a la integración autorizada de Researcher 1.18.0.

ADR-011 y la skill vigente prohíben reescribir la cohorte o ignorar deriva material.
Promover este candidato cambia el hash de `codex-app-server.mjs`: desplegarlo bajo
el contrato actual invalidaría la aceptación. El owner aprobó expresamente la excepción prospectiva; `strategy acceptance amend`
implementa su registro inmutable y sus gates. Falta la prueba viva y aplicar la enmienda.

La excepción propuesta conservaría el manifiesto original y agregaría una revisión
inmutable con actor, razón, aprobación y hashes; mismas GWs, ventanas, cuotas,
criterios y reglas de selección. Rechazaría ventanas iniciadas, cualquier inferencia
previa o evidencia existente. No reinterpretaría GW9 ni borraría errores. Requiere
implementación, tests y validación real independiente antes de promoverse.

## Verificación

`tests/test_research_budget_candidate.py` cubre aviso único, identidad de turno,
consumo exacto incluyendo cacheados, respuesta antes del límite, agente que ignora
el aviso, rechazo RPC, turno incorrecto y finalización concurrente.

Las seis pruebas del candidato y cinco del controlador vigente pasan. La suite
completa terminó con 2295 passed, 1 skipped y 79 deselected en 102,60 s.
`node --check` del candidato y `compileall` del motor también pasan.
No hay prueba pagada del modelo, importación real de brief, despliegue ni nueva
cohorte en este experimento.
