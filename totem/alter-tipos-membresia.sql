-- ============================================================
-- Solo dos tipos de membresía: JUNIOR y SENIOR
-- Acordado en la reunión del 23/10/2026
-- ============================================================
-- Los pases pasan a clasificarse como SENIOR. Que un plan sea pase
-- deja de depender del tipo y pasa a deducirse de que tenga entradas
-- incluidas (dias_incluidos).
--
-- Antes, "tipo" hacía dos trabajos a la vez: decía la categoría
-- comercial Y el mecanismo de cobro. Por eso no se podía clasificar un
-- pase como Senior sin romper el cálculo de la venta.
--
-- Este archivo NO hace falta si vas a recrear la base con
-- totem-schema-v4.sql, que ya viene con los dos tipos.

SET client_encoding = 'UTF8';

BEGIN;

-- EL ORDEN IMPORTA. Las dos restricciones viejas están atadas al tipo
-- 'PASES': la de entradas exige que un plan con entradas SEA de tipo
-- PASES. Si se intenta cambiar el tipo antes de soltarlas, la propia
-- restricción bloquea la migración. Por eso primero se quitan, después
-- se migran los datos, y al final se ponen las nuevas.

-- 1. Soltar las restricciones viejas.
ALTER TABLE planes_membresia DROP CONSTRAINT IF EXISTS chk_plan_dias_incluidos;
ALTER TABLE planes_membresia DROP CONSTRAINT IF EXISTS chk_plan_tipo;

-- 2. Los pases existentes pasan a Senior.
UPDATE planes_membresia
   SET tipo = 'SENIOR'
 WHERE tipo = 'PASES';

-- 3. El tipo queda restringido a dos valores.
ALTER TABLE planes_membresia ADD CONSTRAINT chk_plan_tipo
    CHECK (tipo IN ('JUNIOR', 'SENIOR'));

-- 4. Un plan con entradas incluidas se mide en días; uno mensual no
--    tiene entradas que contar.
ALTER TABLE planes_membresia ADD CONSTRAINT chk_plan_dias_incluidos
    CHECK (
        dias_incluidos IS NULL
        OR (dias_incluidos > 0 AND unidad_duracion = 'DIA')
    );

COMMIT;

-- Comprobación: no debería quedar ningún plan con tipo PASES.
--   SELECT nombre, tipo, dias_incluidos FROM planes_membresia ORDER BY id_plan;
