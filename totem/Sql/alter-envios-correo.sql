-- ============================================================
-- Registro de correos enviados, para poder leer los rebotes
--
-- Hasta ahora el sistema mandaba el correo y lo anotaba en la
-- bitácora. Eso sirve para saber qué se hizo, pero no para saber qué
-- pasó después: cuando el correo rebota, el aviso llega minutos más
-- tarde al buzón del gimnasio y no hay forma de saber a qué factura
-- correspondía.
--
-- Esta tabla guarda el Message-ID de cada mensaje que sale. Es lo que
-- el servidor del destinatario devuelve dentro del rebote, así que es
-- lo que permite decir "este rebote es de la factura F-000123" en
-- lugar de adivinar por la dirección.
--
-- No reemplaza a la bitácora: la bitácora es el registro de lo que
-- hizo una persona, esta tabla es el estado de un mensaje.
--
-- Cómo aplicarlo, desde la carpeta Sql:
--
--   psql -U postgres -d totem -f alter-envios-correo.sql
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS envios_correo (
    id_envio        SERIAL PRIMARY KEY,

    -- De qué era el correo. Las dos pueden ser NULL: un aviso de
    -- clase no tiene factura, y un correo a alguien que no está
    -- registrado no tiene cliente.
    id_factura      INTEGER REFERENCES facturas(id_factura),
    id_cliente      INTEGER REFERENCES clientes(id_cliente),

    destinatario    VARCHAR(120) NOT NULL,
    asunto          VARCHAR(200),

    -- La llave para casar el rebote. Único porque es único por
    -- mensaje; si se repitiera, el rebote sería ambiguo.
    message_id      VARCHAR(255) UNIQUE,

    enviado_en      TIMESTAMP NOT NULL DEFAULT NOW(),

    --   ENVIADO   salió del servidor del gimnasio, sin novedad
    --   REBOTADO  el servidor del destinatario lo devolvió
    --   FALLIDO   no se pudo ni entregar al servidor de salida
    estado          VARCHAR(12) NOT NULL DEFAULT 'ENVIADO',

    -- Lo que dijo el servidor que rechazó. Se guarda recortado: el
    -- rebote completo es larguísimo y lo único útil es el motivo.
    motivo          VARCHAR(400),
    rebotado_en     TIMESTAMP,

    CONSTRAINT chk_envio_estado
        CHECK (estado IN ('ENVIADO', 'REBOTADO', 'FALLIDO'))
);

-- Para buscar los envíos de una factura y los de una dirección.
CREATE INDEX IF NOT EXISTS idx_envios_factura
    ON envios_correo (id_factura);
CREATE INDEX IF NOT EXISTS idx_envios_destinatario
    ON envios_correo (LOWER(destinatario));
CREATE INDEX IF NOT EXISTS idx_envios_fecha
    ON envios_correo (enviado_en DESC);

-- Hasta dónde se leyó el buzón de rebotes la última vez. Sin esto se
-- releería el buzón entero en cada pasada.
CREATE TABLE IF NOT EXISTS rebotes_revision (
    id              BOOLEAN PRIMARY KEY DEFAULT TRUE,
    revisado_hasta  TIMESTAMP,
    ultima_pasada   TIMESTAMP,
    CONSTRAINT chk_rebotes_una_fila CHECK (id)
);

INSERT INTO rebotes_revision (id, revisado_hasta)
VALUES (TRUE, NOW() - INTERVAL '7 days')
ON CONFLICT (id) DO NOTHING;

-- En la ficha del cliente: su correo rebotó y hay que preguntárselo
-- de nuevo. Se limpia solo cuando alguien le cambia el correo.
ALTER TABLE clientes
    ADD COLUMN IF NOT EXISTS correo_rebotado_en TIMESTAMP,
    ADD COLUMN IF NOT EXISTS correo_rebote_motivo VARCHAR(400);

-- Acciones nuevas de la bitácora.
ALTER TABLE bitacora DROP CONSTRAINT IF EXISTS chk_bitacora_accion;

ALTER TABLE bitacora ADD CONSTRAINT chk_bitacora_accion CHECK (
    accion IN (
        'CLIENTE_CREADO', 'CLIENTE_EDITADO',
        'FACTURA_EMITIDA', 'FACTURA_ANULADA', 'ABONO_REGISTRADO',
        'INSCRIPCION_REGISTRADA', 'INSCRIPCION_CANCELADA',
        'ASISTENCIA_MARCADA',
        'IVA_CAMBIADO', 'DATOS_GYM_CAMBIADOS',
        'ITEM_CREADO', 'ITEM_EDITADO', 'ITEM_DESACTIVADO',
        'ITEM_REACTIVADO',
        'EMPLEADO_CREADO', 'EMPLEADO_EDITADO', 'EMPLEADO_DESACTIVADO',
        'EMPLEADO_REACTIVADO', 'PASSWORD_CAMBIADA',
        'CORREO_ENVIADO', 'CORREO_FALLIDO',
        'POSIBLE_CREADO', 'POSIBLE_EDITADO', 'COACH_ASIGNADO',
        'POSIBLE_CONVERTIDO',
        'GASTO_REGISTRADO', 'GASTO_EDITADO', 'GASTO_ANULADO',
        -- Facturación electrónica
        'COMPROBANTE_REEMITIDO',
        'BLOQUE_FACTURADO',
        -- Rebotes de correo
        'CORREO_REBOTADO'
    )
);

COMMIT;
