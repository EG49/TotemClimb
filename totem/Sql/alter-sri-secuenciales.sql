SET client_encoding = 'UTF8';

-- ============================================================
-- TOTEM CLIMB GYM — SECUENCIALES Y ESTADO ANTE EL SRI
-- ============================================================
-- Prepara la base para emitir facturas electrónicas.
--
-- POR QUÉ UNA TABLA Y NO UNA SECUENCIA DE POSTGRES
--
-- El número interno (F-000001) sale de una secuencia, y está bien:
-- si un cobro falla, que se salte un número no le importa a nadie.
--
-- El secuencial del SRI es otra cosa. Dos reglas que no se pueden
-- romper:
--
--   1. No puede repetirse. Dos comprobantes con el mismo número en
--      el mismo punto de emisión son un problema ante el SRI, y no
--      se deshace: lo emitido, emitido está.
--   2. Va por establecimiento y punto de emisión, cada uno con su
--      propia numeración.
--
-- Una secuencia de Postgres no sirve para ninguna de las dos: no
-- vuelve atrás cuando la transacción falla (deja huecos) y es una
-- sola para toda la base.
--
-- Con una fila por punto de emisión, el cobro la bloquea mientras
-- dura su transacción. Si el cobro falla, el número vuelve solo. Si
-- dos cajas cobran al mismo tiempo, la segunda espera a la primera:
-- en un gimnasio con una o dos cajas eso no se nota, y es lo que
-- garantiza que nunca salga el mismo número dos veces.
--
-- IMPORTANTE SI EL GIMNASIO YA FACTURA CON OTRA HERRAMIENTA
--
-- Este archivo deja el punto de emisión 002 arrancando en 1. Si la
-- otra herramienta ya emitió en ese mismo punto, hay que correr el
-- UPDATE del final con el último número que ella emitió. Si usa el
-- 001, no hace falta: son numeraciones separadas.
--
-- Correr una sola vez, sobre una base con el esquema v4:
--   psql -U postgres -d totem -f alter-sri-secuenciales.sql
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. La numeración, una fila por punto de emisión y tipo
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sri_secuenciales (
    establecimiento   CHAR(3)  NOT NULL,
    punto_emision     CHAR(3)  NOT NULL,
    tipo_comprobante  CHAR(2)  NOT NULL,
    ultimo_secuencial INTEGER  NOT NULL DEFAULT 0,
    fecha_actualizacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT pk_sri_secuenciales
        PRIMARY KEY (establecimiento, punto_emision, tipo_comprobante),

    -- El SRI solo admite 9 dígitos.
    CONSTRAINT chk_sri_secuencial_rango
        CHECK (ultimo_secuencial >= 0 AND ultimo_secuencial <= 999999999),

    CONSTRAINT chk_sri_establecimiento
        CHECK (establecimiento ~ '^[0-9]{3}$'),
    CONSTRAINT chk_sri_punto_emision
        CHECK (punto_emision ~ '^[0-9]{3}$'),
    -- 01 factura, 04 nota de crédito.
    CONSTRAINT chk_sri_tipo_comprobante
        CHECK (tipo_comprobante IN ('01', '04'))
);

COMMENT ON TABLE sri_secuenciales IS
    'Último secuencial emitido por punto de emisión. Se reserva con '
    'bloqueo de fila dentro de la transacción del cobro.';

-- ------------------------------------------------------------
-- 2. El estado de cada factura ante el SRI
-- ------------------------------------------------------------
-- Van en la propia factura y no en una tabla aparte: una factura
-- tiene a lo sumo un comprobante electrónico, y así el estado se
-- lee junto con el resto sin un JOIN más.
ALTER TABLE facturas
    ADD COLUMN IF NOT EXISTS sri_establecimiento CHAR(3),
    ADD COLUMN IF NOT EXISTS sri_punto_emision   CHAR(3),
    ADD COLUMN IF NOT EXISTS sri_secuencial      INTEGER,
    ADD COLUMN IF NOT EXISTS sri_clave_acceso    CHAR(49),
    ADD COLUMN IF NOT EXISTS sri_estado          VARCHAR(20),
    ADD COLUMN IF NOT EXISTS sri_autorizacion    VARCHAR(49),
    ADD COLUMN IF NOT EXISTS sri_fecha_autorizacion TIMESTAMP,
    ADD COLUMN IF NOT EXISTS sri_mensaje         TEXT,
    ADD COLUMN IF NOT EXISTS sri_intentos        INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sri_xml             TEXT;

-- Los estados posibles. PENDIENTE es la factura que todavía no se
-- envió: es el estado normal cuando se cae el internet, y el que
-- hace que el reintento la vuelva a tomar.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_factura_sri_estado'
    ) THEN
        ALTER TABLE facturas ADD CONSTRAINT chk_factura_sri_estado
            CHECK (sri_estado IS NULL OR sri_estado IN (
                'PENDIENTE', 'FIRMADA', 'ENVIADA',
                'AUTORIZADA', 'DEVUELTA', 'NO_AUTORIZADA'
            ));
    END IF;
END $$;

-- Dos comprobantes no pueden compartir número en el mismo punto de
-- emisión. Es la red de seguridad por si algún día alguien escribe
-- el secuencial sin pasar por la reserva.
CREATE UNIQUE INDEX IF NOT EXISTS ux_facturas_sri_numero
    ON facturas (sri_establecimiento, sri_punto_emision, sri_secuencial)
    WHERE sri_secuencial IS NOT NULL;

-- Y la clave de acceso tampoco se repite.
CREATE UNIQUE INDEX IF NOT EXISTS ux_facturas_sri_clave
    ON facturas (sri_clave_acceso)
    WHERE sri_clave_acceso IS NOT NULL;

-- Para que el reintento encuentre rápido lo que quedó sin enviar.
CREATE INDEX IF NOT EXISTS ix_facturas_sri_pendientes
    ON facturas (sri_estado)
    WHERE sri_estado IN ('PENDIENTE', 'FIRMADA', 'ENVIADA');

-- ------------------------------------------------------------
-- 3. El punto de emisión del sistema
-- ------------------------------------------------------------
-- Arranca en 0: el primer comprobante será el 1.
INSERT INTO sri_secuenciales
    (establecimiento, punto_emision, tipo_comprobante, ultimo_secuencial)
VALUES
    ('001', '002', '01', 0),
    ('001', '002', '04', 0)
ON CONFLICT (establecimiento, punto_emision, tipo_comprobante) DO NOTHING;

COMMIT;

-- ============================================================
-- SI EL GIMNASIO YA EMITIÓ EN EL PUNTO 002 CON OTRA HERRAMIENTA
-- ============================================================
-- Descomentar y poner el último número que esa herramienta emitió.
-- El sistema seguirá desde el siguiente.
--
-- UPDATE sri_secuenciales
--    SET ultimo_secuencial = 1234,
--        fecha_actualizacion = CURRENT_TIMESTAMP
--  WHERE establecimiento = '001'
--    AND punto_emision   = '002'
--    AND tipo_comprobante = '01';

-- ============================================================
-- PARA VERIFICAR
-- ============================================================
-- SELECT * FROM sri_secuenciales;
-- \d facturas
