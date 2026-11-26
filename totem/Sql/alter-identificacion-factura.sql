-- ============================================================
-- Con qué identificación salió cada factura al SRI
--
-- La lista de facturas mostraba la cédula que el cliente tiene HOY,
-- que no es necesariamente la que se envió. La diferencia aparece
-- justo en el caso que importa: el SRI rechaza una cédula mal
-- escrita, se le corrige la cédula al cliente y se reemite. Desde
-- ese momento la lista muestra la cédula nueva para una factura que
-- salió a consumidor final, y no hay forma de notarlo.
--
-- La verdad está en el XML firmado, que ya se guarda entero en
-- facturas.sri_xml. Así que en vez de agregar columnas que alguien
-- tenga que acordarse de llenar al emitir, se declaran GENERADAS a
-- partir de ese XML.
--
-- Eso tiene tres consecuencias buenas:
--
--   * no hay código que las escriba, así que no pueden quedar
--     desincronizadas del comprobante que se envió
--   * las facturas que ya existen se llenan solas al correr esto, sin
--     script de relleno
--   * si un día se reemite, el XML cambia y las columnas cambian con
--     él, sin que nadie haga nada
--
-- Quedan en NULL para las facturas que nunca se enviaron al SRI, que
-- es lo correcto: de ésas no se envió ninguna identificación.
--
-- Por qué cada columna busca dos veces: sri_xml guarda cosas
-- distintas según el momento. Mientras la factura está FIRMADA
-- guarda el XML del comprobante, con sus etiquetas en claro. Cuando
-- el SRI la autoriza, guarda la respuesta del SRI, que trae el
-- comprobante ESCAPADO adentro (&lt;factura&gt; en vez de
-- <factura>). Buscando solo la forma en claro, estas columnas
-- quedarían vacías justo en las facturas autorizadas, que son las
-- que interesan.
--
-- Cómo aplicarlo, desde la carpeta Sql:
--
--   psql -U postgres -d totem -f alter-identificacion-factura.sql
-- ============================================================

BEGIN;

ALTER TABLE facturas
    ADD COLUMN IF NOT EXISTS sri_tipo_identificacion VARCHAR(2)
        GENERATED ALWAYS AS (
            COALESCE(
                substring(sri_xml from
                    '<tipoIdentificacionComprador>([^<]*)</tipoIdentificacionComprador>'),
                substring(sri_xml from
                    '&lt;tipoIdentificacionComprador&gt;([^&]*)&lt;/tipoIdentificacionComprador&gt;')
            )
        ) STORED,
    ADD COLUMN IF NOT EXISTS sri_identificacion VARCHAR(20)
        GENERATED ALWAYS AS (
            COALESCE(
                substring(sri_xml from
                    '<identificacionComprador>([^<]*)</identificacionComprador>'),
                substring(sri_xml from
                    '&lt;identificacionComprador&gt;([^&]*)&lt;/identificacionComprador&gt;')
            )
        ) STORED;

-- Para filtrar por tipo sin recorrer la tabla entera.
CREATE INDEX IF NOT EXISTS idx_facturas_tipo_identificacion
    ON facturas (sri_tipo_identificacion);

COMMIT;

-- Los códigos son los del SRI:
--   04 RUC
--   05 cédula
--   06 pasaporte
--   07 consumidor final
