-- ============================================================
-- Bloque de captación: coaches y posibles clientes
-- Acordado en la reunión del 23/10/2026
-- ============================================================
-- Lleva una base existente al estado del esquema v4 SIN borrar nada.
--
-- Úsalo si ya tienes datos cargados que no quieres perder. Si vas a
-- recrear la base desde cero, NO corras este archivo: usa directamente
-- totem-schema-v4.sql, que ya lo trae todo.
--
--   psql -U postgres -d totem -f alter-captacion.sql
--
-- Incluye también los cambios de tipos de membresía, por si todavía no
-- corriste alter-tipos-membresia.sql. Si ya lo corriste, esa parte no
-- hace nada: está escrita para poder repetirse sin romper.

SET client_encoding = 'UTF8';

BEGIN;

-- ============================================================
-- 1. EMPLEADOS: coaches sin acceso al sistema
-- ============================================================
-- Un coach no entra al sistema, así que usuario, contraseña y rol
-- pasan a ser opcionales. Ser coach es independiente del rol: así una
-- misma persona puede ser vendedora y coach a la vez.

ALTER TABLE empleados
    ADD COLUMN IF NOT EXISTS es_coach BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE empleados ALTER COLUMN usuario DROP NOT NULL;
ALTER TABLE empleados ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE empleados ALTER COLUMN rol DROP NOT NULL;
ALTER TABLE empleados ALTER COLUMN rol DROP DEFAULT;

ALTER TABLE empleados DROP CONSTRAINT IF EXISTS chk_empleado_rol;
ALTER TABLE empleados ADD CONSTRAINT chk_empleado_rol
    CHECK (rol IS NULL OR rol IN ('ADMIN', 'VENDEDOR'));

-- O se tiene acceso completo (rol + credenciales) o no se tiene
-- ninguno. Sin esta regla podría quedar un empleado con rol pero sin
-- contraseña, que es una puerta de entrada abierta.
ALTER TABLE empleados DROP CONSTRAINT IF EXISTS chk_empleado_acceso;
ALTER TABLE empleados ADD CONSTRAINT chk_empleado_acceso
    CHECK (
        (rol IS NOT NULL AND usuario IS NOT NULL AND password_hash IS NOT NULL)
        OR
        (rol IS NULL AND usuario IS NULL AND password_hash IS NULL)
    );

-- Una fila sin rol y sin ser coach no representa a nadie.
ALTER TABLE empleados DROP CONSTRAINT IF EXISTS chk_empleado_funcion;
ALTER TABLE empleados ADD CONSTRAINT chk_empleado_funcion
    CHECK (rol IS NOT NULL OR es_coach);

-- Por si vienes de una base anterior a alter-empleados.sql.
ALTER TABLE empleados
    ADD COLUMN IF NOT EXISTS fecha_nacimiento DATE;


-- ============================================================
-- 2. POSIBLES CLIENTES
-- ============================================================
-- Quien asiste a una clase demo sin ser todavía cliente.
-- La fecha de la clase NO está aquí: sale de su inscripción al evento,
-- para no guardar el mismo dato en dos lados.

CREATE TABLE IF NOT EXISTS posibles_clientes (
    id_posible SERIAL PRIMARY KEY,

    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    -- Obligatorio: es la llave con la que se detecta la conversión.
    correo VARCHAR(150) NOT NULL,
    telefono VARCHAR(10),

    id_coach INTEGER,
    id_empleado INTEGER NOT NULL,

    asistio BOOLEAN,

    id_cliente INTEGER UNIQUE,
    fecha_conversion TIMESTAMP,

    fecha_registro TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_posible_coach
        FOREIGN KEY (id_coach) REFERENCES empleados(id_empleado),
    CONSTRAINT fk_posible_empleado
        FOREIGN KEY (id_empleado) REFERENCES empleados(id_empleado),
    CONSTRAINT fk_posible_cliente
        FOREIGN KEY (id_cliente) REFERENCES clientes(id_cliente),

    CONSTRAINT chk_posible_conversion
        CHECK (
            (id_cliente IS NULL AND fecha_conversion IS NULL)
            OR
            (id_cliente IS NOT NULL AND fecha_conversion IS NOT NULL)
        )
);


-- ============================================================
-- 3. INSCRITOS: ahora puede ser cliente O posible cliente
-- ============================================================

ALTER TABLE evento_inscritos
    ADD COLUMN IF NOT EXISTS id_posible INTEGER;

ALTER TABLE evento_inscritos ALTER COLUMN id_cliente DROP NOT NULL;

ALTER TABLE evento_inscritos DROP CONSTRAINT IF EXISTS fk_inscrito_posible;
ALTER TABLE evento_inscritos ADD CONSTRAINT fk_inscrito_posible
    FOREIGN KEY (id_posible) REFERENCES posibles_clientes(id_posible);

ALTER TABLE evento_inscritos DROP CONSTRAINT IF EXISTS chk_inscrito_quien;
ALTER TABLE evento_inscritos ADD CONSTRAINT chk_inscrito_quien
    CHECK (
        (id_cliente IS NOT NULL AND id_posible IS NULL)
        OR
        (id_cliente IS NULL AND id_posible IS NOT NULL)
    );

-- OJO: el UNIQUE viejo deja de proteger en cuanto id_cliente admite
-- nulos, porque Postgres considera distintos dos NULL. Hay que
-- reemplazarlo por índices únicos parciales.
ALTER TABLE evento_inscritos
    DROP CONSTRAINT IF EXISTS uq_inscrito_evento_cliente;

DROP INDEX IF EXISTS uq_inscrito_evento_cliente;
CREATE UNIQUE INDEX uq_inscrito_evento_cliente
    ON evento_inscritos(id_evento, id_cliente)
    WHERE id_cliente IS NOT NULL;

DROP INDEX IF EXISTS uq_inscrito_evento_posible;
CREATE UNIQUE INDEX uq_inscrito_evento_posible
    ON evento_inscritos(id_evento, id_posible)
    WHERE id_posible IS NOT NULL;


-- ============================================================
-- 4. BITÁCORA: acciones y entidades nuevas
-- ============================================================

ALTER TABLE bitacora DROP CONSTRAINT IF EXISTS chk_bitacora_accion;
ALTER TABLE bitacora ADD CONSTRAINT chk_bitacora_accion
    CHECK (accion IN (
        'CLIENTE_CREADO', 'CLIENTE_EDITADO',
        'FACTURA_EMITIDA', 'FACTURA_ANULADA', 'ABONO_REGISTRADO',
        'INSCRIPCION_REGISTRADA', 'INSCRIPCION_CANCELADA',
        'ASISTENCIA_MARCADA',
        'IVA_CAMBIADO',
        'ITEM_CREADO', 'ITEM_EDITADO', 'ITEM_DESACTIVADO', 'ITEM_REACTIVADO',
        'EMPLEADO_CREADO', 'EMPLEADO_EDITADO', 'EMPLEADO_DESACTIVADO',
        'EMPLEADO_REACTIVADO', 'PASSWORD_CAMBIADA',
        'CORREO_ENVIADO', 'CORREO_FALLIDO',
        'POSIBLE_CREADO', 'POSIBLE_EDITADO', 'COACH_ASIGNADO',
        'POSIBLE_CONVERTIDO',
        'GASTO_REGISTRADO', 'GASTO_EDITADO', 'GASTO_ANULADO'
    ));

ALTER TABLE bitacora DROP CONSTRAINT IF EXISTS chk_bitacora_entidad;
ALTER TABLE bitacora ADD CONSTRAINT chk_bitacora_entidad
    CHECK (entidad IN (
        'CLIENTE', 'FACTURA', 'PAGO_FIADO', 'INSCRIPCION',
        'CONFIGURACION', 'PRODUCTO', 'PLAN', 'EMPLEADO',
        'POSIBLE_CLIENTE', 'GASTO'
    ));


-- ============================================================
-- 5. TIPOS DE MEMBRESÍA (por si falta)
-- ============================================================
-- El orden importa: la restricción vieja de entradas exige que un plan
-- con entradas SEA de tipo PASES, así que bloquea el cambio de tipo si
-- no se suelta primero.

ALTER TABLE planes_membresia DROP CONSTRAINT IF EXISTS chk_plan_dias_incluidos;
ALTER TABLE planes_membresia DROP CONSTRAINT IF EXISTS chk_plan_tipo;

UPDATE planes_membresia SET tipo = 'SENIOR' WHERE tipo = 'PASES';

ALTER TABLE planes_membresia ADD CONSTRAINT chk_plan_tipo
    CHECK (tipo IN ('JUNIOR', 'SENIOR'));

ALTER TABLE planes_membresia ADD CONSTRAINT chk_plan_dias_incluidos
    CHECK (
        dias_incluidos IS NULL
        OR (dias_incluidos > 0 AND unidad_duracion = 'DIA')
    );


-- ============================================================
-- 6. ÍNDICES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_empleados_coach
    ON empleados(es_coach) WHERE es_coach;
CREATE INDEX IF NOT EXISTS idx_posibles_correo
    ON posibles_clientes(correo);
CREATE INDEX IF NOT EXISTS idx_posibles_coach
    ON posibles_clientes(id_coach);
CREATE INDEX IF NOT EXISTS idx_posibles_cliente
    ON posibles_clientes(id_cliente);
CREATE INDEX IF NOT EXISTS idx_evento_inscritos_posible
    ON evento_inscritos(id_posible);
CREATE INDEX IF NOT EXISTS idx_clientes_correo
    ON clientes(correo);

COMMIT;


-- ============================================================
-- PERMISOS
-- ============================================================
-- Si la app NO se conecta como postgres, la tabla nueva queda a nombre
-- de quien corrió este script y la app no puede ni leerla.
-- Descomenta y reemplaza 'mi_usuario' por el de tu DATABASE_URL:
--
-- GRANT SELECT, INSERT, UPDATE, DELETE ON posibles_clientes TO mi_usuario;
-- GRANT USAGE, SELECT ON SEQUENCE posibles_clientes_id_posible_seq TO mi_usuario;


-- Comprobación rápida:
--   SELECT nombre, usuario, rol, es_coach FROM empleados;
--   SELECT count(*) FROM posibles_clientes;
