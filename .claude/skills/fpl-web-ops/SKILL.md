---
name: fpl-web-ops
description: Cómo operar la interfaz web real de Fantasy Premier League (fantasy.premierleague.com) con agent-browser — armar/editar plantilla, capitán, formación, chips, login. Usar cuando haya que introducir el acta del motor en la cuenta real (crear equipo, hacer transferencias, activar un chip) o leer algo que la API pública no expone.
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
  updated: 2026-08-09
---

# FPL Web Ops — operar fantasy.premierleague.com con agent-browser

> Esta skill es específica del **sitio de FPL**. Para el puente WSL→Windows, el modelo de
> refs/snapshots y los patrones genéricos de `agent-browser`, cargar primero
> `agent-browser-orbital` (y la oficial `agent-browser`). Esta documenta solo lo que es
> peculiar de la interfaz de FPL, aprendido armando la plantilla real de la cuenta de Julián
> (equipo "losmillosFPL", GW1 2026/27, `entry_id=3609854`).

**Recordatorio de límite del motor:** `mova_fpl` solo lee (GET). Todo lo que este documento
describe —clicks, formularios, guardar equipo— lo hace una persona a través del navegador
real, nunca el código Python. El acta (`outputs/fpl/.../gwNN_decision.md`) es la guía; el
navegador es el medio para introducirla.

---

## 0. Login — nunca automatizado

FPL usa el login estándar de Premier League (email + contraseña, a veces con verificación
adicional). **No teclear credenciales del usuario bajo ninguna circunstancia** — no es una
limitación de la herramienta, es una regla dura. Patrón:

```bash
agent-browser connect 9222                       # ANTES del primer open (evita headless trap)
agent-browser open https://fantasy.premierleague.com/
agent-browser snapshot -i -c                      # confirmar que se ve el login
```

Y ahí parar: pedirle al usuario que inicie sesión él mismo en el Chrome real (visible), y
esperar a que confirme ("ya inicié sesión") antes de continuar. Recién ahí re-snapshot.

---

## 1. El `entry_id` no existe hasta que se guarda la primera plantilla completa

Antes de armar el equipo, `/api/me/` (endpoint autenticado, solo vía sesión del navegador,
nunca desde nuestro código) devuelve `"entry": null`. Se puede verificar sin tocar
credenciales:

```bash
agent-browser eval "fetch('/api/me/').then(r=>r.json()).then(d=>window.__me=d)"
agent-browser eval "JSON.stringify(window.__me)"   # separar el await de la lectura (ver §6)
```

El `entry_id` (el número que va en `/entry/<ID>/...` y en `FPL_TEAM_ID`) solo aparece
**después** de completar los 15 jugadores y hacer clic en "Ingresar equipo" — ahí la URL
cambia a `/my-team` y `/api/me/` empieza a devolver el entero. No hay atajo: si la cuenta es
nueva, hay que construir la plantilla completa una vez para obtenerlo.

**Verificación cruzada recomendada** (no confiar solo en lo que muestra el navegador): una
vez se tiene el `entry_id`, confirmarlo con el propio código de lectura del motor:

```python
from mova_fpl.data import live
t = live.team(3609854)
t["name"], t["player_first_name"], t["player_last_name"]   # nombre de equipo y dueño
h = live.team_history(3609854)
h["chips"], len(h["current"] or [])                          # [] y 0 antes de jugar GW1
```

---

## 2. Buscador de jugadores: usa el nombre de display de FPL, no el nombre completo

El buscador del selector de plantilla **no** hace fuzzy match sobre nombre completo. Buscar
"Bruno Fernandes" o "Nathan Collins" da cero resultados. FPL usa una convención de display
propia (apellido solo, o abreviaturas tipo "B.Fernandes"):

| Buscar | Encuentra |
|---|---|
| `Fernandes` | B.Fernandes |
| `Pedro` | João Pedro |
| `Dango` | O.Dango |
| `Collins` | Nathan Collins |

**Regla práctica**: buscar por apellido único. Si da cero resultados, probar solo el primer
apellido o el nombre corto que usa la propia acta del motor (el acta ya usa nombres cortos
por diseño — son los de la fuente de datos).

## 3. Los filtros de posición/precio quedan pegados entre búsquedas

Después de fichar a un jugador con el filtro de precio en, por ejemplo, "£12.0m
seleccionadas", la siguiente búsqueda (otro precio) **devuelve cero resultados en
silencio** — no hay error, solo lista vacía. Antes de cada búsqueda nueva:

```bash
agent-browser snapshot -i -c | grep -i "restablecer\|filtrar por"
agent-browser click @eN     # "Restablecer filtros"
```

El filtro de **posición** también puede quedar mal heredado (p.ej. seguir en
"Mediocampistas" al abrir un slot de delantero vacío). Verificar el estado de `Filtrar por`
tras abrir cada slot nuevo y resetear si no coincide con la posición del hueco.

## 4. Casillas (checkboxes) que no responden a `click`

Los checkboxes de T&C, capitán y vicecapitán en FPL a veces no cambian de estado con
`agent-browser click` sobre el label o su wrapper — el click se reporta `✓ Done` pero
`checked` sigue en `false`. Patrón que sí funciona en todos los casos observados:

```bash
agent-browser focus @eN      # foco en el checkbox mismo, no en el label
agent-browser press "Space"
agent-browser snapshot -i -c   # verificar checked=true antes de seguir
```

Aplica a: aceptar términos y condiciones, marcar "Capitán"/"Subcapitán" dentro del modal
"Perfil del jugador".

## 5. Capitán y vicecapitán: vía el modal de perfil, no un badge directo en la cancha

1. Click en el **nombre** del jugador en la cancha (no el escudo/jersey) → abre "Perfil del
   jugador: <Nombre>".
2. Dentro del modal: `focus` + `Space` sobre el checkbox `Capitán` o `Subcapitán` (§4).
3. Cerrar el modal y **re-snapshot fresco** antes de dar por confirmado el cambio — un
   snapshot reciclado puede mostrar el badge `C`/`V` sobre el jugador equivocado porque los
   refs quedaron de un estado anterior. Confirmar contra el propio heading del modal
   (`"Perfil del jugador: <Nombre esperado>"` + `checked=true`), no contra fragmentos de
   snapshot viejos.

## 6. Cambiar la formación (banca ↔ titular) es un flujo de DOS clics, no uno

No existe un botón único "swap". Clicar directamente el nombre/jersey del titular objetivo
**no** completa nada por sí solo — solo abre su propio perfil, sin relación con el
suplente. El flujo real:

1. Abrir el perfil del **suplente** que va a entrar (click en su nombre en la banca).
2. Click en **"Suplente"** dentro de ese perfil → activa "modo selección" (señal visual:
   pierde las etiquetas de precio, tinte verde sobre la cancha). El modal se cierra pero el
   estado de selección queda activo.
3. Localizar al **titular objetivo** que va a salir. En este punto, los clicks por `@ref`
   estándar sobre su elemento en la cancha son poco confiables (a veces abren un perfil
   viejo/equivocado por el estado dinámico de la cancha). Usar JS directo:
   ```bash
   agent-browser eval "(function(){
     const btns = document.querySelectorAll('button[data-pitch-element=\"true\"]');
     const target = Array.from(btns).find(b => b.textContent.includes('Thiaw'));
     if (target) target.click();
     return !!target;
   })()"
   ```
   (Envolver siempre en IIFE — ver nota de `const` abajo.) Esto abre el perfil del titular
   objetivo.
4. Click en **"Suplente"** dentro de ESE perfil (el del titular objetivo) → recién ahí se
   completa el intercambio. El botón "Cambiar jugador" que aparece al hacer hover NO
   completa el swap por sí solo en la práctica — usar el flujo de dos perfiles descrito.
5. Screenshot final para verificar visualmente la XI resultante contra el acta.

## 7. `agent-browser eval` — dos trampas de JS

- **`const`/`let` persisten entre llamadas** en el mismo contexto de página. Un segundo
  `eval` que redeclare la misma variable (`const btns = ...`) lanza
  `SyntaxError: Identifier 'btns' has already been declared`. Envolver cada snippet en una
  IIFE: `(function(){ const x = ...; return x; })()`.
- **`await` de nivel superior no funciona** (`SyntaxError: await is only valid in async
  functions`). Para leer una respuesta `fetch`, encadenar `.then()` y guardar el resultado
  en `window`, y leerlo en una llamada `eval` separada:
  ```bash
  agent-browser eval "fetch('/api/me/').then(r=>r.json()).then(d=>window.__me=d)"
  agent-browser eval "JSON.stringify(window.__me)"
  ```

## 8. El endpoint de picks está bloqueado antes del deadline — es esperado, no un bug

`GET /api/entry/{id}/event/{gw}/picks/` devuelve `{"detail":"Not found."}` cuando se
consulta públicamente para la jornada **en curso**, antes de que cierre. FPL oculta a
propósito las alineaciones de la jornada activa para que nadie copie plantillas ajenas antes
del deadline. No es una falla de `data/sources.py` ni algo que reintentar — es el
comportamiento correcto del sitio. Se puede seguir inspeccionando el estado vía la propia UI
del navegador mientras tanto.

## 9. Verificación final: comparar contra el acta, no contra la memoria

Después de guardar ("Guardar equipo" / "Ingresar equipo"), no dar la tarea por cerrada solo
con la confirmación visual del sitio. Cerrar cualquier modal promocional que aparezca (FPL
suele ofrecer generadores de escudo u otras promos no relacionadas — ignorar, solo cerrar) y
verificar dos veces:

1. **Screenshot** de la cancha final, comparado campo a campo contra
   `outputs/fpl/<temporada>/gwNN_decision.md` (formación, titulares, capitán, vice, banca en
   orden).
2. **Lectura de solo-GET del propio motor** (no solo lo que muestra el navegador):
   ```python
   from mova_fpl.data import live
   live.team(entry_id)            # nombre, dueño
   live.team_history(entry_id)    # chips (debe ser [] si es plantilla nueva sin jugar aún)
   ```

Si hay una discrepancia menor (p.ej. orden de banca no coincide exactamente con la
prioridad de xP del acta), **declararla explícitamente** en vez de callarla — no es
necesariamente bloqueante, pero el usuario debe saberlo.

---

## Checklist rápido para armar/editar un equipo

```bash
agent-browser connect 9222
agent-browser open https://fantasy.premierleague.com/
# ... esperar login manual del usuario si hace falta ...
agent-browser snapshot -i -c
# por cada slot vacío: click slot -> buscar apellido -> Restablecer filtros si venía sucio -> fichar
# capitán/vice: click nombre -> focus checkbox -> Space -> verificar en snapshot fresco
# formación: perfil suplente -> "Suplente" -> JS click sobre titular objetivo -> "Suplente" en su perfil
# Guardar equipo / Ingresar equipo -> cerrar promos -> screenshot + verificación de solo-lectura
```
