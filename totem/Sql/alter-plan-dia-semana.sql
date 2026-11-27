-- ============================================================
-- Un plan puede estar atado a un día de la semana
--
-- "Promo jueves (2 personas)" se podía cobrar cualquier día. El
-- nombre lo decía y nadie lo revisaba: el jueves es una regla del
-- negocio, no una palabra en un nombre.
--
-- Se guarda el día en el plan en lugar de leer el nombre, por dos
-- motivos. Buscar "jueves" dentro del nombre se rompe el día que
-- alguien lo escriba "Jueves 2x1" o lo renombre, y además no sirve
-- para la promo del martes que venga después. Con el día en su
-- columna, cualquier plan futuro funciona sin tocar el código.
--
-- NULL quiere decir cualquier día, que es lo normal.
-- 0 = lunes ... 6 = domingo, igual que Python.
--
-- Cómo aplicarlo, desde la carpeta Sql:
--
--   psql -U postgres -d totem -f alter-plan-dia-semana.sql
-- ============================================================

BEGIN;

ALTER TABLE planes_membresia
    ADD COLUMN IF NOT EXISTS dia_semana SMALLINT;

ALTER TABLE planes_membresia DROP CONSTRAINT IF EXISTS chk_plan_dia_semana;
ALTER TABLE planes_membresia ADD CONSTRAINT chk_plan_dia_semana
    CHECK (dia_semana IS NULL OR dia_semana BETWEEN 0 AND 6);

-- A los planes que ya existen se les pone el día que dice su nombre.
-- Es una sola vez y para los que ya están: de acá en adelante se
-- elige en la pantalla de Productos.
UPDATE planes_membresia SET dia_semana = 0
 WHERE dia_semana IS NULL AND lower(nombre) LIKE '%lunes%';
UPDATE planes_membresia SET dia_semana = 1
 WHERE dia_semana IS NULL AND lower(nombre) LIKE '%martes%';
UPDATE planes_membresia SET dia_semana = 2
 WHERE dia_semana IS NULL AND (lower(nombre) LIKE '%miercoles%'
                            OR lower(nombre) LIKE '%miércoles%');
UPDATE planes_membresia SET dia_semana = 3
 WHERE dia_semana IS NULL AND lower(nombre) LIKE '%jueves%';
UPDATE planes_membresia SET dia_semana = 4
 WHERE dia_semana IS NULL AND lower(nombre) LIKE '%viernes%';
UPDATE planes_membresia SET dia_semana = 5
 WHERE dia_semana IS NULL AND (lower(nombre) LIKE '%sabado%'
                            OR lower(nombre) LIKE '%sábado%');
UPDATE planes_membresia SET dia_semana = 6
 WHERE dia_semana IS NULL AND lower(nombre) LIKE '%domingo%';

-- Qué quedó atado a un día, para revisarlo de un vistazo.
SELECT nombre,
       CASE dia_semana
           WHEN 0 THEN 'lunes'    WHEN 1 THEN 'martes'
           WHEN 2 THEN 'miércoles' WHEN 3 THEN 'jueves'
           WHEN 4 THEN 'viernes'  WHEN 5 THEN 'sábado'
           WHEN 6 THEN 'domingo'
       END AS solo_los
  FROM planes_membresia
 WHERE dia_semana IS NOT NULL
 ORDER BY dia_semana;

COMMIT;
