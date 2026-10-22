-- Este archivo está guardado en UTF-8.
SET client_encoding = 'UTF8';

-- ============================================================
-- ALTER para la gestión de empleados
-- ============================================================
-- 1. Fecha de nacimiento, para que los cumpleaños del personal
--    también salgan en el calendario.
-- 2. Acciones y entidad nuevas en la bitácora: crear, editar,
--    desactivar un usuario y cambiarle la contraseña son acciones
--    sensibles que deben quedar registradas.
--
-- Uso:
--   psql -U postgres -d totem -f alter-empleados.sql


-- ------------------------------------------------------------
-- 1. Fecha de nacimiento del empleado
-- ------------------------------------------------------------
-- Opcional: un empleado puede no querer registrarla, y el sistema
-- funciona igual. Solo se usa para el calendario.

ALTER TABLE empleados
    ADD COLUMN IF NOT EXISTS fecha_nacimiento DATE;


-- ------------------------------------------------------------
-- 2. Bitácora: gestión de usuarios
-- ------------------------------------------------------------

ALTER TABLE bitacora DROP CONSTRAINT IF EXISTS chk_bitacora_accion;
ALTER TABLE bitacora ADD CONSTRAINT chk_bitacora_accion
    CHECK (accion IN (
        'CLIENTE_CREADO',
        'CLIENTE_EDITADO',
        'FACTURA_EMITIDA',
        'FACTURA_ANULADA',
        'ABONO_REGISTRADO',
        'INSCRIPCION_REGISTRADA',
        'INSCRIPCION_CANCELADA',
        'IVA_CAMBIADO',
        'ITEM_CREADO',
        'ITEM_EDITADO',
        'ITEM_DESACTIVADO',
        'ITEM_REACTIVADO',
        'EMPLEADO_CREADO',
        'EMPLEADO_EDITADO',
        'EMPLEADO_DESACTIVADO',
        'EMPLEADO_REACTIVADO',
        'PASSWORD_CAMBIADA'
    ));

ALTER TABLE bitacora DROP CONSTRAINT IF EXISTS chk_bitacora_entidad;
ALTER TABLE bitacora ADD CONSTRAINT chk_bitacora_entidad
    CHECK (entidad IN (
        'CLIENTE',
        'FACTURA',
        'PAGO_FIADO',
        'INSCRIPCION',
        'CONFIGURACION',
        'PRODUCTO',
        'PLAN',
        'EMPLEADO'
    ));


-- ------------------------------------------------------------
-- Nota sobre el borrado
-- ------------------------------------------------------------
-- Un empleado NO se borra nunca: facturas, pagos_fiado,
-- evento_inscritos y bitacora lo referencian, y esos registros
-- deben seguir diciendo quién los hizo. Cuando alguien deja de
-- trabajar se marca activo = FALSE: deja de poder entrar, pero su
-- historial queda intacto.
