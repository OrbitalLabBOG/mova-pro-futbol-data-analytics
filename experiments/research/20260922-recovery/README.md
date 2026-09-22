# Diagnóstico pareado de research — 22/09/2026

Se reutilizó el request, resultado y evidencia de
`research_73c7968ad6c2c3c71c4fc22fc7515a6d`, importado el 20/09 a las 23:30 UTC.
No hubo llamadas LLM, nuevos fetches web, encolados ni cambios del ledger.
El runtime que ejecutó el replay fue `e15cce7`. Es un experimento del validador,
no una comparación de modelos ni una demostración de ahorro de tokens.

## Resultado

| Misma entrada y fecha original | Policy 2026.09.1 | Policy 2026.09.2 |
| --- | ---: | ---: |
| Señales aceptadas | 2 | 0 |
| Señales candidatas | 6 | 8 |
| Cobertura verificada | 3/25 (12%) | 1/25 (4%) |
| Conflictos no resueltos | 1 | 1 |

Cinco de seis documentos tenían fetch verificado y artefactos cuyos hashes coinciden;
solo dos conservaban fecha de publicación verificada. Cuatro señales no sostienen
identidad/claim y dos carecen de fecha verificada. Las dos aceptadas por la política
anterior son demasiado antiguas para su claim bajo la nueva política.
La reproducción de los contadores originales es un control del replay; no se
reescribió el resultado histórico con los contadores de la nueva política.

[policy-replay.json](policy-replay.json) conserva hashes, fecha y agregados.
[replay.py](replay.py) falla ante request alterado, evidencia alterada o incompleta,
y exige la misma fecha de importación para todos los documentos. Para reproducir
con los artefactos privados del VPS, desde el checkout local:

```bash
ssh ubuntu@72.60.245.2 \
  'sudo -n docker exec -i mova-fpl-api-1 python - research_73c7968ad6c2c3c71c4fc22fc7515a6d' \
  < experiments/research/20260922-recovery/replay.py
```

La lectura de documentos usa la primera página de 100; si deja de contener todos
los documentos del run, el script falla explícitamente. Los artefactos privados y
extractos fuente no se incluyen en Git. Para preservación prolongada debe retenerse
el conjunto sellado según la política operativa de backups.

## Contexto, herramientas y tokens observados

El receipt de `gpt-5.6-luna` registra 162301 ms: 246505 tokens de entrada y
7074 de salida (253579 total). El evento de cierre desglosa 177152 tokens de
entrada cacheados; no se restan del límite lógico vigente. El request archivado
ocupa 63465 bytes: tamaño de archivo no equivale a tokens, y los tokens de entrada
acumulan el trabajo del turno, no sólo ese primer request.

El log tiene cuatro operaciones `web_search` completadas: dos acciones `search`
con ocho queries declaradas en total y dos acciones `other`. No afirmar que hubo
sólo cuatro queries ni que sus ocho queries devolvieron evidencia útil. Hay tres
items `agent_message`, un turno completado y un item `error` que avisa de
abreviación del catálogo de skills para caber en 2% del contexto; el receipt
final fue `succeeded`. No demuestra un fallo de búsqueda ni explica por sí solo
el gasto. El worker ya usa `--ignore-user-config`, `--ignore-rules` y desactiva
plugins, apps, shell, browser y multi-agent: no proponer esas opciones como si
faltaran. Hay que medir el contexto efectivo de la versión de Codex empleada.

[usage.json](usage.json) conserva agregados y hash del log. Comparar proveedores
exige separar tokens lógicos, caché, cuota de suscripción y factura monetaria;
esta corrida no acredita que OpenRouter sea más barato o mejor que Codex.

## Factibilidad del alcance

El request tenía 25 sujetos de 14 clubes, cero hints reutilizables y límite broad
de 10 documentos/8 consultas. Bajo el supuesto favorable de que un documento de
club cubra a todos sus jugadores y sin documentos multiclub, diez documentos cubren
como máximo 21/25 (84%); harían falta doce para alcanzar 90%. Refresh y final tienen
límites de ocho y seis documentos: máximos condicionales 76% y 64%.
[feasibility.json](feasibility.json) conserva el cálculo y el supuesto.
Esto no demuestra imposibilidad general: una fuente multiclub puede cubrir más.

El prompt ya pide radar global, agrupación por club y cobertura prioritaria. Añadir
esas mismas frases no resuelve la falta de evidencia. Tampoco subir tokens demuestra
utilidad: la corrida original consumió 253579 frente al límite 160000.

## Siguiente entrega de AC-02

1. Presupuestar alcance antes de encolar: sujetos/clubes/hints válidos frente a
   documentos, consultas, tiempo y tokens. Registrar capacidad insuficiente;
   nunca convertir `not_checked` en cobertura ni bajar umbrales.
2. Buscar evidencia reciente con fecha comprobable, identidad y claim precisos;
   medir aceptación por documento y motivo de rechazo. Revalidar hints, no
   extender su TTL por reutilizarlos. Mantener radar global acotado.
3. Ensayar una variante de adquisición con igual request y presupuesto, artefactos
   separados y sin importarla como evidencia viva. Comparar sujetos verificados,
   conflictos, tokens por sujeto útil, tiempo y decisiones materialmente cambiadas.
4. Definir y versionar la ventana longitudinal del gate: hoy `research_coverage`
   limita runs antes de agrupar por GW y exige que todas las GWs medidas en esa
   página pasen. El volumen de reintentos puede cambiar el denominador. Separar
   paginación de presentación y cohorte de aceptación, con pruebas adversariales;
   no reinterpretar silenciosamente el gate como «tres GWs recientes».

El replay no cierra el overrun: sigue faltando un follow-up equivalente, liquidado
y dentro de presupuesto. AC-02 sigue abierto y no habilita promoción.

## Iteración de contexto y paginación

`context-replay.json` reproduce el nuevo diagnóstico sobre el request archivado:
63464 bytes JSON antes y 64677 después (incluye el plan de adquisición), 667 jugadores
en catálogo, 25 en foco y 20 señales de GWs anteriores. No se elimina información.
El catálogo ya estaba codificado como filas compactas; no hay ahorro demostrado.
La estimación reproduce 21 sujetos con diez documentos de club y doce documentos
para llegar a 23 sujetos. Ningún hint cuenta como evidencia vigente.

Las pruebas adversariales verifican tres GWs con una fallida y 25 reintentos recientes:
el gate falla igual con límites de presentación 1, 12, 20 y 100. Un worker con Codex
simulado verifica que el hash de contexto corresponde exactamente al JSON enviado y
que conserva receipts de intento fallido. No consume tokens ni acredita calidad LLM.
La validación interactiva y el ensayo pareado del agente siguen abiertos en AC-02.

### Verificación y despliegue de esta entrega

Código `85365e8`, PR #177; CI test success. Suite local: **1805 passed, 1 skipped,
79 deselected**. Compileall y node --check pasan; Compose config y smoke de la
imagen research pasan en VPS. API desplegado healthy con imagen
`sha256:e618dea3703ec4cd4246384c2e16a04f5cead6fd28d0c0e02810fe2c6d6e7819`;
research `sha256:a1e269948b657a4a05cb0d01b153d9d7d48e97f88d2f7cb2dece9cbdd04b0f64`.

El primer probe encontró connection reset durante el arranque y el trap restauró
`ccf21d3`. La segunda ejecución esperó Docker healthy antes del GET readyz y pasó.
Rollback de configuración conservado en
`/opt/orbital/backups/mova-fpl/release-20260922-research-85365e8/` con SHA previo;
no hubo migraciones. Doctor sin red: 23 PASS, 1 WARN por chequeo público omitido,
0 FAIL. Autoridad A0/shadow intacta. API reporta 4 GWs medidas, 0 passing.
Supabase AC-02 continúa in_progress, revisión 6. No se ejecutó una nueva inferencia.

Doctor completo posterior (2026-09-22T17:10:54+00:00): **24 PASS, 0 WARN, 0 FAIL**,
incluido GET público. No se requiere un nuevo despliegue para esta nota documental.
