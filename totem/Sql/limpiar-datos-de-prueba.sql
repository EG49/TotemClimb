SET client_encoding = 'UTF8';

-- ============================================================
-- TOTEM CLIMB GYM - QUITAR LO QUE DEJO pruebas_v4.sql
-- ============================================================
-- La version vieja de pruebas_v4.sql insertaba en ocho tablas y
-- no limpiaba nada. Si la corriste, te quedaron filas inventadas
-- mezcladas con tus datos: entre ellas el plan "Pase 20 dias",
-- que aparecia en el catalogo como si fuera un plan real.
--
-- Esto las quita. Solo borra filas que coinciden EXACTAMENTE con
-- lo que insertaba ese archivo, y antes de borrar un plan
-- comprueba que nunca se haya vendido.
--
--   psql -U postgres -d totem -f limpiar-datos-de-prueba.sql
--
-- La version actual de pruebas_v4.sql ya no deja nada: corre todo
-- dentro de una transaccion que descarta al final. Este archivo
-- es solo para bases que corrieron la version vieja.
-- ============================================================

BEGIN;

-- ---------- Informe de lo que hay ----------
\pset tuples_only on
SELECT 'Antes de limpiar:';
SELECT '  planes de prueba:    ' || count(*) FROM planes_membresia
 WHERE nombre IN ('Pase 20 dias', 'Viejo', 'Raro');
SELECT '  empleados de prueba: ' || count(*) FROM empleados
 WHERE (nombre = 'Diego'  AND apellido = 'Coach')
    OR (nombre = 'Camila' AND apellido = 'Rojas')
    OR nombre = 'Malo';
SELECT '  posibles de prueba:  ' || count(*) FROM posibles_clientes
 WHERE correo IN ('ana@correo.com', 'bea@correo.com');
SELECT '  clientes de prueba:  ' || count(*) FROM clientes
 WHERE nombre = 'Shirley' AND apellido = 'Guevara' AND cedula IS NULL;
SELECT '  eventos de prueba:   ' || count(*) FROM eventos
 WHERE titulo = 'Clase demo' AND hora_inicio = '13:00' AND hora_fin = '14:00';
\pset tuples_only off

-- ---------- Inscripciones y eventos ----------
-- Primero las inscripciones: apuntan al evento y a los posibles.
DELETE FROM evento_inscritos
 WHERE id_evento IN (
    SELECT id_evento FROM eventos
     WHERE titulo = 'Clase demo'
       AND hora_inicio = '13:00' AND hora_fin = '14:00'
 );

DELETE FROM eventos
 WHERE titulo = 'Clase demo'
   AND hora_inicio = '13:00' AND hora_fin = '14:00'
   AND NOT EXISTS (
    SELECT 1 FROM evento_inscritos i WHERE i.id_evento = eventos.id_evento
 );

-- ---------- Posibles clientes ----------
DELETE FROM posibles_clientes
 WHERE correo IN ('ana@correo.com', 'bea@correo.com');

-- ---------- Cliente de prueba ----------
-- Solo si no tiene nada colgando: si le facturaron algo, no es el
-- de la prueba o ya no conviene tocarlo.
DELETE FROM clientes
 WHERE nombre = 'Shirley' AND apellido = 'Guevara'
   AND cedula IS NULL AND correo IS NULL
   AND NOT EXISTS (SELECT 1 FROM facturas f  WHERE f.id_cliente = clientes.id_cliente)
   AND NOT EXISTS (SELECT 1 FROM membresias m WHERE m.id_cliente = clientes.id_cliente);

-- ---------- Gastos ----------
-- Los de prueba son los que insertaba el archivo: montos y
-- conceptos exactos, y registrados por el empleado 1.
DELETE FROM gastos
 WHERE id_empleado = 1
   AND fecha = CURRENT_DATE
   AND (
        (monto = 800 AND segmento = 'GENERAL' AND concepto = 'Arriendo')
     OR (monto = 120 AND segmento = 'JUNIOR'  AND concepto = 'Equipo'
         AND descripcion = 'Colchonetas nuevas')
     OR (monto = 45  AND segmento = 'GENERAL' AND concepto = 'Luz' AND facturado)
     OR (monto = 50  AND segmento = 'GENERAL' AND concepto = 'Luz'
         AND motivo_anulacion = 'Cargado dos veces')
   );

-- ---------- Bitacora ----------
-- Las tres anotaciones sueltas que no vinieron de una accion real:
-- no tienen detalle, que el servicio siempre escribe.
DELETE FROM bitacora
 WHERE id_empleado = 1
   AND detalle IS NULL
   AND fecha::date = CURRENT_DATE
   AND (
        (accion = 'GASTO_REGISTRADO'   AND entidad = 'GASTO'           AND id_entidad = 1)
     OR (accion = 'POSIBLE_CONVERTIDO' AND entidad = 'POSIBLE_CLIENTE' AND id_entidad = 1)
   );

-- ---------- Empleados ----------
-- Se borran despues de los posibles y las inscripciones, que los
-- referencian. Solo si no quedaron apuntando a nada real.
DELETE FROM empleados e
 WHERE (
        (e.nombre = 'Diego'  AND e.apellido = 'Coach')
     OR (e.nombre = 'Camila' AND e.apellido = 'Rojas' AND e.usuario = 'camila')
     OR (e.nombre = 'Malo')
   )
   AND NOT EXISTS (SELECT 1 FROM facturas f           WHERE f.id_empleado = e.id_empleado)
   AND NOT EXISTS (SELECT 1 FROM gastos g             WHERE g.id_empleado = e.id_empleado)
   AND NOT EXISTS (SELECT 1 FROM bitacora b           WHERE b.id_empleado = e.id_empleado)
   AND NOT EXISTS (SELECT 1 FROM posibles_clientes p  WHERE p.id_empleado = e.id_empleado
                                                         OR p.id_coach    = e.id_empleado)
   AND NOT EXISTS (SELECT 1 FROM evento_inscritos i   WHERE i.id_empleado = e.id_empleado);

-- ---------- Planes ----------
-- Un plan solo se borra si NUNCA se vendio. Si se vendio, se
-- desactiva: las facturas tienen que seguir diciendo que se
-- vendio, aunque el plan ya no se ofrezca.
DELETE FROM planes_membresia p
 WHERE p.nombre IN ('Pase 20 dias', 'Viejo', 'Raro')
   AND NOT EXISTS (SELECT 1 FROM membresias m      WHERE m.id_plan = p.id_plan)
   AND NOT EXISTS (SELECT 1 FROM detalle_factura d WHERE d.id_plan = p.id_plan);

UPDATE planes_membresia
   SET activo = FALSE
 WHERE nombre IN ('Pase 20 dias', 'Viejo', 'Raro');

COMMIT;

-- ============================================================
-- COMPROBACION
-- ============================================================
\pset tuples_only on
SELECT '';
SELECT 'Despues de limpiar:';
SELECT CASE WHEN count(*) = 0 THEN '  OK    no quedan planes de prueba'
            ELSE '  REVISAR quedan ' || count(*) ||
                 ' plan(es) de prueba, desactivados porque ya se vendieron' END
  FROM planes_membresia WHERE nombre IN ('Pase 20 dias', 'Viejo', 'Raro');

SELECT CASE WHEN count(*) = 0 THEN '  OK    no quedan empleados de prueba'
            ELSE '  REVISAR quedan ' || count(*) || ' empleado(s) de prueba' END
  FROM empleados
 WHERE (nombre = 'Diego' AND apellido = 'Coach')
    OR (nombre = 'Camila' AND apellido = 'Rojas')
    OR nombre = 'Malo';

SELECT CASE WHEN count(*) = 0 THEN '  OK    no quedan posibles de prueba'
            ELSE '  REVISAR quedan ' || count(*) || ' posible(s) de prueba' END
  FROM posibles_clientes WHERE correo IN ('ana@correo.com', 'bea@correo.com');

SELECT '';
SELECT 'Catalogo que queda activo:';
\pset tuples_only off
SELECT nombre, precio, tipo, permite_descuento AS descuento, permite_pareja AS pareja
  FROM planes_membresia WHERE activo ORDER BY tipo, precio;
