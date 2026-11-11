SET client_encoding = 'UTF8';

-- ============================================================
-- TOTEM CLIMB GYM - VERIFICACION DE LA BASE
-- ============================================================
-- Comprueba que las migraciones quedaron bien aplicadas. No
-- escribe nada: solo lee y dictamina.
--
--   psql -U postgres -d totem -f verificar.sql
--
-- Cada linea dice OK o FALTA. Si todas dicen OK, la base esta al
-- dia con el codigo de la rama.
-- ============================================================

\pset tuples_only on
\pset border 0

SELECT 'TOTEM - verificacion de la base';
SELECT '';

-- ---------- 1. Estructura ----------
SELECT CASE WHEN COUNT(*) = 15 THEN 'OK    15 tablas'
            ELSE 'FALTA tablas: hay ' || COUNT(*) || ', deberian ser 15' END
  FROM information_schema.tables
 WHERE table_schema = 'public' AND table_type = 'BASE TABLE';

SELECT CASE WHEN COUNT(*) = 2
            THEN 'OK    gastos tiene concepto y facturado'
            ELSE 'FALTA correr alter-gastos.sql (campos presentes: '
                 || COUNT(*) || ' de 2)' END
  FROM information_schema.columns
 WHERE table_name = 'gastos' AND column_name IN ('concepto', 'facturado');

SELECT CASE WHEN data_type IN ('text', 'character varying')
                 AND COALESCE(character_maximum_length, 9999) > 100
            THEN 'OK    configuracion.valor acepta textos largos'
            ELSE 'FALTA correr alter-correos-evento.sql (configuracion.valor'
                 || ' sigue limitado a ' || character_maximum_length || ')' END
  FROM information_schema.columns
 WHERE table_name = 'configuracion' AND column_name = 'valor';

SELECT '';

-- ---------- 2. Catalogo ----------
SELECT CASE WHEN COUNT(*) = 0 THEN 'OK    todos los precios cuadran con su IVA'
            ELSE 'FALTA ' || COUNT(*) || ' plan(es) cuyo precio no cuadra' END
  FROM planes_membresia
 WHERE activo
   AND round(precio / 1.15, 2) + (precio - round(precio / 1.15, 2)) <> precio;

SELECT CASE WHEN COUNT(*) = 8
            THEN 'OK    8 planes activos'
            ELSE 'REVISAR hay ' || COUNT(*) || ' planes activos, deberian ser 8.'
                 || ' Los que sobran: '
                 || COALESCE((SELECT string_agg(nombre, ', ') FROM planes_membresia
                               WHERE activo AND nombre NOT IN (
                                 'Membresia Junior','Membresía Junior',
                                 'Membresia Senior','Membresía Senior',
                                 'Senior 3 meses','Mensualidad duo','Mensualidad dúo',
                                 'Pase del dia','Pase del día',
                                 'Promo jueves (2 personas)','5 pases','10 pases')),
                             'ninguno') END
  FROM planes_membresia WHERE activo;

SELECT CASE WHEN COUNT(*) = 6 THEN 'OK    6 productos activos'
            ELSE 'REVISAR hay ' || COUNT(*) || ' productos activos, deberian ser 6' END
  FROM productos WHERE activo;

SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM planes_membresia WHERE nombre = 'Senior anual')
            THEN 'OK    la Senior anual ya no existe'
            WHEN NOT EXISTS (SELECT 1 FROM planes_membresia
                              WHERE nombre = 'Senior anual' AND activo)
            THEN 'OK    Senior anual desactivada (se vendio alguna vez)'
            ELSE 'FALTA la Senior anual sigue activa' END;

SELECT CASE WHEN EXISTS (SELECT 1 FROM planes_membresia
                          WHERE nombre = 'Senior 3 meses' AND activo
                            AND precio = 145.00)
            THEN 'OK    Senior 3 meses a $145'
            ELSE 'FALTA cargar Senior 3 meses a $145' END;

SELECT CASE WHEN EXISTS (SELECT 1 FROM planes_membresia
                          WHERE nombre = 'Membresia Junior' OR nombre LIKE 'Membres%Junior')
            THEN CASE WHEN (SELECT precio FROM planes_membresia
                             WHERE nombre LIKE 'Membres%Junior') = 65.00
                      THEN 'OK    Membresia Junior a $65'
                      ELSE 'FALTA correr alter-precios-iva.sql: la Junior esta en $'
                           || (SELECT precio FROM planes_membresia
                                WHERE nombre LIKE 'Membres%Junior') END
            ELSE 'FALTA no existe la Membresia Junior' END;

SELECT CASE WHEN EXISTS (SELECT 1 FROM planes_membresia
                          WHERE nombre LIKE 'Promo jueves%' AND activo)
            THEN 'OK    existe la Promo jueves'
            ELSE 'FALTA la Promo jueves no esta cargada' END;

SELECT CASE WHEN (SELECT COUNT(*) FROM planes_membresia
                   WHERE activo AND permite_descuento) = 1
            THEN 'OK    solo un plan permite descuento (la Junior)'
            ELSE 'REVISAR permiten descuento: '
                 || (SELECT string_agg(nombre, ', ') FROM planes_membresia
                      WHERE activo AND permite_descuento) END;

SELECT CASE WHEN EXISTS (SELECT 1 FROM productos
                          WHERE lower(nombre) = 'cubo de magnesio' AND activo)
            THEN 'OK    cubo de magnesio como producto'
            ELSE 'FALTA el cubo de magnesio no esta cargado' END;

SELECT '';

-- ---------- 3. Configuracion ----------
SELECT CASE WHEN (SELECT valor FROM configuracion WHERE clave = 'iva_porcentaje') = '15'
            THEN 'OK    IVA en 15%'
            ELSE 'REVISAR IVA en '
                 || COALESCE((SELECT valor FROM configuracion
                               WHERE clave = 'iva_porcentaje'), 'sin definir') END;

SELECT CASE WHEN COUNT(*) = 4
            THEN 'OK    estan las 4 claves de datos del gym'
            ELSE 'FALTA correr alter-correos-evento.sql (claves de datos del'
                 || ' gym: ' || COUNT(*) || ' de 4). Llega con los correos'
                 || ' de eventos; si todavia no mezclaste ese cambio, es'
                 || ' lo esperado.' END
  FROM configuracion
 WHERE clave IN ('gym_direccion', 'gym_mapa_url', 'gym_telefono', 'gym_que_traer');

SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM configuracion WHERE clave = 'gym_direccion')
            THEN '      (la direccion se carga cuando esas claves existan)'
            WHEN COALESCE((SELECT NULLIF(btrim(valor), '') FROM configuracion
                            WHERE clave = 'gym_direccion'), '') = ''
            THEN 'PENDIENTE cargar la direccion del gym en Configuracion'
            ELSE 'OK    direccion del gym cargada' END;

SELECT '';

-- ---------- 4. Facturas emitidas ----------
SELECT CASE WHEN COUNT(*) = 0
            THEN 'OK    todas las facturas cuadran (base + IVA = total)'
            ELSE 'REVISAR ' || COUNT(*) || ' factura(s) donde base + IVA <> total.'
                 || ' Si son anteriores al cambio de IVA es normal: se'
                 || ' cobraron con el calculo viejo y no se tocan.' END
  FROM facturas
 WHERE estado <> 'ANULADA' AND subtotal - (subtotal * descuento_porcentaje / 100) <> total;

SELECT '';
SELECT 'Si algo dice FALTA, corre la migracion que indica.';
SELECT 'PENDIENTE no es un error: es algo que cargas desde la app.';
