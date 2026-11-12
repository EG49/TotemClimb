SET client_encoding = 'UTF8';

-- ============================================================
-- TOTEM CLIMB GYM - DATOS DEL GIMNASIO PARA LOS CORREOS
-- ============================================================
-- Punto 13 del backlog: correos de confirmacion y recordatorio de
-- las clases. Esos correos tienen que decir donde queda el gym y
-- a que numero escribir, y eso no se puede escribir en el codigo:
-- se carga una vez desde Configuracion.
--
-- Dos cambios:
--
--   1. configuracion.valor pasa a TEXT. Estaba en VARCHAR(100) y
--      un enlace de Google Maps no entra ahi.
--
--   2. Cuatro claves nuevas, vacias. Arrancan vacias a proposito:
--      un correo con una direccion inventada es peor que un correo
--      sin direccion.
--
--   psql -U postgres -d totem -f alter-correos-evento.sql
--
-- Si la base se crea de cero con totem-schema-v4.sql, este archivo
-- NO hace falta.
-- ============================================================

BEGIN;

ALTER TABLE configuracion ALTER COLUMN valor TYPE TEXT;

INSERT INTO configuracion (clave, valor, descripcion)
SELECT v.clave, '', v.descripcion
  FROM (VALUES
        ('gym_direccion', 'Direccion del gimnasio, tal como va en los correos'),
        ('gym_mapa_url',  'Enlace de Google Maps al gimnasio. Se pega el que da "Compartir"'),
        ('gym_telefono',  'Celular o WhatsApp de contacto que se muestra en los correos'),
        ('gym_que_traer', 'Que llevar a la clase de prueba. Sale en el correo de confirmacion')
       ) AS v(clave, descripcion)
 WHERE NOT EXISTS (
    SELECT 1 FROM configuracion c WHERE c.clave = v.clave
 );

COMMIT;

-- Comprobacion
\pset tuples_only on
SELECT CASE WHEN data_type = 'text'
            THEN 'OK    configuracion.valor acepta textos largos'
            ELSE 'FALLA configuracion.valor sigue siendo ' || data_type END
  FROM information_schema.columns
 WHERE table_name = 'configuracion' AND column_name = 'valor';

SELECT CASE WHEN count(*) = 4 THEN 'OK    estan las 4 claves del gym'
            ELSE 'FALLA hay ' || count(*) || ' de 4 claves' END
  FROM configuracion
 WHERE clave IN ('gym_direccion', 'gym_mapa_url', 'gym_telefono', 'gym_que_traer');

SELECT '';
SELECT 'Ahora carga la direccion y el enlace del mapa desde Configuracion.';
SELECT 'Sin direccion los correos salen igual, solo que sin esa parte.';

-- ============================================================
-- BITACORA: acciones y entidades nuevas
-- ============================================================
-- DATOS_GYM_CAMBIADOS para la pantalla de Configuracion, y la
-- entidad EVENTO para anotar los correos de clases contra el
-- evento y no contra una factura.
BEGIN;

ALTER TABLE bitacora DROP CONSTRAINT IF EXISTS chk_bitacora_accion;
ALTER TABLE bitacora ADD CONSTRAINT chk_bitacora_accion
    CHECK (accion IN (
        'CLIENTE_CREADO','CLIENTE_EDITADO',
        'FACTURA_EMITIDA','FACTURA_ANULADA','ABONO_REGISTRADO',
        'INSCRIPCION_REGISTRADA','INSCRIPCION_CANCELADA','ASISTENCIA_MARCADA',
        'IVA_CAMBIADO','DATOS_GYM_CAMBIADOS',
        'ITEM_CREADO','ITEM_EDITADO','ITEM_DESACTIVADO','ITEM_REACTIVADO',
        'EMPLEADO_CREADO','EMPLEADO_EDITADO','EMPLEADO_DESACTIVADO',
        'EMPLEADO_REACTIVADO','PASSWORD_CAMBIADA',
        'CORREO_ENVIADO','CORREO_FALLIDO',
        'POSIBLE_CREADO','POSIBLE_EDITADO','COACH_ASIGNADO','POSIBLE_CONVERTIDO',
        'GASTO_REGISTRADO','GASTO_EDITADO','GASTO_ANULADO'
    ));

ALTER TABLE bitacora DROP CONSTRAINT IF EXISTS chk_bitacora_entidad;
ALTER TABLE bitacora ADD CONSTRAINT chk_bitacora_entidad
    CHECK (entidad IN (
        'CLIENTE','FACTURA','PAGO_FIADO','INSCRIPCION','CONFIGURACION',
        'PRODUCTO','PLAN','EMPLEADO','POSIBLE_CLIENTE','GASTO','EVENTO'
    ));

COMMIT;

\pset tuples_only on
SELECT 'OK    la bitacora acepta DATOS_GYM_CAMBIADOS y la entidad EVENTO';
