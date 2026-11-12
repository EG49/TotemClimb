SET client_encoding = 'UTF8';

-- ============================================================
-- TOTEM CLIMB GYM — GASTOS: concepto y facturado
-- ============================================================
-- Agrega a la tabla gastos los dos campos que faltaban para el
-- punto 4 del backlog:
--
--   concepto   Qué se pagó: "Arriendo", "Luz", "Magnesio". Es lo
--              que permite agrupar el balance y sugerir los
--              gastos recurrentes del mes anterior.
--
--   facturado  Si el gasto tiene factura de respaldo. Es lo que
--              distingue lo deducible de lo que no, y por eso no
--              admite nulos: un gasto sin respuesta no existe,
--              o la tiene o no la tiene.
--
-- Correr una sola vez, sobre una base que ya tenga el esquema v4:
--   psql -U postgres -d totem -f alter-gastos.sql
--
-- Si la base se crea de cero con totem-schema-v4.sql, este
-- archivo NO hace falta: el esquema ya los trae.
-- ============================================================

BEGIN;

-- La tabla nacio con el esquema v4. Una base creada con el esquema
-- anterior no la tiene, y entonces no hay columnas que agregar: hay
-- que crearla entera. Sin esto, migrar desde el esquema viejo fallaba
-- con "no existe la relacion gastos".
CREATE TABLE IF NOT EXISTS gastos (
    id_gasto SERIAL PRIMARY KEY,
    fecha DATE NOT NULL,
    monto NUMERIC(10,2) NOT NULL,
    segmento VARCHAR(10) NOT NULL,
    concepto VARCHAR(80),
    facturado BOOLEAN NOT NULL DEFAULT FALSE,
    descripcion VARCHAR(255),
    metodo_pago VARCHAR(30),
    id_empleado INTEGER NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'REGISTRADO',
    motivo_anulacion VARCHAR(255),
    fecha_registro TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_gasto_empleado FOREIGN KEY (id_empleado)
        REFERENCES empleados(id_empleado),
    CONSTRAINT chk_gasto_monto CHECK (monto > 0),
    CONSTRAINT chk_gasto_segmento CHECK (segmento IN ('JUNIOR','SENIOR','GENERAL')),
    CONSTRAINT chk_gasto_estado CHECK (estado IN ('REGISTRADO','ANULADO')),
    CONSTRAINT chk_gasto_metodo
        CHECK (metodo_pago IS NULL OR metodo_pago IN ('EFECTIVO','TRANSFERENCIA')),
    CONSTRAINT chk_gasto_anulacion CHECK (
        (estado = 'ANULADO' AND motivo_anulacion IS NOT NULL)
        OR (estado <> 'ANULADO'))
);

ALTER TABLE gastos
    ADD COLUMN IF NOT EXISTS concepto VARCHAR(80);

ALTER TABLE gastos
    ADD COLUMN IF NOT EXISTS facturado BOOLEAN NOT NULL DEFAULT FALSE;

-- Los gastos que ya existían no tienen concepto. Se les pone uno
-- genérico para poder exigirlo de aquí en adelante.
UPDATE gastos SET concepto = 'Sin clasificar'
 WHERE concepto IS NULL OR btrim(concepto) = '';

ALTER TABLE gastos
    ALTER COLUMN concepto SET NOT NULL;

ALTER TABLE gastos DROP CONSTRAINT IF EXISTS chk_gasto_concepto;
ALTER TABLE gastos ADD CONSTRAINT chk_gasto_concepto
    CHECK (btrim(concepto) <> '');

-- Si la base venía con el mismo concepto escrito de varias formas
-- ('Luz', 'LUZ', 'luz '), el balance lo mostraría como tres gastos
-- distintos. Se unifican a la escritura más usada de cada uno.
WITH canonico AS (
    SELECT lower(btrim(concepto)) AS clave,
           (array_agg(concepto ORDER BY n DESC, concepto))[1] AS forma
      FROM (
        SELECT concepto, COUNT(*) AS n
          FROM gastos
         GROUP BY concepto
      ) AS variantes
     GROUP BY lower(btrim(concepto))
)
UPDATE gastos g
   SET concepto = c.forma
  FROM canonico c
 WHERE lower(btrim(g.concepto)) = c.clave
   AND g.concepto <> c.forma;

-- Búsquedas del balance: siempre por rango de fechas, y casi
-- siempre dejando fuera los anulados.
CREATE INDEX IF NOT EXISTS idx_gasto_fecha ON gastos(fecha);
CREATE INDEX IF NOT EXISTS idx_gasto_estado_fecha ON gastos(estado, fecha);

COMMIT;

-- Comprobación
SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_name = 'gastos' AND column_name IN ('concepto', 'facturado')
 ORDER BY column_name;
