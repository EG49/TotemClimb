-- Este archivo está guardado en UTF-8.
SET client_encoding = 'UTF8';

-- ============================================================
-- ALTER para el módulo de Cobrar
-- ============================================================
-- 1. Numeración de facturas mediante secuencia, para que dos
--    cobros simultáneos nunca reciban el mismo número.
-- 2. Acciones y entidades nuevas en la bitácora: cambios de
--    precio en el catálogo, que antes no se registraban.
--
-- Uso:
--   psql -U postgres -d totem -f alter-cobrar.sql
--
-- NOTA: si la aplicación se conecta con un usuario distinto de
-- postgres, ese usuario necesita permiso sobre la secuencia nueva.
-- Descomenta la última línea del archivo y pon ahí su nombre.


-- ------------------------------------------------------------
-- 1. Secuencia de numeración de facturas
-- ------------------------------------------------------------
-- El número visible se arma como 'F-000001'. Arranca después
-- del número más alto que ya exista, para no chocar con las
-- facturas cargadas durante las pruebas.

CREATE SEQUENCE IF NOT EXISTS seq_numero_factura START 1;

SELECT setval(
    'seq_numero_factura',
    GREATEST(
        (SELECT COALESCE(MAX(CAST(SUBSTRING(numero_factura FROM 3) AS BIGINT)), 0)
           FROM facturas
          WHERE numero_factura ~ '^F-[0-9]+$'),
        1
    )
);


-- ------------------------------------------------------------
-- 2. Bitácora: cambios en el catálogo
-- ------------------------------------------------------------
-- La entidad (PRODUCTO o PLAN) distingue qué se tocó, así que
-- bastan acciones genéricas de ítem.

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
        'ITEM_REACTIVADO'
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
        'PLAN'
    ));


-- Si la aplicación NO se conecta como postgres, descomenta esto y
-- reemplaza 'mi_usuario' por el usuario que usa la app. Sin este
-- permiso, al cobrar aparece "permission denied for sequence".
-- GRANT USAGE, SELECT ON SEQUENCE seq_numero_factura TO mi_usuario;
