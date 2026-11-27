-- ============================================================
-- Las que el SRI ya autorizó no se vuelven a facturar en Contífico
--
-- En noviembre este sistema emitió al SRI. Esas ventas ya tienen su
-- comprobante autorizado, con su número de autorización. Si salen en
-- el primer Excel de Contífico, se facturan por segunda vez: dos
-- comprobantes autorizados de la misma venta, y eso no se arregla
-- borrando una fila.
--
-- Por eso se marcan como ya cargadas: no es que estén en Contífico,
-- es que ya tienen factura y no necesitan otra.
--
-- Las que el SRI RECHAZÓ no se tocan a propósito. Esas se quedaron
-- sin factura, así que deben una: tienen que salir en el Excel para
-- que se emitan en Contífico, con la cédula ya corregida.
--
-- Cómo aplicarlo, desde la carpeta Sql:
--
--   psql -U postgres -d totem -f alter-contifico-sri-ya-emitidas.sql
--
-- Se puede correr dos veces sin problema: solo toca las que todavía
-- no están marcadas.
-- ============================================================

BEGIN;

-- Qué se va a marcar, antes de marcarlo.
SELECT numero_factura, fecha::date AS fecha, sri_estado, sri_autorizacion
  FROM facturas
 WHERE sri_estado = 'AUTORIZADA'
   AND sri_autorizacion IS NOT NULL
   AND (contifico_planes_en IS NULL OR contifico_productos_en IS NULL)
 ORDER BY fecha;

-- El comprobante del SRI cubre la venta entera, planes y productos,
-- así que se marcan las dos partes.
--
-- La condición exige número de autorización y no solo el estado: una
-- factura marcada AUTORIZADA sin número es un error de nuestro lado,
-- y con esa duda conviene que salga en el Excel y se revise, antes
-- que ocultarla y que se quede sin factura.
UPDATE facturas
   SET contifico_planes_en = COALESCE(contifico_planes_en,
                                      sri_fecha_autorizacion, fecha),
       contifico_productos_en = COALESCE(contifico_productos_en,
                                         sri_fecha_autorizacion, fecha)
 WHERE sri_estado = 'AUTORIZADA'
   AND sri_autorizacion IS NOT NULL
   AND (contifico_planes_en IS NULL OR contifico_productos_en IS NULL);

-- Las rechazadas siguen pendientes: se revisa que así sea.
--
-- Los dos estados son los que usa el SRI: DEVUELTA la rechaza al
-- recibirla y NO_AUTORIZADA al autorizarla. No existe un estado
-- 'RECHAZADA', y preguntar por él daría cero siempre y parecería que
-- todo está bien.
SELECT sri_estado,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE contifico_planes_en IS NULL
                          AND contifico_productos_en IS NULL)
           AS siguen_pendientes
  FROM facturas
 WHERE sri_estado IN ('DEVUELTA', 'NO_AUTORIZADA')
 GROUP BY sri_estado;

COMMIT;
