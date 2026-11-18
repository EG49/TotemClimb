SET client_encoding = 'UTF8';

-- ============================================================
-- TOTEM CLIMB GYM — ACCIONES DEL SRI EN LA BITACORA
-- ============================================================
-- La bitácora acepta solo una lista fija de acciones, y eso está
-- bien: evita que se cuelen nombres inventados que después nadie
-- sabe interpretar. Pero hay que agregar las nuevas.
--
-- COMPROBANTE_REEMITIDO es la que importa. Cuando el SRI rechaza una
-- factura —típicamente porque no acepta la cédula del cliente— hay
-- que emitir un comprobante NUEVO, con otro número. El anterior
-- queda gastado, y eso deja un hueco en la numeración.
--
-- El hueco tiene explicación, pero hay que poder darla. El mensaje
-- de la factura no sirve: al emitir de nuevo se pisa con el
-- resultado nuevo. La bitácora no se pisa.
--
-- Correr una sola vez:
--   psql -U postgres -d totem -f alter-bitacora-sri.sql
-- ============================================================

BEGIN;

ALTER TABLE bitacora DROP CONSTRAINT IF EXISTS chk_bitacora_accion;

ALTER TABLE bitacora ADD CONSTRAINT chk_bitacora_accion CHECK (
    accion IN (
        'CLIENTE_CREADO', 'CLIENTE_EDITADO',
        'FACTURA_EMITIDA', 'FACTURA_ANULADA', 'ABONO_REGISTRADO',
        'INSCRIPCION_REGISTRADA', 'INSCRIPCION_CANCELADA',
        'ASISTENCIA_MARCADA',
        'IVA_CAMBIADO', 'DATOS_GYM_CAMBIADOS',
        'ITEM_CREADO', 'ITEM_EDITADO', 'ITEM_DESACTIVADO',
        'ITEM_REACTIVADO',
        'EMPLEADO_CREADO', 'EMPLEADO_EDITADO', 'EMPLEADO_DESACTIVADO',
        'EMPLEADO_REACTIVADO', 'PASSWORD_CAMBIADA',
        'CORREO_ENVIADO', 'CORREO_FALLIDO',
        'POSIBLE_CREADO', 'POSIBLE_EDITADO', 'COACH_ASIGNADO',
        'POSIBLE_CONVERTIDO',
        'GASTO_REGISTRADO', 'GASTO_EDITADO', 'GASTO_ANULADO',
        -- Facturación electrónica
        'COMPROBANTE_REEMITIDO',
        'BLOQUE_FACTURADO'
    )
);

COMMIT;

-- ============================================================
-- PARA VERIFICAR
-- ============================================================
-- SELECT pg_get_constraintdef(oid) FROM pg_constraint
--  WHERE conname = 'chk_bitacora_accion';
