---
type: decision
created: 2026-09-22
status: accepted
---

# Observación de alertas en el API sin credenciales de envío

El worker recibe la configuración privada del canal externo; el API no recibe
ese secreto. Ambos usaban `channel_status`, por lo que el API interpretaba la
ausencia local del secreto como canal `local_only`, mientras el CLI devolvía
`configured`. Readiness y cockpit quedaban en desacuerdo después de desplegar.

Se conserva el secreto únicamente en el worker. Tras ejecutar el watchdog,
éste publica atómicamente `runtime/alert-channel.json`: schema, fecha UTC y
estado sanitizado (owner, canal, fingerprint, flags y error tipado). No incluye
token, URL ni destinatario. El API tiene un selector explícito
`MOVA_ALERT_CHANNEL_STATUS_FILE` y lee esa proyección en su mount read-only.
El worker no usa fallback: quitar su configuración debe devolver `local_only`
aunque exista una observación anterior.

Una observación ausente, inválida, futura o mayor de 1800 segundos falla cerrada.
El intervalo cubre el timer watchdog de 15 minutos y un margen de scheduling;
no demuestra entrega reciente. El gate de live ping sigue requiriendo un job
completado cuyo fingerprint coincide con el destino observado. La observación
no proporciona un sink, no activa tools, no concede autoridad ni modifica gates.
Un fallo de publicación ocurre después del despacho y hace fallar el watchdog,
sin impedir por ese motivo la entrega que ya debía realizar.

Pruebas: equivalencia de estado worker/API sin secreto en API, ausencia de
credenciales en el archivo, eliminación del secreto sin fallback, rechazo de
observaciones stale/futuras/corruptas y de campos ajenos al contrato. El test
comprueba también que la proyección no se convierte en capacidad de envío.
