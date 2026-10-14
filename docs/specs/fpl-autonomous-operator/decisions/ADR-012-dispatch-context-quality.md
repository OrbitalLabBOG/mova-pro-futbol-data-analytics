# ADR-012: contexto material antes del permiso y calidad separada de transporte

Estado: implementado localmente, pendiente de release y aceptación operativa.

El worker puede recibir una deliberación sellada horas antes. Validar únicamente
su hash, deadline y presupuesto prueba integridad, pero no vigencia. Antes de
crear un permiso, reconstruir el request desde el envelope verificado actual y
comparar su semántica, incluidos expiración de señales y fingerprint de plantilla.
Una diferencia o evidencia ausente bloquea la autorización. Reutilizar el mismo
constructor de enqueue evita contratos divergentes. No cancelar ni liberar reservas
sin prueba durable de que no existió dispatch.

Research importado conserva procesamiento healthy, pero el servicio solo es healthy
si el último run pasa los umbrales existentes de cobertura/evidencia/conflictos.
Exponer processing_status y quality_status; no alterar los gates prospectivos ni
confundir calidad puntual con aceptación de cohorte. Cambiar estos archivos cambia
el contrato hasheado de aceptación; no heredar una aprobación del contrato anterior.

Esta reparación no elimina conflictos, no atesta ejecuciones ausentes, no modifica
la selección deportiva, no habilita escrituras y no promueve autonomía. La ventana
entre permiso y ejecución requiere seguimiento separado. El protocolo experimental
vive en experiments/gw6_recovery y reutiliza el laboratorio causal existente.
