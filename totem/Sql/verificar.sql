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
SELECT CASE WHEN COUNT(*) >= 20 THEN 'OK    ' || COUNT(*) || ' tablas'
            ELSE 'FALTA tablas: hay ' || COUNT(*) || ', deberian ser 20 o mas' END
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

-- Por contenido y no por nombre exacto. Buscaba 'cubo de magnesio' y
-- en el gimnasio esta cargado como 'Magnesio Cubo', asi que daba
-- FALTA sobre un producto que existia. Una verificacion que se
-- equivoca asi es peor que no tenerla: manda a cargar algo que ya
-- esta, o peor, a renombrarlo para que la verificacion quede
-- contenta. Lo que importa es que haya magnesio, no como se llame.
SELECT CASE WHEN EXISTS (SELECT 1 FROM productos
                          WHERE lower(nombre) LIKE '%magnesio%' AND activo)
            THEN 'OK    magnesio como producto ('
                 || (SELECT string_agg(nombre, ', ' ORDER BY nombre)
                       FROM productos
                      WHERE lower(nombre) LIKE '%magnesio%' AND activo)
                 || ')'
            ELSE 'FALTA no hay ningun producto de magnesio cargado' END;

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
-- Las facturas donde el subtotal menos el descuento no da el total.
--
-- Antes del cambio de IVA el subtotal guardaba la base y el total le
-- sumaba el IVA encima: subtotal + iva = total. Ahora los precios ya
-- incluyen IVA, el subtotal tambien, y la columna iva guarda el IVA
-- CONTENIDO en el total, no sumado encima; asi que subtotal menos
-- descuento tiene que dar el total exacto.
--
-- La distincion se hace con el iva guardado en cada factura y no
-- suponiendo una tasa, porque entre las viejas hay cobradas al 12% y
-- al 14%.
--
-- Este aviso antes decia "si son anteriores al cambio de IVA es
-- normal" y dejaba la decision al que lo leia. Un aviso que siempre
-- hay que interpretar es un aviso que se acaba ignorando, asi que
-- ahora la consulta lo decide: si el total coincide con el calculo
-- viejo, esta explicado y no se toca; si no coincide con ninguno de
-- los dos, no tiene explicacion y hay que mirarlo.
WITH descuadres AS (
    SELECT numero_factura, fecha, subtotal, total,
           abs(subtotal + iva - total) <= 0.02 AS calculo_viejo
      FROM facturas
     WHERE estado <> 'ANULADA'
       AND subtotal - (subtotal * descuento_porcentaje / 100) <> total
)
SELECT CASE
    WHEN (SELECT COUNT(*) FROM descuadres) = 0
        THEN 'OK    todas las facturas cuadran (subtotal - descuento = total)'
    WHEN (SELECT COUNT(*) FROM descuadres WHERE NOT calculo_viejo) = 0
        THEN 'OK    ' || (SELECT COUNT(*) FROM descuadres)
             || ' factura(s) con el calculo viejo de IVA, de '
             || (SELECT to_char(min(fecha), 'DD/MM/YYYY') FROM descuadres)
             || ' a '
             || (SELECT to_char(max(fecha), 'DD/MM/YYYY') FROM descuadres)
             || '. Es lo esperado: se cobraron asi y no se tocan.'
    ELSE 'REVISAR ' || (SELECT COUNT(*) FROM descuadres WHERE NOT calculo_viejo)
         || ' factura(s) que no cuadran ni con el calculo viejo ni con el'
         || ' nuevo: '
         || (SELECT string_agg(numero_factura, ', ' ORDER BY numero_factura)
               FROM descuadres WHERE NOT calculo_viejo)
         || '. Las otras '
         || (SELECT COUNT(*) FROM descuadres WHERE calculo_viejo)
         || ' son del calculo viejo y estan bien.'
END;

SELECT '';

-- ---------- 5. Facturacion electronica ----------
-- Las tres migraciones del SRI, en el orden en que hay que correrlas.

SELECT CASE WHEN COUNT(*) = 1
            THEN 'OK    la numeracion del SRI existe'
            ELSE 'FALTA correr alter-sri-secuenciales.sql'
                 || ' (sin esto no se puede emitir ninguna factura)' END
  FROM information_schema.tables
 WHERE table_name = 'sri_secuenciales';

SELECT CASE WHEN COUNT(*) = 10
            THEN 'OK    las facturas guardan su estado ante el SRI'
            ELSE 'FALTA correr alter-sri-secuenciales.sql (campos sri_ en'
                 || ' facturas: ' || COUNT(*) || ' de 10)' END
  FROM information_schema.columns
 WHERE table_name = 'facturas' AND column_name LIKE 'sri_%';

SELECT CASE WHEN COUNT(*) = 2
            THEN 'OK    las facturas en bloque de productos existen'
            ELSE 'FALTA correr alter-sri-bloques.sql (tablas presentes: '
                 || COUNT(*) || ' de 2)' END
  FROM information_schema.tables
 WHERE table_name IN ('facturas_bloque', 'detalle_bloque');

SELECT CASE WHEN COUNT(*) = 1
            THEN 'OK    se puede marcar lo ya facturado en bloque'
            ELSE 'FALTA correr alter-sri-bloques.sql'
                 || ' (detalle_factura.unidades_en_bloque)' END
  FROM information_schema.columns
 WHERE table_name = 'detalle_factura'
   AND column_name = 'unidades_en_bloque';

SELECT CASE WHEN pg_get_constraintdef(oid) LIKE '%COMPROBANTE_REEMITIDO%'
            THEN 'OK    la bitacora acepta las acciones del SRI'
            ELSE 'FALTA correr alter-bitacora-sri.sql (sin esto, reemitir'
                 || ' una factura rechazada no queda registrado)' END
  FROM pg_constraint
 WHERE conname = 'chk_bitacora_accion';

-- Rebotes de correo: saber cuales comprobantes NO llegaron.
SELECT CASE WHEN COUNT(*) = 2
            THEN 'OK    los correos enviados quedan registrados'
            ELSE 'FALTA correr alter-envios-correo.sql (sin esto, un'
                 || ' comprobante que rebota se da por entregado)' END
  FROM information_schema.tables
 WHERE table_name IN ('envios_correo', 'rebotes_revision');

SELECT CASE WHEN COUNT(*) = 2
            THEN 'OK    la ficha del cliente avisa si su correo rebota'
            ELSE 'FALTA correr alter-envios-correo.sql' END
  FROM information_schema.columns
 WHERE table_name = 'clientes'
   AND column_name IN ('correo_rebotado_en', 'correo_rebote_motivo');

-- Y el punto de emision cargado, que es lo unico de esta seccion que
-- no arregla una migracion sino una decision: cual usa el gimnasio.
--
-- Se consulta solo si la tabla existe. Postgres analiza la consulta
-- entera antes de ejecutarla, asi que una consulta a una tabla que
-- no existe falla aunque este dentro de un CASE que no se cumple, y
-- cortaria la verificacion justo donde mas falta hace.
SELECT to_regclass('public.sri_secuenciales') IS NOT NULL AS hay_numeracion
\gset

\if :hay_numeracion
SELECT CASE WHEN COUNT(*) > 0
            THEN 'OK    punto de emision ' || MIN(establecimiento) || '-'
                 || MIN(punto_emision) || ', ultimo numero emitido: '
                 || MAX(ultimo_secuencial)
            ELSE 'PENDIENTE no hay ningun punto de emision cargado.'
                 || ' Revisa alter-sri-secuenciales.sql' END
  FROM sri_secuenciales
 WHERE tipo_comprobante = '01';
\else
SELECT 'PENDIENTE el punto de emision se revisa despues de correr'
       || ' alter-sri-secuenciales.sql';
\endif

-- ============================================================
-- El cierre
--
-- Antes este final imprimia siempre la lista de migraciones en
-- orden, incluso despues de una corrida donde todo estaba OK. Un
-- "haga esto en este orden" impreso al pie de un reporte limpio se
-- lee como una instruccion pendiente, y hace dudar a quien lo corre.
-- Ahora el archivo dice que falta solo cuando falta algo.
-- ============================================================

SELECT '';

-- Falta alguna migracion?
SELECT (
    to_regclass('public.sri_secuenciales') IS NULL
 OR to_regclass('public.facturas_bloque')  IS NULL
 OR to_regclass('public.detalle_bloque')   IS NULL
 OR to_regclass('public.envios_correo')    IS NULL
 OR to_regclass('public.rebotes_revision') IS NULL
 OR NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'detalle_factura'
                   AND column_name = 'unidades_en_bloque')
 OR NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'clientes'
                   AND column_name = 'correo_rebotado_en')
) AS falta_migracion
\gset

-- Y hay algo que cargar desde la aplicacion?
SELECT COALESCE((SELECT NULLIF(btrim(valor), '') FROM configuracion
                  WHERE clave = 'gym_direccion'), '') = '' AS hay_pendiente
\gset

\if :falta_migracion
SELECT 'Donde dice FALTA, corre esa migracion. Van en este orden:';
SELECT '';
SELECT '  1. alter-sri-secuenciales.sql';
SELECT '  2. alter-sri-bloques.sql';
SELECT '  3. alter-bitacora-sri.sql';
SELECT '  4. alter-envios-correo.sql';
SELECT '';
SELECT 'El orden importa: la de bitacora modifica una restriccion que';
SELECT 'usan las otras.';
\else
SELECT 'Todas las migraciones estan aplicadas.';
\endif

\if :hay_pendiente
SELECT '';
SELECT 'PENDIENTE no es un error ni una migracion: es un dato que se';
SELECT 'carga desde la aplicacion, en Configuracion.';
\endif
