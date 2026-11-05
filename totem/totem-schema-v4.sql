-- ============================================================
-- TOTEM CLIMB GYM — ESQUEMA CONSOLIDADO v4
-- PostgreSQL 16
-- ============================================================
-- Este archivo reemplaza por completo a totem-schema-final.sql y
-- a los cuatro ALTER sueltos (productos-activo, cobrar, empleados
-- y correo). Es el único script que hay que correr.
--
-- Uso:
--   psql -U postgres -d totem -f totem-schema-v4.sql
--
-- Después:
--   python -m scripts.crear_admin
--
-- Incorpora lo acordado en la reunión del 23/10/2026:
--   * Solo dos tipos de membresía: JUNIOR y SENIOR. Los pases se
--     clasifican como SENIOR; que un plan sea pase se deduce de
--     sus días incluidos, no de su tipo.
--   * Coaches: empleados sin acceso al sistema. Ser coach es
--     independiente del rol, así una persona puede ser vendedora
--     y coach a la vez.
--   * Posibles clientes: quien asiste a una clase demo ya no
--     necesita ser cliente.
--   * Gastos, con segmento y descripción opcional, para el
--     balance.
-- ============================================================

SET client_encoding = 'UTF8';


-- ============================================================
-- 1. EMPLEADOS
-- ============================================================
-- Una fila por persona del gimnasio, entre o no al sistema.
--
-- Dos cosas distintas conviven aquí, y conviene no confundirlas:
--
--   rol      -> qué puede hacer DENTRO del sistema. Solo lo tiene
--               quien inicia sesión. ADMIN hace todo lo del
--               VENDEDOR, más ver la bitácora, gestionar empleados
--               y cambiar el IVA.
--   es_coach -> una función en el gimnasio, no un permiso. No
--               habilita ningún acceso.
--
-- Separarlos permite los tres casos reales:
--   recepcionista .... rol VENDEDOR, es_coach FALSE
--   coach puro ....... sin rol ni credenciales, es_coach TRUE
--   ambas cosas ...... rol VENDEDOR, es_coach TRUE
--
-- password_hash guarda el hash bcrypt, nunca texto plano.
-- Un empleado jamás se borra: se desactiva. Sus facturas, abonos,
-- inscripciones y su rastro en la bitácora deben seguir diciendo
-- quién fue.

CREATE TABLE empleados (
    id_empleado SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,

    -- Nulos en un coach que no entra al sistema.
    usuario VARCHAR(50) UNIQUE,
    password_hash VARCHAR(255),
    rol VARCHAR(30),

    es_coach BOOLEAN NOT NULL DEFAULT FALSE,

    fecha_nacimiento DATE,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    fecha_registro TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_empleado_rol
        CHECK (rol IS NULL OR rol IN ('ADMIN', 'VENDEDOR')),

    -- O se tiene acceso completo (rol + credenciales) o no se
    -- tiene ninguno. Sin esta regla podría colarse un empleado
    -- con rol pero sin contraseña, que es un agujero de entrada.
    CONSTRAINT chk_empleado_acceso
        CHECK (
            (rol IS NOT NULL AND usuario IS NOT NULL AND password_hash IS NOT NULL)
            OR
            (rol IS NULL AND usuario IS NULL AND password_hash IS NULL)
        ),

    -- Una fila sin rol y sin ser coach no representa a nadie.
    CONSTRAINT chk_empleado_funcion
        CHECK (rol IS NOT NULL OR es_coach)
);


-- ============================================================
-- 2. CLIENTES
-- ============================================================
-- id_representante: auto-referencia. NULL para un cliente
-- normal; apunta al padre o la madre cuando el registro es un
-- menor a cargo (el menor es un cliente más, con su propia
-- membresía e historial).
-- cedula: opcional. UNIQUE sigue aplicando; Postgres permite
-- varios NULL sin conflicto.
-- contacto_emergencia: solo el celular del contacto.
-- referencia: relación del contacto con el cliente (ej. Mamá).
-- vigente_hasta: caché de la vigencia; la fuente de verdad es
-- la tabla membresias.

CREATE TABLE clientes (
    id_cliente SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    cedula VARCHAR(10) UNIQUE,
    fecha_nacimiento DATE,
    correo VARCHAR(150),
    telefono VARCHAR(10),
    genero VARCHAR(30),
    contacto_emergencia VARCHAR(10),
    referencia VARCHAR(50),
    seguro_nombre VARCHAR(100),
    seguro_numero VARCHAR(50),
    id_representante INTEGER,
    vigente_hasta DATE,
    fecha_registro TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_cliente_representante
        FOREIGN KEY (id_representante)
        REFERENCES clientes(id_cliente),

    CONSTRAINT chk_cliente_no_auto_representante
        CHECK (
            id_representante IS NULL
            OR id_representante <> id_cliente
        ),

    CONSTRAINT chk_genero
        CHECK (genero IN ('MASCULINO', 'FEMENINO', 'OTRO'))
);


-- ============================================================
-- 3. POSIBLES CLIENTES
-- ============================================================
-- Quien asiste a una clase demo sin ser todavía cliente.
--
-- El correo es obligatorio: es el dato con el que se detecta la
-- conversión cuando la persona vuelve a inscribirse. Nombre y
-- apellido se escriben de muchas formas; el correo no.
--
-- La fecha de la clase NO está aquí: sale de su inscripción en
-- evento_inscritos, para no guardar el mismo dato dos veces.
--
-- asistio: NULL mientras la clase no haya ocurrido o nadie la
-- haya marcado. TRUE o FALSE una vez registrada.
--
-- id_coach: puede asignarse al agendar o después, por eso es
-- opcional. Es lo que permite medir qué coach trae socios.
--
-- id_cliente: se llena cuando la persona paga su primera
-- membresía. Hasta entonces, NULL.

CREATE TABLE posibles_clientes (
    id_posible SERIAL PRIMARY KEY,

    nombre VARCHAR(100) NOT NULL,
    apellido VARCHAR(100) NOT NULL,
    correo VARCHAR(150) NOT NULL,
    telefono VARCHAR(10),

    id_coach INTEGER,
    id_empleado INTEGER NOT NULL,

    asistio BOOLEAN,

    id_cliente INTEGER UNIQUE,
    fecha_conversion TIMESTAMP,

    fecha_registro TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_posible_coach
        FOREIGN KEY (id_coach)
        REFERENCES empleados(id_empleado),

    CONSTRAINT fk_posible_empleado
        FOREIGN KEY (id_empleado)
        REFERENCES empleados(id_empleado),

    CONSTRAINT fk_posible_cliente
        FOREIGN KEY (id_cliente)
        REFERENCES clientes(id_cliente),

    -- Convertido y fecha de conversión van juntos o no van.
    CONSTRAINT chk_posible_conversion
        CHECK (
            (id_cliente IS NULL AND fecha_conversion IS NULL)
            OR
            (id_cliente IS NOT NULL AND fecha_conversion IS NOT NULL)
        )
);


-- ============================================================
-- 4. PRODUCTOS
-- ============================================================
-- Solo artículos físicos que se venden. Las membresías viven en
-- planes_membresia.
-- Un producto que deja de venderse no se borra, porque
-- detalle_factura lo referencia y las facturas antiguas deben
-- seguir mostrando qué se vendió: se desactiva.

CREATE TABLE productos (
    id_producto SERIAL PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL,
    precio NUMERIC(10,2) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT chk_producto_precio
        CHECK (precio >= 0)
);


-- ============================================================
-- 5. PLANES DE MEMBRESÍA
-- ============================================================
-- tipo: SOLO la categoría comercial, JUNIOR o SENIOR. Senior es
-- todo lo que no es Junior, pases incluidos.
--
-- Que un plan sea un pase NO se deduce del tipo, sino de que
-- tenga dias_incluidos. Antes el tipo hacía las dos cosas a la
-- vez —categoría y mecanismo de cobro— y por eso no se podía
-- clasificar un pase como Senior sin romper el cálculo.
--
-- duracion + unidad_duracion: plazo máximo de validez.
-- dias_incluidos: cuántas entradas trae el pase; se copia a
-- membresias.dias_totales al vender.
--   Ej.: Pase 10 días = dias_incluidos 10, duracion 30 DIA.
--        Membresía Senior = dias_incluidos NULL, duracion 1 MES.
--
-- La Promo pareja es un plan SENIOR con permite_pareja = TRUE.

CREATE TABLE planes_membresia (
    id_plan SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL UNIQUE,
    tipo VARCHAR(20) NOT NULL,
    precio NUMERIC(10,2) NOT NULL,
    duracion INTEGER NOT NULL,
    unidad_duracion VARCHAR(10) NOT NULL,
    dias_incluidos INTEGER,
    permite_pareja BOOLEAN NOT NULL DEFAULT FALSE,
    permite_descuento BOOLEAN NOT NULL DEFAULT FALSE,
    activo BOOLEAN NOT NULL DEFAULT TRUE,

    CONSTRAINT chk_plan_tipo
        CHECK (tipo IN ('JUNIOR', 'SENIOR')),

    CONSTRAINT chk_plan_precio
        CHECK (precio >= 0),

    CONSTRAINT chk_plan_duracion
        CHECK (duracion > 0),

    CONSTRAINT chk_plan_unidad
        CHECK (unidad_duracion IN ('DIA', 'MES')),

    -- Un plan con entradas incluidas se mide en días. Un plan
    -- mensual no tiene entradas que contar.
    CONSTRAINT chk_plan_dias_incluidos
        CHECK (
            dias_incluidos IS NULL
            OR (dias_incluidos > 0 AND unidad_duracion = 'DIA')
        )
);


-- ============================================================
-- 6. CONFIGURACIÓN
-- ============================================================
-- Parámetros editables por el ADMIN. Cada cambio va a bitacora.

CREATE TABLE configuracion (
    clave VARCHAR(50) PRIMARY KEY,
    valor VARCHAR(100) NOT NULL,
    descripcion VARCHAR(200),
    fecha_actualizacion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- 7. FACTURAS
-- ============================================================
-- subtotal: monto ANTES del descuento. El descuento en dinero se
-- calcula subtotal * descuento_porcentaje / 100.
-- iva_porcentaje: tasa con la que se emitió esta factura, para
-- que un cambio de IVA no altere las anteriores.
-- estado PENDIENTE = factura fiada.
-- metodo_pago es opcional: una fiada se paga con abonos, que
-- pueden usar métodos distintos (ver pagos_fiado).
-- saldo_pendiente arranca en el total si es fiada y baja con
-- cada abono; al llegar a 0 el estado pasa a EMITIDA.
-- Anulación: motivo obligatorio. Las facturas nunca se borran.

CREATE TABLE facturas (
    id_factura SERIAL PRIMARY KEY,
    numero_factura VARCHAR(30) NOT NULL UNIQUE,

    id_cliente INTEGER NOT NULL,
    id_empleado INTEGER NOT NULL,

    fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    metodo_pago VARCHAR(30),

    descuento_porcentaje NUMERIC(5,2) NOT NULL DEFAULT 0,
    iva_porcentaje NUMERIC(5,2) NOT NULL DEFAULT 15,

    subtotal NUMERIC(10,2) NOT NULL,
    iva NUMERIC(10,2) NOT NULL,
    total NUMERIC(10,2) NOT NULL,

    estado VARCHAR(30) NOT NULL DEFAULT 'EMITIDA',
    motivo_anulacion VARCHAR(255),

    saldo_pendiente NUMERIC(10,2) NOT NULL DEFAULT 0,

    CONSTRAINT fk_factura_cliente
        FOREIGN KEY (id_cliente)
        REFERENCES clientes(id_cliente),

    CONSTRAINT fk_factura_empleado
        FOREIGN KEY (id_empleado)
        REFERENCES empleados(id_empleado),

    CONSTRAINT chk_factura_metodo_pago
        CHECK (metodo_pago IN ('EFECTIVO', 'TRANSFERENCIA')),

    CONSTRAINT chk_factura_descuento
        CHECK (descuento_porcentaje >= 0 AND descuento_porcentaje <= 100),

    CONSTRAINT chk_factura_iva_porcentaje
        CHECK (iva_porcentaje >= 0 AND iva_porcentaje <= 100),

    CONSTRAINT chk_factura_subtotal CHECK (subtotal >= 0),
    CONSTRAINT chk_factura_iva      CHECK (iva >= 0),
    CONSTRAINT chk_factura_total    CHECK (total >= 0),

    CONSTRAINT chk_factura_estado
        CHECK (estado IN ('EMITIDA', 'ANULADA', 'PENDIENTE')),

    CONSTRAINT chk_factura_anulacion
        CHECK (
            (estado = 'ANULADA' AND motivo_anulacion IS NOT NULL)
            OR
            (estado <> 'ANULADA')
        ),

    CONSTRAINT chk_factura_saldo_pendiente
        CHECK (saldo_pendiente >= 0 AND saldo_pendiente <= total),

    -- PENDIENTE exige saldo > 0; EMITIDA exige saldo = 0.
    CONSTRAINT chk_factura_estado_saldo
        CHECK (
            (estado = 'PENDIENTE' AND saldo_pendiente > 0)
            OR
            (estado = 'EMITIDA' AND saldo_pendiente = 0)
            OR
            (estado = 'ANULADA')
        )
);


-- ============================================================
-- 8. DETALLE DE FACTURA
-- ============================================================
-- Cada línea es un producto O un plan de membresía, exactamente
-- uno de los dos. Vender un plan además genera su membresía.

CREATE TABLE detalle_factura (
    id_detalle SERIAL PRIMARY KEY,

    id_factura INTEGER NOT NULL,
    id_producto INTEGER,
    id_plan INTEGER,

    cantidad INTEGER NOT NULL,
    precio_unitario NUMERIC(10,2) NOT NULL,
    subtotal NUMERIC(10,2) NOT NULL,

    CONSTRAINT fk_detalle_factura
        FOREIGN KEY (id_factura)
        REFERENCES facturas(id_factura)
        ON DELETE CASCADE,

    CONSTRAINT fk_detalle_producto
        FOREIGN KEY (id_producto)
        REFERENCES productos(id_producto),

    CONSTRAINT fk_detalle_plan
        FOREIGN KEY (id_plan)
        REFERENCES planes_membresia(id_plan),

    CONSTRAINT chk_detalle_item
        CHECK (
            (id_producto IS NOT NULL AND id_plan IS NULL)
            OR
            (id_producto IS NULL AND id_plan IS NOT NULL)
        ),

    CONSTRAINT chk_detalle_cantidad CHECK (cantidad > 0),
    CONSTRAINT chk_detalle_precio   CHECK (precio_unitario >= 0),
    CONSTRAINT chk_detalle_subtotal CHECK (subtotal >= 0)
);


-- ============================================================
-- 9. MEMBRESÍAS
-- ============================================================
-- Fuente de verdad de la vigencia.
-- id_cliente: quien usa la membresía (puede ser un menor); la
-- factura puede estar a nombre del representante.
-- dias_totales / dias_restantes: solo en planes con entradas
-- incluidas; NULL en los mensuales.
-- id_membresia_pareja: enlaza dos membresías de la promo pareja,
-- generadas desde la misma factura. Se insertan las dos y luego
-- se enlazan con UPDATE.

CREATE TABLE membresias (
    id_membresia SERIAL PRIMARY KEY,

    id_cliente INTEGER NOT NULL,
    id_plan INTEGER NOT NULL,
    id_factura INTEGER NOT NULL,

    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,

    dias_totales INTEGER,
    dias_restantes INTEGER,

    estado VARCHAR(30) NOT NULL DEFAULT 'ACTIVA',

    id_membresia_pareja INTEGER UNIQUE,

    CONSTRAINT fk_membresia_cliente
        FOREIGN KEY (id_cliente)
        REFERENCES clientes(id_cliente),

    CONSTRAINT fk_membresia_plan
        FOREIGN KEY (id_plan)
        REFERENCES planes_membresia(id_plan),

    CONSTRAINT fk_membresia_factura
        FOREIGN KEY (id_factura)
        REFERENCES facturas(id_factura),

    CONSTRAINT fk_membresia_pareja
        FOREIGN KEY (id_membresia_pareja)
        REFERENCES membresias(id_membresia),

    CONSTRAINT chk_membresia_fechas
        CHECK (fecha_fin >= fecha_inicio),

    CONSTRAINT chk_membresia_dias
        CHECK (dias_totales IS NULL OR dias_totales > 0),

    CONSTRAINT chk_membresia_dias_restantes
        CHECK (
            dias_restantes IS NULL
            OR (dias_restantes >= 0 AND dias_restantes <= dias_totales)
        ),

    CONSTRAINT chk_membresia_estado
        CHECK (estado IN ('ACTIVA', 'VENCIDA', 'CANCELADA')),

    CONSTRAINT chk_membresia_no_auto_pareja
        CHECK (
            id_membresia_pareja IS NULL
            OR id_membresia_pareja <> id_membresia
        )
);


-- ============================================================
-- 10. CATEGORÍAS DE EVENTOS
-- ============================================================
-- Los cumpleaños NO son una categoría: se calculan al vuelo
-- desde la fecha de nacimiento de clientes y empleados.

CREATE TABLE categorias_evento (
    id_categoria SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL UNIQUE,
    color VARCHAR(30) NOT NULL
);


-- ============================================================
-- 11. EVENTOS
-- ============================================================
-- Convención de "todo el día": hora_inicio 00:00, hora_fin 23:59,
-- y "(todo el día)" en el título.

CREATE TABLE eventos (
    id_evento SERIAL PRIMARY KEY,

    titulo VARCHAR(150) NOT NULL,
    id_categoria INTEGER NOT NULL,

    fecha DATE NOT NULL,
    hora_inicio TIME NOT NULL,
    hora_fin TIME NOT NULL,

    descripcion TEXT,
    cupo_maximo INTEGER,

    CONSTRAINT fk_evento_categoria
        FOREIGN KEY (id_categoria)
        REFERENCES categorias_evento(id_categoria),

    CONSTRAINT chk_evento_horas
        CHECK (hora_fin > hora_inicio),

    CONSTRAINT chk_evento_cupo
        CHECK (cupo_maximo IS NULL OR cupo_maximo > 0)
);


-- ============================================================
-- 12. INSCRITOS A EVENTOS
-- ============================================================
-- Un inscrito es un cliente O un posible cliente, exactamente
-- uno de los dos. Mismo patrón que detalle_factura.
-- Una clase demo tendrá sobre todo posibles clientes.
-- id_empleado: quién lo agendó (vista "Agenda por cliente").
-- El cupo se valida en la capa de servicios, dentro de la
-- transacción y bloqueando la fila del evento.

CREATE TABLE evento_inscritos (
    id_evento_inscrito SERIAL PRIMARY KEY,

    id_evento INTEGER NOT NULL,
    id_cliente INTEGER,
    id_posible INTEGER,
    id_empleado INTEGER NOT NULL,

    fecha_inscripcion TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_inscrito_evento
        FOREIGN KEY (id_evento)
        REFERENCES eventos(id_evento)
        ON DELETE CASCADE,

    CONSTRAINT fk_inscrito_cliente
        FOREIGN KEY (id_cliente)
        REFERENCES clientes(id_cliente),

    CONSTRAINT fk_inscrito_posible
        FOREIGN KEY (id_posible)
        REFERENCES posibles_clientes(id_posible),

    CONSTRAINT fk_inscrito_empleado
        FOREIGN KEY (id_empleado)
        REFERENCES empleados(id_empleado),

    CONSTRAINT chk_inscrito_quien
        CHECK (
            (id_cliente IS NOT NULL AND id_posible IS NULL)
            OR
            (id_cliente IS NULL AND id_posible IS NOT NULL)
        )
);

-- Nota: un UNIQUE (id_evento, id_cliente) dejaría de proteger en
-- cuanto id_cliente admite nulos, porque Postgres considera
-- distintos dos NULL. Por eso van como índices únicos parciales.

CREATE UNIQUE INDEX uq_inscrito_evento_cliente
    ON evento_inscritos(id_evento, id_cliente)
    WHERE id_cliente IS NOT NULL;

CREATE UNIQUE INDEX uq_inscrito_evento_posible
    ON evento_inscritos(id_evento, id_posible)
    WHERE id_posible IS NOT NULL;


-- ============================================================
-- 13. PAGOS DE FACTURAS FIADAS
-- ============================================================
-- Historial de abonos de una factura PENDIENTE. El primer abono,
-- el monto recibido al fiar, también se guarda aquí.

CREATE TABLE pagos_fiado (
    id_pago SERIAL PRIMARY KEY,

    id_factura INTEGER NOT NULL,
    id_empleado INTEGER NOT NULL,

    monto NUMERIC(10,2) NOT NULL,
    metodo_pago VARCHAR(30) NOT NULL,
    fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_pago_fiado_factura
        FOREIGN KEY (id_factura)
        REFERENCES facturas(id_factura),

    CONSTRAINT fk_pago_fiado_empleado
        FOREIGN KEY (id_empleado)
        REFERENCES empleados(id_empleado),

    CONSTRAINT chk_pago_fiado_monto CHECK (monto > 0),

    CONSTRAINT chk_pago_fiado_metodo
        CHECK (metodo_pago IN ('EFECTIVO', 'TRANSFERENCIA'))
);


-- ============================================================
-- 14. GASTOS
-- ============================================================
-- Salidas de dinero, para el balance. Solo el ADMIN las registra.
--
-- segmento: a qué parte del negocio se imputa el gasto. Las
-- ventas de productos se consideran GENERAL, porque no son ni
-- Junior ni Senior.
--
-- descripcion: opcional y en texto libre. Por decisión del
-- 23/10/2026 no hay categorías fijas de motivo; si más adelante
-- se quiere un reporte por naturaleza del gasto, se agrega una
-- columna y las filas viejas quedan sin categoría, sin perder
-- nada de lo ya cargado.
--
-- metodo_pago: opcional, útil si alguna vez se cuadra la caja.
--
-- Un gasto no se borra: se anula con motivo, igual que una
-- factura, y queda en la bitácora.

CREATE TABLE gastos (
    id_gasto SERIAL PRIMARY KEY,

    fecha DATE NOT NULL,
    monto NUMERIC(10,2) NOT NULL,
    segmento VARCHAR(10) NOT NULL,
    descripcion VARCHAR(255),
    metodo_pago VARCHAR(30),

    id_empleado INTEGER NOT NULL,

    estado VARCHAR(20) NOT NULL DEFAULT 'REGISTRADO',
    motivo_anulacion VARCHAR(255),

    fecha_registro TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_gasto_empleado
        FOREIGN KEY (id_empleado)
        REFERENCES empleados(id_empleado),

    CONSTRAINT chk_gasto_monto CHECK (monto > 0),

    CONSTRAINT chk_gasto_segmento
        CHECK (segmento IN ('JUNIOR', 'SENIOR', 'GENERAL')),

    CONSTRAINT chk_gasto_metodo
        CHECK (metodo_pago IS NULL
               OR metodo_pago IN ('EFECTIVO', 'TRANSFERENCIA')),

    CONSTRAINT chk_gasto_estado
        CHECK (estado IN ('REGISTRADO', 'ANULADO')),

    CONSTRAINT chk_gasto_anulacion
        CHECK (
            (estado = 'ANULADO' AND motivo_anulacion IS NOT NULL)
            OR
            (estado <> 'ANULADO')
        )
);


-- ============================================================
-- 15. BITÁCORA
-- ============================================================
-- Registro de solo lectura para el ADMIN: qué empleado hizo qué
-- y cuándo. Lo escribe la capa de servicios en cada acción.
-- entidad + id_entidad apuntan al registro afectado; id_entidad
-- es NULL para CONFIGURACION.
-- detalle (JSONB): datos útiles de la acción. En CLIENTE_EDITADO,
-- los campos antes y después; en IVA_CAMBIADO, los dos valores;
-- en FACTURA_ANULADA, el motivo.

CREATE TABLE bitacora (
    id_bitacora SERIAL PRIMARY KEY,

    id_empleado INTEGER NOT NULL,
    accion VARCHAR(30) NOT NULL,
    entidad VARCHAR(20) NOT NULL,
    id_entidad INTEGER,
    detalle JSONB,
    fecha TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_bitacora_empleado
        FOREIGN KEY (id_empleado)
        REFERENCES empleados(id_empleado),

    CONSTRAINT chk_bitacora_accion
        CHECK (accion IN (
            -- Clientes
            'CLIENTE_CREADO',
            'CLIENTE_EDITADO',
            -- Facturación
            'FACTURA_EMITIDA',
            'FACTURA_ANULADA',
            'ABONO_REGISTRADO',
            -- Calendario
            'INSCRIPCION_REGISTRADA',
            'INSCRIPCION_CANCELADA',
            'ASISTENCIA_MARCADA',
            -- Configuración
            'IVA_CAMBIADO',
            -- Catálogo
            'ITEM_CREADO',
            'ITEM_EDITADO',
            'ITEM_DESACTIVADO',
            'ITEM_REACTIVADO',
            -- Empleados
            'EMPLEADO_CREADO',
            'EMPLEADO_EDITADO',
            'EMPLEADO_DESACTIVADO',
            'EMPLEADO_REACTIVADO',
            'PASSWORD_CAMBIADA',
            -- Correo
            'CORREO_ENVIADO',
            'CORREO_FALLIDO',
            -- Posibles clientes
            'POSIBLE_CREADO',
            'POSIBLE_EDITADO',
            'COACH_ASIGNADO',
            'POSIBLE_CONVERTIDO',
            -- Gastos
            'GASTO_REGISTRADO',
            'GASTO_EDITADO',
            'GASTO_ANULADO'
        )),

    CONSTRAINT chk_bitacora_entidad
        CHECK (entidad IN (
            'CLIENTE',
            'FACTURA',
            'PAGO_FIADO',
            'INSCRIPCION',
            'CONFIGURACION',
            'PRODUCTO',
            'PLAN',
            'EMPLEADO',
            'POSIBLE_CLIENTE',
            'GASTO'
        ))
);


-- ============================================================
-- SECUENCIA DE NUMERACIÓN DE FACTURAS
-- ============================================================
-- El número visible se arma como 'F-000001'. Con una secuencia,
-- dos cobros simultáneos nunca reciben el mismo número.

CREATE SEQUENCE IF NOT EXISTS seq_numero_factura START 1;


-- ============================================================
-- ÍNDICES
-- ============================================================

CREATE INDEX idx_clientes_representante ON clientes(id_representante);
CREATE INDEX idx_clientes_correo        ON clientes(correo);

CREATE INDEX idx_empleados_coach        ON empleados(es_coach) WHERE es_coach;

-- El correo es la llave de la conversión: se busca por él.
CREATE INDEX idx_posibles_correo        ON posibles_clientes(correo);
CREATE INDEX idx_posibles_coach         ON posibles_clientes(id_coach);
CREATE INDEX idx_posibles_cliente       ON posibles_clientes(id_cliente);

CREATE INDEX idx_facturas_cliente       ON facturas(id_cliente);
CREATE INDEX idx_facturas_empleado      ON facturas(id_empleado);
CREATE INDEX idx_facturas_fecha         ON facturas(fecha);
CREATE INDEX idx_facturas_estado        ON facturas(estado);

CREATE INDEX idx_detalle_factura        ON detalle_factura(id_factura);
CREATE INDEX idx_detalle_producto       ON detalle_factura(id_producto);
CREATE INDEX idx_detalle_plan           ON detalle_factura(id_plan);

CREATE INDEX idx_membresias_cliente     ON membresias(id_cliente);
CREATE INDEX idx_membresias_plan        ON membresias(id_plan);
CREATE INDEX idx_membresias_factura     ON membresias(id_factura);
CREATE INDEX idx_membresias_estado      ON membresias(estado);

CREATE INDEX idx_eventos_fecha          ON eventos(fecha);
CREATE INDEX idx_eventos_categoria      ON eventos(id_categoria);

CREATE INDEX idx_evento_inscritos_evento   ON evento_inscritos(id_evento);
CREATE INDEX idx_evento_inscritos_cliente  ON evento_inscritos(id_cliente);
CREATE INDEX idx_evento_inscritos_posible  ON evento_inscritos(id_posible);
CREATE INDEX idx_evento_inscritos_empleado ON evento_inscritos(id_empleado);

CREATE INDEX idx_pagos_fiado_factura    ON pagos_fiado(id_factura);
CREATE INDEX idx_pagos_fiado_empleado   ON pagos_fiado(id_empleado);

CREATE INDEX idx_gastos_fecha           ON gastos(fecha);
CREATE INDEX idx_gastos_segmento        ON gastos(segmento);
CREATE INDEX idx_gastos_estado          ON gastos(estado);

CREATE INDEX idx_bitacora_fecha         ON bitacora(fecha);
CREATE INDEX idx_bitacora_empleado      ON bitacora(id_empleado);
CREATE INDEX idx_bitacora_entidad       ON bitacora(entidad, id_entidad);


-- ============================================================
-- DATOS INICIALES
-- ============================================================

-- IVA vigente.
-- PENDIENTE DE DEFINIR: los precios del catálogo ya incluyen IVA.
-- Mientras no se confirme si el gimnasio lo declara, el valor
-- queda en 15 y el cálculo se corrige en la capa de servicios.
INSERT INTO configuracion (clave, valor, descripcion) VALUES
    ('iva_porcentaje', '15', 'Porcentaje de IVA aplicado a las facturas nuevas');

-- Planes de membresía.
-- Todos los pases son SENIOR; lo que los hace pases es tener
-- días incluidos.
INSERT INTO planes_membresia
    (nombre, tipo, precio, duracion, unidad_duracion, dias_incluidos, permite_pareja, permite_descuento)
VALUES
    ('Membresía Junior',          'JUNIOR',  30.00,  1, 'MES', NULL, FALSE, TRUE),
    ('Membresía Senior',          'SENIOR',  35.00,  1, 'MES', NULL, FALSE, TRUE),
    ('Senior anual',              'SENIOR', 350.00, 12, 'MES', NULL, FALSE, TRUE),
    ('Pase 1 día',                'SENIOR',  10.00,  1, 'DIA', 1,    FALSE, TRUE),
    ('Pase 5 días',               'SENIOR',  28.00, 30, 'DIA', 5,    FALSE, TRUE),
    ('Pase 10 días',              'SENIOR',  49.00, 30, 'DIA', 10,   FALSE, TRUE),
    ('Promo pareja (2 personas)', 'SENIOR', 111.00,  1, 'MES', NULL, TRUE,  FALSE);

-- Categorías del calendario.
INSERT INTO categorias_evento (nombre, color) VALUES
    ('Clase de prueba',  '#6A6A67'),
    ('Clase grupal',     '#2B3210'),
    ('Evento especial',  '#C2DD58');

-- Usuario administrador inicial.
-- El hash es un marcador: NO permite iniciar sesión. Hay que
-- reemplazarlo por uno real con:  python -m scripts.crear_admin
INSERT INTO empleados (nombre, apellido, usuario, password_hash, rol) VALUES
    ('Administrador', 'Totem', 'admin', 'PENDIENTE_ESTABLECER_HASH_BCRYPT', 'ADMIN');


-- ============================================================
-- PERMISOS
-- ============================================================
-- Si la aplicación se conecta con un usuario distinto de
-- postgres, ese usuario necesita permiso sobre la secuencia.
-- Sin esto, al cobrar aparece "permission denied for sequence".
-- Descomenta y reemplaza 'mi_usuario':
--
-- GRANT USAGE, SELECT ON SEQUENCE seq_numero_factura TO mi_usuario;
