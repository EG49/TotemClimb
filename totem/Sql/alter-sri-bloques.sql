SET client_encoding = 'UTF8';

-- ============================================================
-- TOTEM CLIMB GYM — FACTURAS EN BLOQUE DE PRODUCTOS
-- ============================================================
-- Al SRI van automáticamente solo las membresías y los pases. Los
-- productos sueltos —aguas, bebidas, magnesio— se facturan aparte y
-- en bloque, cada tanto, juntando lo vendido en un periodo.
--
-- POR QUÉ UNA TABLA APARTE Y NO UNA FILA EN facturas
--
-- Porque esa plata YA se contó cuando se cobró. Si la factura en
-- bloque entrara como una venta más, el balance contaría el mismo
-- dinero dos veces, y los reportes de ventas también.
--
-- Se podría poner una marca en facturas y acordarse de excluirla en
-- cada consulta de contabilidad. No: basta que alguien escriba una
-- consulta nueva y se olvide del filtro para duplicar los saldos sin
-- que nadie lo note. Con una tabla aparte, ninguna consulta de
-- contabilidad la alcanza aunque quiera.
--
-- La pantalla de facturas sí las muestra, junto a las ventas y
-- marcadas como lo que son.
--
-- EL TOPE DE USD 200
--
-- Una factura a consumidor final no puede pasar de USD 200: arriba
-- de eso el SRI exige identificar al comprador, imposible cuando son
-- decenas de clientes distintos. Por eso un periodo puede producir
-- VARIAS facturas en bloque, cada una por debajo del tope. De ahí
-- que esta tabla tenga una fila por factura emitida y no una por
-- periodo.
--
-- Correr una sola vez, después de alter-sri-secuenciales.sql:
--   psql -U postgres -d totem -f alter-sri-bloques.sql
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS facturas_bloque (
    id_bloque       SERIAL PRIMARY KEY,
    desde           DATE NOT NULL,
    hasta           DATE NOT NULL,
    fecha_emision   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    id_empleado     INTEGER REFERENCES empleados(id_empleado),

    base_imponible  NUMERIC(10,2) NOT NULL,
    iva             NUMERIC(10,2) NOT NULL,
    total           NUMERIC(10,2) NOT NULL,
    iva_porcentaje  NUMERIC(5,2)  NOT NULL,

    -- Lo mismo que en facturas: el estado ante el SRI.
    sri_establecimiento CHAR(3),
    sri_punto_emision   CHAR(3),
    sri_secuencial      INTEGER,
    sri_clave_acceso    CHAR(49),
    sri_estado          VARCHAR(20),
    sri_autorizacion    VARCHAR(49),
    sri_fecha_autorizacion TIMESTAMP,
    sri_mensaje         TEXT,
    sri_intentos        INTEGER NOT NULL DEFAULT 0,
    sri_xml             TEXT,

    CONSTRAINT chk_bloque_fechas CHECK (desde <= hasta),
    CONSTRAINT chk_bloque_total  CHECK (total >= 0),
    CONSTRAINT chk_bloque_estado CHECK (
        sri_estado IS NULL OR sri_estado IN (
            'PENDIENTE', 'FIRMADA', 'ENVIADA',
            'AUTORIZADA', 'DEVUELTA', 'NO_AUTORIZADA'
        )
    )
);

COMMENT ON TABLE facturas_bloque IS
    'Facturas de productos sueltos agrupados por periodo. NO son '
    'ventas: esa plata ya se conto en facturas. No deben entrar en '
    'ningun calculo de contabilidad.';

-- El detalle de cada bloque, ya consolidado por producto.
CREATE TABLE IF NOT EXISTS detalle_bloque (
    id_detalle_bloque SERIAL PRIMARY KEY,
    id_bloque   INTEGER NOT NULL REFERENCES facturas_bloque(id_bloque)
                ON DELETE CASCADE,
    id_producto INTEGER NOT NULL REFERENCES productos(id_producto),
    cantidad    INTEGER NOT NULL,
    precio_unitario NUMERIC(10,2) NOT NULL,
    subtotal    NUMERIC(10,2) NOT NULL,

    CONSTRAINT chk_detalle_bloque_cantidad CHECK (cantidad > 0)
);

CREATE INDEX IF NOT EXISTS ix_detalle_bloque_bloque
    ON detalle_bloque (id_bloque);

-- ------------------------------------------------------------
-- La marca de "ya facturado en bloque"
-- ------------------------------------------------------------
-- Va sobre la linea de venta, no sobre la factura: una venta mixta
-- tiene la membresia ya facturada al SRI y las aguas pendientes.
--
-- Guarda CUANTAS unidades de esa linea entraron en un bloque, y no
-- un simple si/no, porque el tope de USD 200 puede obligar a partir
-- una linea entre dos facturas: 400 aguas de 0.50 son exactamente el
-- tope, 401 ya no entran juntas.
ALTER TABLE detalle_factura
    ADD COLUMN IF NOT EXISTS unidades_en_bloque INTEGER NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'chk_detalle_unidades_en_bloque'
    ) THEN
        -- Nunca se puede haber facturado mas de lo que se vendio.
        ALTER TABLE detalle_factura
            ADD CONSTRAINT chk_detalle_unidades_en_bloque
            CHECK (unidades_en_bloque >= 0
                   AND unidades_en_bloque <= cantidad);
    END IF;
END $$;

-- Para encontrar rapido lo que falta facturar.
CREATE INDEX IF NOT EXISTS ix_detalle_pendiente_bloque
    ON detalle_factura (id_producto)
    WHERE id_producto IS NOT NULL;

-- La numeracion: los bloques salen por el mismo punto de emision y
-- comparten la numeracion con las demas facturas, porque son
-- facturas (codigo 01) del mismo emisor. Ya existe la fila.

COMMIT;

-- ============================================================
-- PARA VERIFICAR
-- ============================================================
-- SELECT * FROM facturas_bloque;
-- SELECT cantidad, unidades_en_bloque FROM detalle_factura
--  WHERE id_producto IS NOT NULL LIMIT 10;
