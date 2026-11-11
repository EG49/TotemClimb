SET client_encoding = 'UTF8';

-- ============================================================
-- TOTEM CLIMB GYM — CATÁLOGO CON PRECIOS QUE INCLUYEN IVA
-- ============================================================
-- Punto 2 del backlog. Hasta ahora el sistema sumaba el IVA encima
-- del precio del catálogo, así que una mensualidad de $65 se
-- facturaba en $74.75. Los precios del gimnasio YA INCLUYEN IVA,
-- de modo que el cálculo tiene que extraerlo del total.
--
-- El cambio de cálculo va en el código (cobro_service.calcular).
-- Este archivo solo pone el catálogo al día:
--
--   * Precios nuevos, con IVA incluido.
--   * Junior y Senior cuestan lo mismo ($65). A la Junior se le
--     aplica un descuento al cobrar, que varía según el caso; la
--     Senior se cobra completa.
--   * "Promo jueves": nueva, $10 por dos personas.
--   * "Senior anual": se desactiva, ya no se vende.
--   * "Cubo de magnesio" como producto, $5.
--
-- Las facturas ya emitidas NO se tocan. Quedan con los montos con
-- que se cobraron: una factura vieja es un hecho histórico, y
-- recalcularla cambiaría cifras que el cliente ya pagó.
--
-- Correr una sola vez:
--   psql -U postgres -d totem -f alter-precios-iva.sql
-- ============================================================

BEGIN;

-- ---------- Nada se borra: lo que no se vende se desactiva ----------
-- Desactivar en lugar de borrar mantiene intactas las facturas que
-- ya incluyen estos planes.
UPDATE planes_membresia SET activo = FALSE
 WHERE nombre IN ('Senior anual');

-- ---------- Renombrar los que cambian de nombre ----------
-- Se renombra en vez de crear uno nuevo para no partir el historial
-- de ventas del mismo plan en dos filas del reporte.
UPDATE planes_membresia SET nombre = 'Mensualidad dúo'
 WHERE nombre = 'Promo pareja (2 personas)';
UPDATE planes_membresia SET nombre = 'Pase del día'
 WHERE nombre = 'Pase 1 día';
UPDATE planes_membresia SET nombre = '5 pases'
 WHERE nombre = 'Pase 5 días';
UPDATE planes_membresia SET nombre = '10 pases'
 WHERE nombre = 'Pase 10 días';

-- ---------- Precios con IVA incluido ----------
UPDATE planes_membresia SET precio = 65.00,  permite_descuento = TRUE,
                            permite_pareja = FALSE
 WHERE nombre = 'Membresía Junior';

UPDATE planes_membresia SET precio = 65.00,  permite_descuento = FALSE,
                            permite_pareja = FALSE
 WHERE nombre = 'Membresía Senior';

UPDATE planes_membresia SET precio = 111.00, permite_descuento = FALSE,
                            permite_pareja = TRUE
 WHERE nombre = 'Mensualidad dúo';

UPDATE planes_membresia SET precio = 10.00,  permite_descuento = FALSE,
                            permite_pareja = FALSE
 WHERE nombre = 'Pase del día';

UPDATE planes_membresia SET precio = 30.00,  permite_descuento = FALSE
 WHERE nombre = '5 pases';

UPDATE planes_membresia SET precio = 49.00,  permite_descuento = FALSE
 WHERE nombre = '10 pases';

-- ---------- Promo jueves: nueva ----------
-- Un pase de día para dos personas. Se inserta solo si no existe,
-- para que el archivo se pueda correr dos veces sin duplicarla.
INSERT INTO planes_membresia
    (nombre, tipo, precio, duracion, unidad_duracion, dias_incluidos,
     permite_pareja, permite_descuento, activo)
SELECT 'Promo jueves (2 personas)', 'SENIOR', 10.00, 1, 'DIA', 1,
       TRUE, FALSE, TRUE
 WHERE NOT EXISTS (
    SELECT 1 FROM planes_membresia
     WHERE nombre = 'Promo jueves (2 personas)'
 );

-- ---------- Cubo de magnesio: producto, no plan ----------
INSERT INTO productos (nombre, precio)
SELECT 'Cubo de magnesio', 5.00
 WHERE NOT EXISTS (
    SELECT 1 FROM productos WHERE lower(nombre) = 'cubo de magnesio'
 );

UPDATE productos SET precio = 5.00, activo = TRUE
 WHERE lower(nombre) = 'cubo de magnesio';

-- ---------- El IVA sigue en 15, pero ahora va incluido ----------
UPDATE configuracion
   SET valor = '15',
       descripcion = 'Porcentaje de IVA incluido en los precios del catálogo'
 WHERE clave = 'iva_porcentaje';

COMMIT;

-- ============================================================
-- COMPROBACIÓN
-- ============================================================
-- La base y el IVA se calculan al facturar; esto muestra cuánto
-- daría cada uno con el 15%, para cotejar contra la lista.
SELECT nombre,
       precio                                   AS con_iva,
       round(precio / 1.15, 2)                  AS base,
       precio - round(precio / 1.15, 2)         AS iva,
       round(precio / 1.15, 2)
         + (precio - round(precio / 1.15, 2))   AS suma_control,
       tipo,
       permite_descuento AS descuento,
       permite_pareja    AS pareja,
       activo
  FROM planes_membresia
 ORDER BY activo DESC, tipo, precio;

SELECT nombre, precio AS con_iva,
       round(precio / 1.15, 2) AS base,
       precio - round(precio / 1.15, 2) AS iva,
       activo
  FROM productos
 ORDER BY activo DESC, nombre;
