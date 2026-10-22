---
type: adr
name: ADR-018 — Foco nativo y conciliación R2 ante cotizaciones de venta
created: 2026-10-22
status: accepted-for-implementation
owner: Julian Zuluaga
---

# Evidencia y alcance

La validación viva de ADR-017 falló en `focus_checkbox` de Vice Captain después de
un swap y antes del paso de Save. El intento quedó ambiguo y no se reintentó. El
checkbox nativo había sido observado por el probe y por el wait del driver, pero
el finder de accesibilidad con nombre exacto no pudo enfocarlo.

Dos lecturas posteriores a recarga mostraron exactamente los mismos jugadores,
posiciones, C/VC, fecha de edición, precios de compra, banco, valor, contadores y
chips que antes. Sólo cambiaron dos cotizaciones `selling_price`: 418 de 48 a 47 y 427
de 78 a 79. El fingerprint completo cambió y la conciliación estricta lo rechazó.
El error y las dos lecturas se conservan; esa lectura no acredita Save ni entrega.

Julián autorizó iterar el goal hasta operar y verificar el equipo preliminar. Esta
corrección conserva A2/lineup-v1, cero transferencias/hits/chips y cuotas; no permite
tratar como exitosa una ejecución ambigua ni repetirla sin conciliación previa.

# Decisión

El foco se enlaza al mismo input checkbox nativo que usan probe y verifier: etiqueta
exacta, visible, único y habilitado. Se verifica `document.activeElement` antes de
Space. El foco no cambia checked; Space y la verificación posterior siguen siendo
pasos separados. Ambigüedad, controles duplicados, ausentes o deshabilitados fallan
cerrados. No se buscan nombres aproximados ni se hacen clicks Save de prueba.

El cleanup del host carga runtime.env y luego deploy.env como el collector privado.
Respeta `MOVA_BROWSER_KEEP_RUNNING=1` en éxito y fallo; conserva el perfil provisionado,
los locks, los tokens privados fuera de argv/logs y la clasificación de ambigüedad.

Para conciliar un R2 como no aplicado se permiten únicamente diferencias de
`selling_price` de mercado, con estas
condiciones simultáneas:

- Invariante original sellado, validado y ligado al fingerprint previo del intento.
- Dos GET privados independientes después de recarga y del fallo, separados >=5s,
  ambos <=300s y con el mismo fingerprint completo actual, incluidas cotizaciones.
- Todos los demás campos normalizados idénticos al original: cuenta/GW/deadline,
  picks/orden/C/VC/multiplicadores, compras, fecha de edición, banco, valor,
  transferencias libres/hechas/coste/estado y todos los campos de chips.
- Mismos snapshots y fingerprints al compare-and-swap transaccional; ningún otro
  intento posterior o activo. Conservar fingerprint previo y ambos observados.

Se registra evidencia de cotización cambiada y de estado controlado por la cuenta
idéntico. La transición es ambiguo → fallido conciliado; jamás verified. Conserva
el error previo, resultado y eventos. Sólo entonces otro solve/preflight/lease nuevo
puede preparar una revisión. Si cambia cualquier otro campo o los dos GET discrepan,
la ambigüedad se mantiene. Preflight y verifier R2 no relajan sus controles.

# Validación y aceptación

Pruebas de foco sin toggle, unicidad/habilitación, cleanup persistente tanto tras
éxito como fallo después de begin; conciliación con cotización estable, rechazo
por compra/capitanía/banco cambiado, cotizaciones discrepantes, evidencia alterada,
lecturas viejas o demasiado cercanas. Suite completa e imagen antes de despliegue.
La aceptación viva exige dos lecturas nuevas, conciliación auditada y una nueva
entrega normal del scheduler verificada. El fallo inicial nunca se borra.
