---
type: decision
name: "ADR-010 — Discovery no equivale a evidencia"
created: 2026-08-22
updated: 2026-08-22
tags: [mova, fpl, adr, research, provenance, security]
status: proposed
---

# ADR-010 — Discovery no equivale a evidencia

## Contexto

OpenRouter y Codex pueden devolver URLs, excerpts y citas durante web search. La forma y los
límites cambian según engine/downstream provider: búsquedas nativas pueden omitir annotations,
ignorar `max_uses` o aplicar filtros de dominio de manera distinta. Además, una cita del
provider no conserva necesariamente los bytes, la fecha de publicación ni un locator que
MOVA pueda reproducir después.

Aceptar directamente esas citas como noticias convertiría la salida del modelo en fuente de
verdad y rompería replay, cutoff, licencias, corroboración y defensa contra prompt injection.

## Decisión

Separar obligatoriamente:

1. **discovery:** query → `DiscoveryCandidate` con URL/citation metadata;
2. **acquisition:** safe fetch determinista → `SourceDocument` con bytes/excerpt, fechas y
   hashes;
3. **extraction:** documento sellado → `ResearchSignal candidate` con locator;
4. **policy:** identidad, tier, TTL, independencia, conflicto y aceptación en código.

Una cita que no pueda recuperarse queda como candidate informativo y nunca produce una
señal aceptada. Search no navega la red privada, no hereda secretos y no habilita tools
operativas.

Para el discovery rutinario OpenRouter se fija un engine no nativo y un número acotado de
resultados. Native search no se usa como control duro inicial porque sus garantías varían.
Codex continúa como especialista, con timeout y cuota por job/GW; su contador de búsquedas
es observado, no una garantía de límite interno.

## Alternativas

| Opción | Evaluación |
| --- | --- |
| aceptar citations del modelo | rápida, pero no reproducible ni suficiente para evidencia |
| browser para toda fuente | costoso, amplio y mezcla sesión/autenticación innecesariamente |
| solo HTTP sin discovery | seguro, pero no encuentra cambios/fuentes nuevas |
| discovery → safe fetch → evidence | seleccionado: separa creatividad de provenance |

## Consecuencias

- se requieren schemas distintos para candidate, document y signal;
- cada accepted signal referencia al menos un `SourceDocument` verificable;
- aumenta una llamada HTTP por URL útil, con dedupe/hash para evitar repetición;
- una fuente dinámica o bloqueada puede degradar cobertura sin inventar evidencia;
- prompt injection se contiene principalmente por least privilege y frontera de tools;
- el engine de search puede cambiar sin cambiar el contrato de evidencia.

## Revisión

Revisar después de tres GWs shadow y un benchmark comparando cobertura, citas recuperables,
latencia y costo entre engines de search.

## Referencias

- [OpenRouter web search plugin](https://openrouter.ai/docs/guides/features/plugins/web-search)
- [Pydantic AI OpenRouter web search](https://pydantic.dev/docs/ai/models/openrouter/)
- [OWASP LLM01 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [OWASP SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
