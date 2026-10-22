-- ============================================================
-- CORRECCIÓN DE CODIFICACIÓN
-- ============================================================
-- En Windows, psql usa por defecto la página de códigos de la
-- consola (normalmente WIN1252) en vez de UTF-8, así que al
-- cargar el script original las letras acentuadas se guardaron
-- mal. Esta línea obliga a interpretar el archivo como UTF-8.
--
-- Uso:
--   psql -U postgres -d totem -f fix-codificacion.sql

SET client_encoding TO 'UTF8';

-- Reescribe los nombres con acentos, sin importar cómo hayan
-- quedado. Se identifican por su tipo y precio, que no tienen
-- caracteres especiales.

UPDATE planes_membresia SET nombre = 'Membresía Junior'
 WHERE tipo = 'JUNIOR' AND precio = 30.00;

UPDATE planes_membresia SET nombre = 'Membresía Senior'
 WHERE tipo = 'SENIOR' AND precio = 35.00;

UPDATE planes_membresia SET nombre = 'Pase 1 día'
 WHERE tipo = 'PASES' AND dias_incluidos = 1;

UPDATE planes_membresia SET nombre = 'Pase 10 días'
 WHERE tipo = 'PASES' AND dias_incluidos = 10;

UPDATE configuracion
   SET descripcion = 'Porcentaje de IVA aplicado a las facturas nuevas'
 WHERE clave = 'iva_porcentaje';

-- Comprobación: estos cuatro nombres deben verse con sus tildes.
SELECT id_plan, nombre, tipo, precio FROM planes_membresia ORDER BY id_plan;
