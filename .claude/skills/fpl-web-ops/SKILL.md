---
name: fpl-web-ops
description: "Operar rápidamente la cuenta real de Fantasy Premier League con agent-browser: crear o reemplazar la plantilla, ordenar titulares y banca, asignar capitán y vice, guardar y producir evidencia verificable. Usar solo para ejecutar en la web una decisión FPL ya aprobada o para leer estado privado no expuesto por la API pública."
metadata:
  vertical: mova
  type: skill
  repo: mova-pro-futbol-data-analytics
  updated: 2026-08-20
---

# FPL Web Ops

Ejecuta el acta canónica en `fantasy.premierleague.com` con el Chrome real de Windows.
Esta skill no decide jugadores: recibe una spec o acta aprobada, la monta sin improvisar y
demuestra que quedó persistida.

Cuenta conocida: `losmillosFPL`, `entry_id=3609854`.

## Carga y autorización

Antes de operar:

1. Carga `agent-browser` y su core vigente: `agent-browser skills get core`.
2. En Orbital/WSL carga también `agent-browser-orbital` para levantar el puente CDP.
3. Lee [references/operations.md](references/operations.md) para crear, transferir o editar
   el equipo.
4. Lee [references/recovery.md](references/recovery.md) únicamente si falla CDP, el login,
   una ref o el usuario cambia de pestaña.
5. Obtén la fuente de verdad: spec/acta con 15 jugadores, XI, banca, capitán, vice y chip.

Montar o transferir jugadores modifica una cuenta externa: requiere que el usuario lo haya
pedido. No actives chips, confirmes transferencias con coste ni cambies la decisión deportiva
sin autorización explícita.

## Invariantes

- `mova_fpl` es solo lectura. Toda mutación se hace visualmente en el navegador real.
- Nunca escribas contraseña, OTP ni código MFA. El selector de una cuenta Google ya
  autenticada sí puede clicarse; si pide secreto, pausa para el usuario.
- No uses nombres recordados: compara cada jugador, orden y capitanía con la spec.
- Las refs caducan con cualquier render, modal, navegación o cambio de pestaña.
- Antes de cada interacción por ref: ancla la pestaña FPL y toma un snapshot fresco.
- En la cancha dinámica, identifica jugadores por texto dentro de
  `button[data-pitch-element=true]`; no dependas de una ref antigua.
- Los checkboxes de capitán/vice se operan con `focus` + `Space` y se verifican.
- Un cambio no existe en servidor hasta pulsar **Guardar equipo** o confirmar la plantilla.
- El éxito exige: mensaje de guardado, recarga, segunda comparación y captura completa.

## Ruta rápida

### 1. Anclar la sesión

```bash
export PATH=/home/jzuluaga/.nvm/versions/node/v22.17.0/bin:$PATH
agent-browser connect 9222
agent-browser open https://fantasy.premierleague.com/es/my-team
agent-browser tab
```

Registra el tab estable de FPL, por ejemplo `t1`. Desde ese momento, toda unidad de trabajo
empieza así:

```bash
agent-browser connect 9222 >/dev/null
agent-browser tab t1 >/dev/null
agent-browser snapshot -i
```

No ejecutes `tab t1` y luego reutilices refs de un snapshot anterior: el cambio de pestaña
las invalida.

### 2. Ejecutar por bloques verificables

Orden recomendado:

1. Plantilla o transferencias: completar los 15 y confirmar el modal solo después de comparar.
2. XI y formación: hacer swaps banca↔campo.
3. Orden de banca: portero, suplente 1, 2 y 3.
4. Capitán y vicecapitán.
5. Chip, únicamente si la spec lo ordena y está autorizado.
6. Snapshot final contra la spec.
7. **Guardar equipo**.

Mantén cada bloque corto: interacción → espera específica → snapshot → comparación. No
encadenes muchos clicks ciegos.

### 3. Cerrar con evidencia

Después de guardar:

```bash
agent-browser wait --text "Equipo guardado"
agent-browser reload
agent-browser wait --load domcontentloaded
agent-browser snapshot -i > /tmp/fpl-persisted.txt
agent-browser screenshot --full /ruta/absoluta/gwNN_final_mounted.png
sha256sum /ruta/absoluta/gwNN_final_mounted.png
```

La recarga debe mostrar:

- los 15 jugadores correctos;
- XI y formación correctos;
- badges de capitán y vice correctos;
- banca en orden exacto;
- presupuesto y banco esperados;
- ningún botón **Guardar equipo** por cambios pendientes;
- chip correcto o ninguno.

Completa la evidencia con lecturas públicas, cuando estén disponibles:

```python
from mova_fpl.data import live
live.team(3609854)
live.team_history(3609854)
```

El endpoint público de picks puede devolver 404 antes del deadline; la verificación visual
autenticada es entonces la evidencia canónica.

## Criterio de parada

Detente y reporta antes de confirmar si:

- el modal no coincide exactamente con la spec;
- aparece un coste en puntos no aprobado;
- FPL cambió precio, disponibilidad o fixture de forma material;
- se requiere contraseña/MFA;
- falta un jugador o la plantilla viola presupuesto/club/posición;
- no puedes demostrar persistencia tras recargar.
