SET client_encoding = 'UTF8';
\set ON_ERROR_STOP off
\pset tuples_only on

-- Cada bloque debe decir OK. "DEBERIA HABER FALLADO" marca un hueco.
CREATE OR REPLACE FUNCTION probar(etiqueta TEXT, sentencia TEXT, debe_fallar BOOLEAN)
RETURNS TEXT AS $$
BEGIN
    BEGIN
        EXECUTE sentencia;
    EXCEPTION WHEN OTHERS THEN
        IF debe_fallar THEN
            RETURN 'OK   rechaza: ' || etiqueta;
        ELSE
            RETURN 'FALLA: ' || etiqueta || ' -> ' || SQLERRM;
        END IF;
    END;
    IF debe_fallar THEN
        RETURN 'DEBERIA HABER FALLADO: ' || etiqueta;
    END IF;
    RETURN 'OK   acepta:  ' || etiqueta;
END;
$$ LANGUAGE plpgsql;

-- ---------- EMPLEADOS ----------
SELECT probar('coach sin credenciales',
  $$INSERT INTO empleados (nombre,apellido,es_coach) VALUES ('Diego','Coach',TRUE)$$, FALSE);
SELECT probar('vendedor que ademas es coach',
  $$INSERT INTO empleados (nombre,apellido,usuario,password_hash,rol,es_coach)
    VALUES ('Camila','Rojas','camila','hash','VENDEDOR',TRUE)$$, FALSE);
SELECT probar('empleado con rol pero sin contrasena',
  $$INSERT INTO empleados (nombre,apellido,usuario,rol) VALUES ('Malo','Uno','malo1','VENDEDOR')$$, TRUE);
SELECT probar('empleado con usuario pero sin rol',
  $$INSERT INTO empleados (nombre,apellido,usuario,password_hash) VALUES ('Malo','Dos','malo2','hash')$$, TRUE);
SELECT probar('fila que no es ni usuario ni coach',
  $$INSERT INTO empleados (nombre,apellido) VALUES ('Malo','Tres')$$, TRUE);
SELECT probar('rol inventado',
  $$INSERT INTO empleados (nombre,apellido,usuario,password_hash,rol) VALUES ('Malo','4','malo4','h','COACH')$$, TRUE);

-- ---------- PLANES ----------
SELECT probar('plan tipo PASES (ya no existe)',
  $$INSERT INTO planes_membresia (nombre,tipo,precio,duracion,unidad_duracion)
    VALUES ('Viejo','PASES',10,1,'DIA')$$, TRUE);
SELECT probar('pase Senior con dias incluidos',
  $$INSERT INTO planes_membresia (nombre,tipo,precio,duracion,unidad_duracion,dias_incluidos)
    VALUES ('Pase 20 dias','SENIOR',90,60,'DIA',20)$$, FALSE);
SELECT probar('plan mensual con dias incluidos',
  $$INSERT INTO planes_membresia (nombre,tipo,precio,duracion,unidad_duracion,dias_incluidos)
    VALUES ('Raro','SENIOR',50,1,'MES',5)$$, TRUE);

-- ---------- POSIBLES CLIENTES ----------
INSERT INTO clientes (nombre,apellido) VALUES ('Shirley','Guevara');
SELECT probar('posible cliente nuevo',
  $$INSERT INTO posibles_clientes (nombre,apellido,correo,id_coach,id_empleado)
    VALUES ('Ana','Perez','ana@correo.com',1,1)$$, FALSE);
SELECT probar('convertido sin fecha de conversion',
  $$INSERT INTO posibles_clientes (nombre,apellido,correo,id_empleado,id_cliente)
    VALUES ('Bea','Lopez','bea@correo.com',1,1)$$, TRUE);
SELECT probar('convertido con fecha',
  $$INSERT INTO posibles_clientes (nombre,apellido,correo,id_empleado,id_cliente,fecha_conversion)
    VALUES ('Bea','Lopez','bea@correo.com',1,1,now())$$, FALSE);

-- ---------- INSCRITOS ----------
INSERT INTO eventos (titulo,id_categoria,fecha,hora_inicio,hora_fin)
    VALUES ('Clase demo',1,CURRENT_DATE,'13:00','14:00');
SELECT probar('inscribir a un posible cliente',
  $$INSERT INTO evento_inscritos (id_evento,id_posible,id_empleado) VALUES (1,1,1)$$, FALSE);
SELECT probar('inscribir a un cliente',
  $$INSERT INTO evento_inscritos (id_evento,id_cliente,id_empleado) VALUES (1,1,1)$$, FALSE);
SELECT probar('inscrito que es cliente Y posible a la vez',
  $$INSERT INTO evento_inscritos (id_evento,id_cliente,id_posible,id_empleado) VALUES (1,1,2,1)$$, TRUE);
SELECT probar('inscrito que no es ninguno de los dos',
  $$INSERT INTO evento_inscritos (id_evento,id_empleado) VALUES (1,1)$$, TRUE);
SELECT probar('mismo posible cliente dos veces en el evento',
  $$INSERT INTO evento_inscritos (id_evento,id_posible,id_empleado) VALUES (1,1,1)$$, TRUE);
SELECT probar('mismo cliente dos veces en el evento',
  $$INSERT INTO evento_inscritos (id_evento,id_cliente,id_empleado) VALUES (1,1,1)$$, TRUE);

-- ---------- GASTOS ----------
SELECT probar('gasto normal sin descripcion',
  $$INSERT INTO gastos (fecha,monto,segmento,id_empleado) VALUES (CURRENT_DATE,800,'GENERAL',1)$$, FALSE);
SELECT probar('gasto con descripcion y metodo',
  $$INSERT INTO gastos (fecha,monto,segmento,descripcion,metodo_pago,id_empleado)
    VALUES (CURRENT_DATE,120,'JUNIOR','Colchonetas nuevas','EFECTIVO',1)$$, FALSE);
SELECT probar('segmento inventado',
  $$INSERT INTO gastos (fecha,monto,segmento,id_empleado) VALUES (CURRENT_DATE,50,'OTRO',1)$$, TRUE);
SELECT probar('monto cero',
  $$INSERT INTO gastos (fecha,monto,segmento,id_empleado) VALUES (CURRENT_DATE,0,'GENERAL',1)$$, TRUE);
SELECT probar('gasto anulado sin motivo',
  $$INSERT INTO gastos (fecha,monto,segmento,id_empleado,estado)
    VALUES (CURRENT_DATE,50,'GENERAL',1,'ANULADO')$$, TRUE);
SELECT probar('gasto anulado con motivo',
  $$INSERT INTO gastos (fecha,monto,segmento,id_empleado,estado,motivo_anulacion)
    VALUES (CURRENT_DATE,50,'GENERAL',1,'ANULADO','Cargado dos veces')$$, FALSE);

-- ---------- BITACORA ----------
SELECT probar('accion nueva de gasto',
  $$INSERT INTO bitacora (id_empleado,accion,entidad,id_entidad)
    VALUES (1,'GASTO_REGISTRADO','GASTO',1)$$, FALSE);
SELECT probar('accion nueva de conversion',
  $$INSERT INTO bitacora (id_empleado,accion,entidad,id_entidad)
    VALUES (1,'POSIBLE_CONVERTIDO','POSIBLE_CLIENTE',1)$$, FALSE);
SELECT probar('accion inventada',
  $$INSERT INTO bitacora (id_empleado,accion,entidad) VALUES (1,'CUALQUIER_COSA','GASTO')$$, TRUE);
