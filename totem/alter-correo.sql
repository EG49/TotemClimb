-- Envío de comprobantes por correo.
--
-- Agrega a la bitácora las dos acciones del envío. Se registran las dos,
-- la que funcionó y la que falló: si un cliente reclama que nunca le
-- llegó su recibo, la bitácora tiene que poder responder si se intentó.

SET client_encoding = 'UTF8';

ALTER TABLE bitacora DROP CONSTRAINT IF EXISTS chk_bitacora_accion;
ALTER TABLE bitacora ADD CONSTRAINT chk_bitacora_accion
    CHECK (accion IN (
        'CLIENTE_CREADO', 'CLIENTE_EDITADO', 'FACTURA_EMITIDA', 'FACTURA_ANULADA',
        'ABONO_REGISTRADO', 'INSCRIPCION_REGISTRADA', 'INSCRIPCION_CANCELADA',
        'IVA_CAMBIADO', 'ITEM_CREADO', 'ITEM_EDITADO', 'ITEM_DESACTIVADO',
        'ITEM_REACTIVADO', 'EMPLEADO_CREADO', 'EMPLEADO_EDITADO',
        'EMPLEADO_DESACTIVADO', 'EMPLEADO_REACTIVADO', 'PASSWORD_CAMBIADA',
        'CORREO_ENVIADO', 'CORREO_FALLIDO'
    ));
