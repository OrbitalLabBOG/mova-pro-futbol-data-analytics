# Investigación de GW6 y recuperación causal

Estado: preparación local; no ejecutado ni desplegado. El protocolo JSON fija
cuatro brazos antes de comparar nuevas variantes. GW2–6 de 2026-27 ya se
inspeccionaron: sirven para desarrollar hipótesis, jamás como holdout limpio.
La jornada en curso solo produce resultados provisionales; no permite declarar
un ganador ni cambiar pesos automáticamente. Ocho apariciones de semivida no
son ocho gameweeks: jugadores sin minutos y dobles jornadas alteran la unidad.

Reutilizar `experiments.long_horizon` y `fit_temporal_fold`; no cargar points
1.1.0, entrenado hasta 2025-26, para afirmar resultados causales de esa temporada.
El primer experimento cambia únicamente recencia individual; fixture, minutos,
modelo, universo, optimizador, restricciones y política de chips permanecen
idénticos en ambos brazos. Un cambio de fixture o chips exige otro experimento.
No se ha conectado todavía este protocolo a un ejecutor de los cuatro brazos.

Antes de ejecutar, guardar fuera del repositorio un manifiesto con hash del
protocolo, commit, modelos, datos, precios, snapshots y sus cortes de información.
Cada fold debe tener entrenamiento anterior al objetivo. Datos reconstruidos con
calendario definitivo deben llevar esa limitación; no equivalen a snapshots vivos.
Si falta un snapshot o inventario de chips no se sustituye por el estado actual.

Separar dos pruebas: (1) mismo equipo poseído, XI/capitán sin transferencias;
(2) replay secuencial, cada brazo arrastra sus compras, ventas, precios, banco,
transferencias, hits y chips. En (2), puntos netos pareados contra control es la
métrica principal. Publicar todos los brazos, errores, fallos y dispersión por
jornada; no escoger jornadas, jugadores o semillas después del resultado.

Tras desarrollo, congelar un único candidato y sus hashes antes del primer
resultado futuro. Observar al menos tres jornadas cerradas es un mínimo operativo,
no prueba estadística de superioridad. Ampliar el seguimiento si la incertidumbre
no permite distinguir mejora de varianza. Reutilizar el settlement con GET oficial,
`finished + data_checked` y scoring de autosubs/capitán del laboratorio existente.
No reutilizar una temporada ya abierta como holdout por cambiarle el nombre.

## Diagnóstico que motiva las reparaciones

- La cola admitía llamadas con contexto material antiguo. El autorizador ahora
  compara el request sellado contra el envelope actual y la última plantilla.
  IDs nuevos sin cambio material no generan por sí solos un bloqueo.
- Importar research no prueba cobertura suficiente. El estado expone por separado
  procesamiento y calidad; calidad insuficiente o no medida degrada el servicio.
- Un conflicto vencido no demuestra disponibilidad: conservar el gate hasta
  resolverlo con evidencia verificable y actor explícito.
- GW6 carece de ejecución atestada para el cierre autónomo. No fabricar esa
  atestación con picks públicos retrospectivos ni marcar el cierre como logrado.
- El peso de Bruno mezcla historia y temporada sin decaimiento individual. Es
  una hipótesis a contrastar, no un error demostrado por una mala jornada.

Limitaciones pendientes: los requests obsoletos quedan bloqueados y conservan
su reserva. Falta una cancelación/reemplazo transaccional que pruebe ausencia de
cualquier autorización o intento antes de devolver presupuesto; un refund genérico
podría ocultar gasto real. La revalidación prepermiso no es un lock contra cambios
posteriores durante la llamada. Los resultados siguen siendo asesores sellados,
sin autoridad para escribir equipo ni promover autonomía.

Ejecutar replays en proceso local aislado con límites de RAM/CPU. Nunca dentro
del contenedor de la API de producción: una prueba anterior agotó su cgroup.

Sellado reproducible (solo archivos de evidencia previamente saneados, sin secretos):

```bash
python -m experiments.gw6_recovery.freeze \
  --evidence-dir /ruta/evidencia-saneada \
  --output /ruta/externa/manifest.json
```

El comando registra hashes de protocolo, código y evidencia, commit y worktree
sucio; rechaza sobrescritura y salida dentro del directorio de entrada. No ejecuta
backtesting ni declara congelado un candidato prospectivo.
