---
type: decision
name: "ADR-009 — Coordinador delgado con Pydantic AI y Codex"
created: 2026-08-22
updated: 2026-08-22
tags: [mova, fpl, adr, agentic, codex, openrouter, pydantic-ai]
status: proposed
---

# ADR-009 — Coordinador delgado con Pydantic AI y Codex

## Contexto

MOVA necesita interpretar noticias abiertas sin entregar el control de la temporada a un
LLM. El POC del VPS demostró que Codex CLI puede reutilizar autenticación ChatGPT, ejecutar
búsqueda web no interactiva y producir JSON validado. También mostró un consumo alto para
una consulta pequeña. Orbital dispone además de OpenRouter para tareas API controlables.

## Decisión propuesta

Construir un coordinador exterior delgado y agnóstico al proveedor. Usar Pydantic AI core
2.x fijado por versión como runner interior de la inferencia rutinaria sobre OpenRouter y
`codex exec` como job agéntico autocontenido para discovery profundo y crítica. El
orquestador determinista conserva deadline, idempotencia, policy, decisión y ejecución.

El worker de investigación corre en proceso/container separado, recibe un request package inmutable y
devuelve un result package validado. No accede a `ops.db`, browser profile, cookies FPL,
Docker socket ni executor.

Pydantic AI aporta provider OpenRouter nativo, outputs Pydantic, tools acotadas, retries,
usage limits y OpenTelemetry; evita implementar a mano un loop de tools. No se adopta el
paquete completo `pydantic-ai-harness` inicialmente: continúa en serie 0.x y sus capas de
research, persistencia y budget duplican responsabilidades actuales.

La implementación exterior usa Python async explícito sobre el ledger existente.
LangGraph, Pydantic Graph, StepPersistence y Vercel Workflow quedan fuera porque
duplicarían estado, checkpointer, retries y autoridad. OpenAI Agents SDK y Vercel AI SDK 7
son suficientes, pero el primero pierde ventaja al operar rutinariamente por OpenRouter y
el segundo añade un runtime TypeScript a un servicio Python. App Server y Codex SDK también
quedan fuera del MVP: `codex exec` ya encaja como job acotado. Cualquier cambio hacia un
agente persistente requiere una ADR nueva.

## Alternativas

| Opción | Evaluación |
| --- | --- |
| Codex como manager end-to-end | descarta autoridad, reproducibilidad y aislamiento; auth/cuotas no son control plane |
| OpenAI Agents SDK | Python maduro y suficiente; menos directo con OpenRouter y sin OpenAI API como control plane actual |
| Vercel AI SDK 7 | muy completo y OpenRouter-native; introduce Node/TypeScript y durabilidad redundante |
| Pydantic AI core + OpenRouter | seleccionado: nativo Python/OpenRouter, tipado y acotable sin nueva state machine |
| Pydantic AI Harness completo | potente, pero pre-1.0 y demasiado amplio para el MVP |
| solo reglas/collectors | determinista, insuficiente para texto abierto y contradicciones |
| LangGraph | aporta branching/checkpoints ya resueltos por `ops.db`; complejidad duplicada |
| plataforma genérica Orbital desde el día uno | reutilizable, pero prematura antes de estabilizar contratos FPL |
| loop HTTP/OpenRouter propio | pequeño al inicio, pero reconstruye tools, validación, retries, usage y trazas |

## Consecuencias

- se implementan interfaces pequeñas `ResearchBackend`, `DiscoveryAdapter` y `FetchAdapter`;
- `PydanticAIResearchBackend` queda como backend rutinario y `CodexExecBackend` como
  especialista;
- modelo/proveedor se eligen por task policy versionada;
- se añaden ledger, schemas, quotas, artifacts e incidentes agénticos;
- Codex auth se trata como secreto renovable y su fallo no detiene el motor base;
- Firecrawl es opcional y browser es excepción de lectura;
- el costo local desconocido nunca habilita trabajo adicional: mandan límites duros de
  requests/tools/tokens/searches y el cap externo de OpenRouter;
- ninguna salida LLM alcanza el executor sin policy, optimizer y gates;
- el coordinador puede extraerse como servicio Orbital común después de demostrar dos casos de
  uso y contratos estables.

## Condición de revisión

Revisar esta ADR después de tres GWs/rehearsals shadow o si el costo/latencia de Codex,
OpenRouter o extracción impide cumplir el cutoff T-70m.
