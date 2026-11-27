-- ============================================================
-- Borrar las facturas que se emitieron probando el SRI
--
-- Son las del entorno de desarrollo: no tienen valor tributario y
-- ensucian la contabilidad y los Excel de Contífico.
--
-- Este archivo reemplaza a alter-contifico-sri-ya-emitidas.sql, que
-- marcaba esas mismas facturas como ya cargadas para que no se
-- volvieran a facturar. Si las facturas se borran, no hay nada que
-- marcar: correr los dos no tiene sentido.
--
-- ESTO NO SE DESHACE. Antes de correrlo, saque un respaldo:
--
--   pg_dump -U postgres -d totem -Fc -f antes-de-borrar-sri.dump
--
-- Si algo sale mal, se restaura con:
--
--   pg_restore -U postgres -d totem --clean antes-de-borrar-sri.dump
--
-- Cómo aplicarlo, desde la carpeta Sql:
--
--   psql -U postgres -d totem -f borrar-facturas-sri-de-prueba.sql
--
-- QUÉ SE LLEVA, además de la factura:
--
--   - Sus líneas (se van solas, por la llave foránea).
--   - Su membresía, aunque esté vigente. Si alguna de esas personas
--     es un cliente real que pagó, queda sin membresía y hay que
--     volver a cobrarle: el primer SELECT es para verlo antes.
--   - El registro de los correos que se le mandaron.
--   - Los pagos de fiado asociados, si los hubiera.
--
-- QUÉ NO SE LLEVA:
--
--   - La bitácora. Es el registro de quién hizo qué y cuándo, y
--     borrarlo es justo lo contrario de para qué existe. Queda
--     hablando de facturas que ya no están, que es lo correcto.
-- ============================================================

\echo ''
\echo '=== LO QUE SE VA A BORRAR ==='

SELECT f.numero_factura,
       f.fecha::date       AS fecha,
       f.total,
       f.sri_estado,
       c.nombre || ' ' || c.apellido AS cliente,
       (SELECT COUNT(*) FROM membresias m
         WHERE m.id_factura = f.id_factura)              AS membresias,
       (SELECT COUNT(*) FROM membresias m
         WHERE m.id_factura = f.id_factura
           AND m.fecha_fin >= CURRENT_DATE)              AS vigentes_hoy
  FROM facturas f
  LEFT JOIN clientes c ON c.id_cliente = f.id_cliente
 WHERE f.sri_estado IS NOT NULL
 ORDER BY f.fecha;

\echo ''
\echo '=== CLIENTES QUE SE QUEDAN SIN MEMBRESIA VIGENTE ==='
\echo '(si acá aparece alguien real, deténgase: Ctrl-C antes de seguir)'

SELECT c.nombre || ' ' || c.apellido AS cliente,
       c.cedula,
       m.fecha_inicio::date,
       m.fecha_fin::date
  FROM membresias m
  JOIN facturas f ON f.id_factura = m.id_factura
  LEFT JOIN clientes c ON c.id_cliente = m.id_cliente
 WHERE f.sri_estado IS NOT NULL
   AND m.fecha_fin >= CURRENT_DATE
 ORDER BY m.fecha_fin;

\prompt 'Escriba BORRAR y Enter para continuar (o Ctrl-C para salir): ' respuesta

-- La confirmación se evalúa acá, fuera de la transacción: con un
-- Enter distraído el script termina sin tocar nada.
SELECT upper(:'respuesta') = 'BORRAR' AS seguir \gset

\if :seguir

BEGIN;

-- En orden, de lo que cuelga hacia la factura. Las líneas del detalle
-- se van solas: su llave foránea es ON DELETE CASCADE.

DELETE FROM envios_correo
 WHERE id_factura IN (SELECT id_factura FROM facturas
                       WHERE sri_estado IS NOT NULL);

DELETE FROM pagos_fiado
 WHERE id_factura IN (SELECT id_factura FROM facturas
                       WHERE sri_estado IS NOT NULL);

DELETE FROM membresias
 WHERE id_factura IN (SELECT id_factura FROM facturas
                       WHERE sri_estado IS NOT NULL);

DELETE FROM facturas WHERE sri_estado IS NOT NULL;

-- Los secuenciales del SRI tampoco sirven ya: este sistema no emite.
-- Se vacía la tabla en lugar de borrarla, por si algún día se vuelve
-- a encender el interruptor y hay que empezar de cero.
DELETE FROM sri_secuenciales;

\echo ''
\echo '=== COMO QUEDO ==='

-- Tiene que dar 0. Si no da 0, algo quedó a medias.
SELECT COUNT(*) AS facturas_con_rastro_del_sri
  FROM facturas WHERE sri_estado IS NOT NULL;

-- Y nada puede quedar colgando de una factura que ya no existe.
SELECT (SELECT COUNT(*) FROM membresias m
          WHERE m.id_factura IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM facturas f
                             WHERE f.id_factura = m.id_factura))
           AS membresias_huerfanas,
       (SELECT COUNT(*) FROM envios_correo e
          WHERE e.id_factura IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM facturas f
                             WHERE f.id_factura = e.id_factura))
           AS correos_huerfanos;

COMMIT;

\echo ''
\echo 'Listo. Revise los totales del mes en Contabilidad: cambiaron.'

\else

\echo ''
\echo 'Cancelado: no se escribió BORRAR. No se borró nada.'

\endif
