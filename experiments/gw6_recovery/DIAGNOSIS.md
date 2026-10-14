# Diagnóstico posterior a GW6

Corte de evidencia: auditoría local del 13 de octubre de 2026, release observado
9e1ff83. Este documento distingue hechos reproducidos de hipótesis; no es una
nueva lectura del VPS ni una declaración de que los fixes estén desplegados.

## Qué falló y cuánto permite afirmar

1. **Orquestación, fallo demostrado:** contextos de deliberación de Oct9 10:00/
   11:00 UTC llegaron Oct10 01:44/01:50 UTC. El autorizador comprobaba integridad,
   presupuesto y deadline, sin contrastar contexto material actual. La reparación
   local añade ese contraste antes de emitir permiso. No demuestra que toda pérdida
   deportiva venga de esa demora ni reconstruye hechos que el agente nunca recibió.
2. **Research, cobertura insuficiente:** el informe previo observó 3/25 sujetos
   cubiertos y ninguno de los diez candidatos del modelo. Importación exitosa
   describía transporte, no evidencia útil. La reparación separa ambos estados.
   No se relajan umbrales para hacer pasar el resultado.
3. **Cierre y aprendizaje incompletos:** GW6 no tiene ejecución atestada y su review
   no existe. La última ejecución verificada era GW5. El cierre automático que exige
   esa evidencia está cumpliendo su contrato; falta reconciliación verificable, no
   un parche para darlo por aprobado. Picks públicos no prueban cómo se ejecutó.
4. **Conflicto antiguo:** la fecha de publicación desconocida y señales vencidas no
   convierten el conflicto de Haaland en una lesión actual ni en alta médica.
   Hace falta adjudicación trazable; borrarlo por TTL sería un fallo de autoridad.
5. **Modelo, hipótesis seria:** las tasas individuales incluyen temporada anterior
   y jornadas cerradas, pero no decaen por recencia. Las nuevas jornadas sí entran.
   Para Bruno, antes de GW6 solo 12.8% de los minutos usados eran de esta temporada;
   después, 15.0%. El pico de GW2 (23 puntos, 2.02 xG) sigue influyendo y los cuatro
   últimos partidos suman 0.48 xG. Probar recencia y estabilidad por rol es razonable;
   no basta con forzar su exclusión. La ablación de xP completa sigue sin ejecutarse.
6. **Chips, política sin justificación cuantitativa suficiente:** conservarlos por
   opcionalidad no sustituye una valoración de calendario, inventario y caducidad.
   BB habría sumado 11 puntos en GW6; ese contrafactual aislado no prueba que gastarlo
   fuera óptimo antes del deadline ni mejor en toda la temporada. Medirlo en replay
   secuencial, con las mismas reglas de disponibilidad y vencimiento.

## Qué descarta el replay ya hecho

El scorer coincidió con los 667 jugadores oficiales. El replay H1 con proyecciones
selladas y precios previos recuperó la misma alternativa primaria y resultado
óptimo del solver. No hay evidencia aquí de un error aritmético ni de un MILP que
ignorara sus propias entradas.

El equipo hizo 44 frente a una media de 58. La alternativa sin cambios también
habría hecho 44: la mejora de XI fue compensada por el capitán. Con el mismo XI,
Haaland capitán daba 49 y Mbeumo 51. Son atribuciones retrospectivas, no nuevas
predicciones. En cinco jornadas expuestas, las políticas sobre el equipo realmente
poseído sumaron MOVA 355, ep_next 353, form 334 y ppg 331. Esto no simula compras,
ventas o chips de políticas independientes ni demuestra superioridad general.

El ranking global parecía fuerte por separar a quienes juegan de quienes no:
Spearman GW6 .741 en todo el mercado, pero .079 en los 138 jugadores con P60>=.75.
La precisión entre titulares es el diagnóstico más relevante para la selección;
una sola jornada no permite estimar su fiabilidad. Incluir esta estratificación en
los reportes de desarrollo, sin seleccionar el grupo por minutos reales futuros.

## Evidencia reproducible

Directorio de artefactos saneados fuera del repositorio:
`/home/julianzu/code/artifacts/mova-fpl/gw06-audit-20261013/`.
Ver `informe.html`, `milp-replay.json`, `benchmarks.json`, `bruno-findings.json`,
`envelopes.json`, `research.json`, `team-state-history.json` y scripts de replay.
El sellado del protocolo registra hashes, no transforma estos datos ya observados
en evidencia prospectiva. No ejecutar estos replays dentro del contenedor API.
