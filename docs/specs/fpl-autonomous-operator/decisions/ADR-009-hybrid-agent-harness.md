---
type: decision
name: "ADR-009 — Coordinador delgado con backends híbridos"
created: 2026-08-22
updated: 2026-08-22
tags: [mova, fpl, adr, agentic, codex, openrouter]
status: proposed
---

# ADR-009 — Coordinador delgado con backends híbridos

## Contexto

MOVA necesita interpretar noticias abiertas sin entregar el control de la temporada a un
LLM. El POC del VPS demostró que Codex CLI puede reutilizar autenticación ChatGPT, ejecutar
búsqueda web no interactiva y producir JSON validado. También mostró un consumo alto para
una consulta pequeña. Orbital dispone además de OpenRouter para tareas API controlables.

## Decisión propuesta

Construir solo un coordinador delgado y agnóstico al proveedor, no un framework de agentes. OpenRouter
será inferencia estructurada rutinaria y `codex exec` un job agéntico autocontenido para
discovery profundo y crítica. El orquestador determinista conserva deadline, idempotencia,
policy, decisión y ejecución.

El worker de investigación corre en proceso/container separado, recibe un request package inmutable y
devuelve un result package validado. No accede a `ops.db`, browser profile, cookies FPL,
Docker socket ni executor.

La implementación usa Python async explícito sobre el ledger existente. LangGraph queda
fuera de alcance porque duplicaría estado, checkpointer, retries y autoridad. App Server y
Codex SDK también quedan fuera del MVP: la documentación oficial sitúa `codex exec` como la
integración adecuada para scripts y background jobs acotados. Cualquier cambio hacia un
agente persistente requiere una ADR nueva.

## Alternativas

| Opción | Evaluación |
| --- | --- |
| Codex como manager end-to-end | descarta autoridad, reproducibilidad y aislamiento; auth/cuotas no son control plane |
| agente OpenRouter end-to-end | mejor control económico, pero obliga a reconstruir search/tools y conserva el problema de autoridad |
| solo reglas/collectors | determinista, insuficiente para texto abierto y contradicciones |
| LangGraph | aporta branching/checkpoints ya resueltos por `ops.db`; complejidad duplicada |
| plataforma genérica Orbital desde el día uno | reutilizable, pero prematura antes de estabilizar contratos FPL |
| coordinador MOVA híbrido con interfaces extraíbles | seleccionado: menor acoplamiento y aprendizaje medible |

## Consecuencias

- se implementan interfaces pequeñas `ResearchBackend`, `DiscoveryAdapter` y `FetchAdapter`;
- modelo/proveedor se eligen por task policy versionada;
- se añaden ledger, schemas, quotas, artifacts e incidentes agénticos;
- Codex auth se trata como secreto renovable y su fallo no detiene el motor base;
- Firecrawl es opcional y browser es excepción de lectura;
- ninguna salida LLM alcanza el executor sin policy, optimizer y gates;
- el coordinador puede extraerse como servicio Orbital común después de demostrar dos casos de
  uso y contratos estables.

## Condición de revisión

Revisar esta ADR después de tres GWs/rehearsals shadow o si el costo/latencia de Codex,
OpenRouter o extracción impide cumplir el cutoff T-70m.
