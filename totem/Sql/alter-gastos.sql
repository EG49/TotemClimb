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
