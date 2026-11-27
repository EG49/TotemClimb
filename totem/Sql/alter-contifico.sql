-- ============================================================
-- Marcar qué ventas ya se cargaron en Contífico
--
-- Los comprobantes electrónicos los emite Contífico, a partir de un
-- Excel que este sistema genera al cerrar el día. Alguien lo abre y
-- los registra allá: es una tarea semimanual, y las tareas
-- semimanuales fallan de dos formas.
--
-- Una venta que se carga dos veces deja dos comprobantes autorizados
-- de la misma venta. Una que no se carga nunca es una venta sin
-- factura. Las dos son problemas tributarios, y ninguna de las dos
-- se nota al día siguiente.
--
-- Por eso la exportación no es solo un archivo: cada factura queda
-- marcada cuando se confirma que ya está en Contífico, y la
-- siguiente exportación no la vuelve a incluir.
--
-- Cómo aplicarlo, desde la carpeta Sql:
--
--   psql -U postgres -d totem -f alter-contifico.sql
-- ============================================================

BEGIN;

-- Dos marcas y no una, porque los planes y los productos se cargan
-- por separado: los planes van a nombre del cliente y los productos
-- en bloque a consumidor final. En esta base, una de cada cuatro
-- ventas lleva las dos cosas, así que con una sola marca cargar los
-- planes del día daría por cargadas también las bebidas de esas
-- ventas, que nadie registró.
ALTER TABLE facturas
    ADD COLUMN IF NOT EXISTS contifico_planes_en TIMESTAMP,
    ADD COLUMN IF NOT EXISTS contifico_planes_por INTEGER
        REFERENCES empleados(id_empleado),
    ADD COLUMN IF NOT EXISTS contifico_productos_en TIMESTAMP,
    ADD COLUMN IF NOT EXISTS contifico_productos_por INTEGER
        REFERENCES empleados(id_empleado);

-- Para buscar rápido lo que falta cargar, de cada tipo.
CREATE INDEX IF NOT EXISTS idx_facturas_contifico_planes
    ON facturas (fecha) WHERE contifico_planes_en IS NULL;
CREATE INDEX IF NOT EXISTS idx_facturas_contifico_productos
    ON facturas (fecha) WHERE contifico_productos_en IS NULL;

-- La bitácora: quién confirmó la carga y de qué período.
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
        'BLOQUE_FACTURADO',
        -- Rebotes de correo
        'CORREO_REBOTADO',
        -- Carga en el sistema externo
        'CONTIFICO_CARGADO'
    )
);

COMMIT;
