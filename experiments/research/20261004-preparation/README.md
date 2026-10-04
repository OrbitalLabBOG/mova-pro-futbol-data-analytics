---
type: experiment
name: MOVA FPL — preparación pareada y auditoría de conflictos
updated: 2026-10-04
status: prepared-deferred-budget
---

# Preparación 1.10.0 / 1.12.0

La [preparación JSON](pair-preparation.json) se calculó sin encolar ni reservar tokens,
con el request original sellado del 22/09 y presupuesto vivo del 04/10 UTC. El request
histórico permite fijar el protocolo; no acredita un manifest fresco para una corrida
predeadline. Se registran sólo hashes, límites y contadores, nunca plantilla o payload privado.

## Protocolo fijado

- Baseline 1.10.0 y candidato 1.12.0; mismos modelo/esfuerzo, scope, calidad, timeout,
  guard, contrato de salida, implementación y método de fuentes. Ambas versiones
  existen en el registro; activa 1.10.0.
- Las diferencias deliberadas son agenda multi_branch → focus_completion y
  distribución club_first_pass. El experimento mide **el conjunto** de cambios;
  para aislar distribución, preparar después 1.11.0 / 1.12.0.
- Sellar una sola entrada fresca para los dos brazos. Conservar request, contexto,
  resultados, evaluación independiente y receipts finales originales. Una tentativa
  completa por brazo; fallos no se ocultan escogiendo sólo el intento favorable.
- Presupuesto máximo 1M por brazo y preservar otro job de 1M/una utilización para
  operación. Se requieren 3M tokens y tres usos disponibles tanto en GW como mes.
  GW disponible: 2.310.934; faltan 689.066. Reservar inicialmente 500k no reduce
  exposición máxima. No aumentar allowances ni activar el par automáticamente.
- Antes de ejecutar, volver a consultar presupuesto/cola, comprobar reservas
  huérfanas y ventana y sellar manifest nuevo. La preparación no es reserva atómica:
  el ledger vuelve a autorizar cada trabajo. El guard de tokens es reactivo.
- Fetches secuenciales en vivo no equivalen a una web congelada ni diseño aleatorio;
  registrar orden, horas y URLs. No atribuir diferencias a un único cambio de prompt.

## Medición y aceptación

Usar `experiments/research/compare_agents.py` sobre archivos reales de los dos runs.
Reporta sujetos verificados, cobertura/evidencia global y fuera del foco, documentos
con fecha, conflictos, errores de tools, tokens y duración. Para revisión de candidato:
mejora >=2 sujetos, conservación de todos los sujetos con señales aceptadas del
baseline, sin aumento de conflictos, herramientas/evidencia utilizadas, recibos
finales completos no negativos, dentro de límites y modelo usado coincidente con
release. Nada de ello promociona el agente ni suma las tres GWs operativas.

La preparación se reproduce con artefactos privados del operador:

```bash
python experiments/research/prepare_comparison.py \
  --request /ruta/privada/run.request.json --cost-report /ruta/privada/cost-report.json
```

El CLI sólo prepara metadata; nunca consulta red, escribe el ledger o encola agentes.
Un estado deferred describe incompatibilidad/capacidad insuficiente, no una corrida fallida.

## Revisión de conflictos originales

La [auditoría fechada](conflict-audit.json) consultó los endpoints de sólo lectura
(limit 500) y comprobó SHA físico, extracto y provenance de los documentos originales
bajo la raíz de evidence. Sin fetch web nuevo, resolución ni promoción de señales.

| Conflicto | Hallazgo | Acción pendiente |
| --- | --- | --- |
| Haaland GW6 | Dos artefactos/fragmentos íntegros, sin publicación verificada | Establecer período original de ambos; no inferir alta médica |
| Haaland GW4 | Artefacto íntegro, fecha declarada no verificada | Conciliar período del contenido con publicación original |
| Guehi GW2 | Dos documentos legacy_unverified sin extractos ni artefactos | Recuperar originales verificables o mantener incertidumbre |
| Watkins GW2 | Documento legacy_unverified sin extracto ni artefacto | Recuperar original y revisar semántica; entrenamiento no prueba disponibilidad |

Auditoría reutilizable:

```bash
python experiments/research/audit_conflicts.py \
  --inventory /ruta/privada/inventory.json --evidence-root /ruta/privada/evidence
```

Inventory contiene arrays `conflicts` y `documents` de la API. El límite/truncación
puede dejar documentos ausentes: el auditor falla conservadoramente y pide recuperar
inventario. Hash/fetch/fecha verificados permiten revisar, no prueban compatibilidad
semántica. Una noticia actual nunca reconstruye evidencia perdida del run histórico.

## Alcance de esta entrega

Tooling y reportes de preparación; cero inferencias, reservas, escrituras FPL o cambios
de autoridad. La guía de recuperación del workflow requiere el siguiente release
para aparecer en el VPS. Runtime observado 4917df0; código integrado no implica deploy.
No se ejecutaron ni añadieron pruebas locales en esta iteración. CI se registra en PR.
