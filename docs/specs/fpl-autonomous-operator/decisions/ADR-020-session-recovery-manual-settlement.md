---
type: adr
name: ADR-020 — Recuperación de sesión y cierre manual atribuido
created: 2026-10-28
status: accepted-for-implementation
owner: Julian Zuluaga
---

# Alcance y autorización

Julián pidió el 28/10 resolver los fallos de sesión y cierre GW8 e iterar hacia
la autonomía completa. Autoriza correcciones y rollout verificable; no sustituye
pruebas longitudinales ni habilita fichajes/chips sin sus gates.

# Decisión

Un 403 privado permite una sola recarga GET de la pestaña bajo los locks del
collector. Se espera cancha/login y se repite una vez el GET. Redirect de identidad,
timeout o segundo rechazo fallan cerrados, sin credenciales ni Save. El runtime
conserva la cota externa de 120 s y el cooldown. Una sesión persistente puede
recuperarse así; contraseña/MFA impuestos por el proveedor siguen siendo humanos.

El cierre programado de una ejecución manual íntegra usa el contrato financiado
manual v2, con selected reconstruido desde decision_players/audit y comparator
desde el pre-state identificado por fingerprint. No exige ni inventa candidato
MILP. Hashes, recibo, estados financieros y resultado oficial siguen obligatorios.
La expectativa retrospectiva usa un batch approved generado antes del deadline.
El contrato manual queda excluido de observed_closeouts autónomos. Automatizar
settlement no acredita montaje autónomo ni crea un scorecard causal.

# Validación

Regresiones: recuperación exitosa, segundo 403, otro error sin recarga; manual
con/sin candidato equivalente; evidencia alterada; financiación; conteo separado.
Suite completa, smoke de imagen, conciliación GW8 y doctor tras rollout. Conservar
imagen previa y rollback de código; no restaurar DB para ocultar intentos fallidos.
