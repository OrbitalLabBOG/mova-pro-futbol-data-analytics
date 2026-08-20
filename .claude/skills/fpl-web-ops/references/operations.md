# Operaciones rápidas en FPL

Usa este runbook después de cargar `fpl-web-ops`. Los textos pueden cambiar de idioma; busca
la intención equivalente y valida el resultado, no una ref fija.

## Crear o reemplazar la plantilla

### Transferencias masivas

1. Abre `/es/transfers` y ancla el tab FPL.
2. Retira únicamente los jugadores que no aparecen en la spec aprobada.
3. Añade cada reemplazo por el nombre corto de FPL, preferentemente apellido único.
4. Antes de una búsqueda nueva, restablece filtros de posición/precio si la lista sale vacía.
5. Verifica 2 GKP, 5 DEF, 5 MID, 3 FWD; máximo 3 por club; presupuesto no negativo.
6. Pulsa **Realizar transferencias**.
7. En el modal final compara uno a uno salidas, entradas y coste en puntos.
8. Confirma solamente si coincide con la spec y el coste está autorizado.

El buscador usa nombres de display: `Fernandes` encuentra `B.Fernandes`; `Pedro` encuentra
`João Pedro`. Si un nombre completo devuelve cero, usa el apellido distintivo.

### Plantilla inicial

Abre cada slot vacío, resetea filtros heredados, busca por apellido, selecciona el jugador y
comprueba el contador. El `entry_id` solo nace después de completar y confirmar los 15.

## Abrir un jugador de forma robusta

En la cancha, evita refs viejas. Usa una IIFE y una cadena distintiva:

```bash
agent-browser eval "(function(){
  const p=Array.from(document.querySelectorAll('button[data-pitch-element=true]'))
    .find(x=>x.textContent.includes('Haaland'));
  if (p) p.click();
  return !!p;
})()"
agent-browser snapshot -i
```

Confirma que el modal diga `Perfil del jugador: <jugador esperado>` antes de actuar.

## Swap banca ↔ titular

La operación real usa dos perfiles:

1. Abre el suplente que entra.
2. En su perfil pulsa **Suplente**; esto activa el modo selección.
3. Localiza por JS al titular que sale y abre su perfil.
4. Confirma que el heading corresponde al titular objetivo.
5. Pulsa **Suplente** en ese segundo perfil.
6. Toma snapshot y verifica que ambos cambiaron de ubicación.

Si el segundo modal muestra **Cancelar** en vez de **Suplente**, el swap no está listo para
confirmarse. Cierra/cancela, reancla el tab, inspecciona posiciones y repite desde el perfil
del suplente. Nunca adivines el estado.

## Ordenar la banca

El mismo flujo intercambia posiciones entre suplentes de campo:

1. Abre el suplente que debe moverse.
2. Pulsa **Suplente**.
3. Abre por JS el jugador que ocupa la posición objetivo.
4. Pulsa **Suplente** en el segundo perfil.
5. Verifica headings `1.`, `2.`, `3.` y los nombres asociados.

Ordena con el mínimo de swaps; no muevas el portero salvo que cambie el GKP titular.

## Capitán y vice

1. Abre el perfil del capitán por JS.
2. Verifica el heading del modal.
3. En el checkbox **Capitán**, usa `focus @ref` y `press Space`.
4. Repite con el vice y **Subcapitán**.
5. Cierra el modal y toma snapshot fresco.
6. Comprueba que los badges siguen inmediatamente al jugador esperado en el árbol.

No confíes en `click` sobre el label: puede devolver éxito sin cambiar `checked`.

## Chips

No pulses **Jugar** por exploración. Si la spec autoriza un chip:

1. Verifica jornada y deadline.
2. Pulsa el chip indicado.
3. Lee el modal completo y muestra preview si hay confirmación adicional.
4. Confirma una sola vez.
5. Recarga y verifica su estado activo.

## Guardar sin perder el trabajo

Antes de guardar, genera un snapshot fresco y compara la cancha completa con la spec. Luego:

1. Localiza **Guardar equipo** en ese snapshot actual.
2. Pulsa el botón sin cambiar de tab entre snapshot y click.
3. Espera el texto **Equipo guardado**.
4. Recarga `/es/my-team`.
5. Comprueba que no reapareció la configuración automática anterior.
6. Captura `--full` usando ruta absoluta y calcula SHA-256.

Una captura anterior al guardado no prueba persistencia.
