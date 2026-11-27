"""Consultas agregadas para el reporte de Contabilidad.

A diferencia de Facturas, que lista transacción por transacción, aquí
todo viene sumado: lo que interesa es el total del período, no cada
venta.

Regla que atraviesa todas las consultas: cuenta la plata el día que
entra a la caja, no el día que se emitió la factura.

Antes contaba al emitir, y eso dejaba un agujero: una fiada que se
abonaba de a poco no aparecía por ningún lado hasta que se saldaba
entera. Veinte dólares en la caja y cero en el reporte. Y al saldarse,
los sesenta y cinco entraban de golpe en el mes de la factura, así que
un mes ya cerrado cambiaba solo.

Las ANULADA no cuentan, ni siquiera lo que se hubiera abonado antes de
anularlas.
"""

from app.db import obtener_cursor

_FILTRO_CLIENTE = "AND f.id_cliente = %s"

# Cada peso que entró a la caja, con su fecha, su método y la parte de
# IVA que le toca. Todo el reporte se arma sobre esto, para que las
# cifras no puedan discrepar entre sí: si una venta aparece en el
# total y no en el desglose por método, es porque se sumaron de dos
# formas distintas.
#
# Son dos clases de movimiento y no una:
#
#   - La venta cobrada en el momento: no tiene abonos y no quedó
#     saldo. Entra entera el día de la venta.
#   - La fiada: su plata vive toda en pagos_fiado, incluido lo que se
#     recibió al momento de fiar. Cada abono entra el día que se
#     recibió, con la parte de IVA que le corresponde.
#
# Una no puede ser la otra: la venta cobrada se reconoce justamente
# por no tener abonos, así que ninguna se cuenta dos veces.
MOVIMIENTOS = """
    SELECT f.fecha::date   AS fecha,
           f.total         AS monto,
           f.iva           AS iva,
           f.metodo_pago   AS metodo_pago,
           f.id_factura    AS id_factura,
           f.id_cliente    AS id_cliente
      FROM facturas f
     WHERE f.estado <> 'ANULADA'
       AND f.saldo_pendiente = 0
       AND NOT EXISTS (SELECT 1 FROM pagos_fiado g
                        WHERE g.id_factura = f.id_factura)
    UNION ALL
    SELECT g.fecha::date,
           g.monto,
           -- El IVA del abono, a prorrata de lo que representa sobre
           -- el total. Redondeado al centavo: la suma de los abonos
           -- puede quedar a un centavo del IVA de la factura, y eso
           -- es preferible a inventar una cifra exacta que no cuadre
           -- con ninguno de los abonos.
           ROUND(g.monto * f.iva / NULLIF(f.total, 0), 2),
           g.metodo_pago,
           f.id_factura,
           f.id_cliente
      FROM pagos_fiado g
      JOIN facturas f ON f.id_factura = g.id_factura
     WHERE f.estado <> 'ANULADA'
"""


class ContabilidadRepositorio:

    def _parametros(self, desde, hasta, id_cliente):
        parametros = [desde, hasta]
        filtro = ""
        if id_cliente:
            filtro = _FILTRO_CLIENTE
            parametros.append(id_cliente)
        return filtro, parametros

    def resumen(self, desde, hasta, id_cliente=None) -> dict:
        filtro, parametros = self._parametros(desde, hasta, id_cliente)
        # El filtro por cliente se aplica dos veces: una sobre los
        # movimientos de caja y otra sobre las facturas del periodo.
        filtro_mov = filtro.replace("f.id_cliente", "m.id_cliente")

        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                WITH movimientos AS ({MOVIMIENTOS})
                SELECT
                  -- Lo que entró a la caja en el período, IVA incluido.
                  (SELECT COALESCE(SUM(m.monto), 0) FROM movimientos m
                    WHERE m.fecha BETWEEN %s AND %s {filtro_mov})
                    AS cobrado,
                  -- El ingreso real del gym: lo cobrado menos el IVA,
                  -- que se recauda para el SRI y no es plata propia.
                  (SELECT COALESCE(SUM(m.monto - m.iva), 0) FROM movimientos m
                    WHERE m.fecha BETWEEN %s AND %s {filtro_mov})
                    AS ingresos,
                  (SELECT COALESCE(SUM(m.iva), 0) FROM movimientos m
                    WHERE m.fecha BETWEEN %s AND %s {filtro_mov})
                    AS iva,
                  -- Los conteos son de ventas, no de plata: cuántas se
                  -- emitieron en el período, se hayan cobrado o no.
                  count(*) FILTER (WHERE f.estado = 'EMITIDA')  AS n_pagadas,
                  count(*) FILTER (WHERE f.estado = 'ANULADA')  AS n_anuladas,
                  count(*) FILTER (WHERE f.estado = 'PENDIENTE') AS n_pendientes,
                  COALESCE(SUM(f.total) FILTER (WHERE f.estado = 'ANULADA'), 0)
                    AS monto_anulado,
                  COALESCE(SUM(f.total) FILTER (WHERE f.estado <> 'ANULADA'), 0)
                    AS facturado,
                  COALESCE(SUM(f.saldo_pendiente)
                           FILTER (WHERE f.estado = 'PENDIENTE'), 0) AS por_cobrar,
                  COALESCE(SUM(f.subtotal * f.descuento_porcentaje / 100)
                           FILTER (WHERE f.estado <> 'ANULADA'), 0) AS descuentos
                  FROM facturas f
                 WHERE f.fecha::date BETWEEN %s AND %s
                 {filtro}
                """,
                # Cuatro veces los mismos parámetros: las tres
                # subconsultas de caja y el WHERE de las facturas.
                parametros * 4,
            )
            fila = cursor.fetchone()

        # El ticket promedio es de ventas, no de caja: cuánto gastó en
        # promedio quien compró. Un abono de una fiada vieja no es una
        # venta nueva y no debe mover este número.
        vendidas = fila["n_pagadas"] + fila["n_pendientes"]
        fila["ticket_promedio"] = (
            fila["facturado"] / vendidas if vendidas else 0
        )
        return fila

    def por_metodo_pago(self, desde, hasta, id_cliente=None) -> list[dict]:
        """Cuánto entró por efectivo y cuánto por transferencia.

        Sale de los mismos movimientos de caja que el resumen, y no de
        una suma aparte: si se calculan por separado, el día que una
        venta entre en un total y no en el otro nadie se entera.

        Cada abono trae su propio método, porque una fiada se puede
        haber pagado en efectivo una vez y por transferencia la
        siguiente.
        """
        filtro, parametros = self._parametros(desde, hasta, id_cliente)
        filtro_mov = filtro.replace("f.id_cliente", "m.id_cliente")
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                WITH movimientos AS ({MOVIMIENTOS})
                SELECT COALESCE(m.metodo_pago, 'SIN ESPECIFICAR') AS metodo,
                       SUM(m.monto) AS monto,
                       count(*) AS n_facturas
                  FROM movimientos m
                 WHERE m.fecha BETWEEN %s AND %s
                   {filtro_mov}
                 GROUP BY 1
                 ORDER BY monto DESC
                """,
                parametros,
            )
            return cursor.fetchall()

    def por_categoria(self, desde, hasta, id_cliente=None) -> list[dict]:
        """Separa lo vendido entre membresías Junior, Senior y productos.

        Suma el subtotal de las líneas, no el total de la factura, para
        poder repartir una factura que lleve de ambos.

        Los pases cuentan como Senior, igual que en el resto del
        sistema. El CASE sobre 'PASES' existe para que el reporte sea
        correcto también en bases que todavía no corrieron la migración
        de tipos; una vez migradas, esa rama simplemente no se usa.
        """
        filtro, parametros = self._parametros(desde, hasta, id_cliente)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT CASE
                         WHEN d.id_plan IS NULL THEN 'Productos'
                         WHEN p.tipo = 'JUNIOR' THEN 'Membresías Junior'
                         ELSE 'Membresías Senior'
                       END AS categoria,
                       -- Neto de IVA y de descuento, igual que el ingreso
                       -- del encabezado, para que las categorías sumen el
                       -- mismo total y el reporte no se contradiga. Se
                       -- reparte el neto de cada factura en proporción al
                       -- peso de cada línea, porque el detalle no guarda
                       -- su propio IVA ni su parte del descuento.
                       SUM(d.subtotal / NULLIF(f.subtotal, 0)
                           * (f.total - f.iva)) AS monto,
                       SUM(d.cantidad) AS unidades
                  FROM detalle_factura d
                  JOIN facturas f ON f.id_factura = d.id_factura
             LEFT JOIN planes_membresia p ON p.id_plan = d.id_plan
                 WHERE f.estado = 'EMITIDA'
                   AND f.fecha::date BETWEEN %s AND %s
                   {filtro}
                 GROUP BY 1
                 ORDER BY monto DESC
                """,
                parametros,
            )
            return cursor.fetchall()

    def mas_vendidos(self, desde, hasta, id_cliente=None, limite=8) -> list[dict]:
        filtro, parametros = self._parametros(desde, hasta, id_cliente)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COALESCE(p.nombre, pm.nombre) AS nombre,
                       CASE WHEN d.id_plan IS NOT NULL THEN 'plan'
                            ELSE 'producto' END AS tipo,
                       SUM(d.cantidad) AS unidades,
                       -- Neto, en la misma base que el resto del reporte.
                       SUM(d.subtotal / NULLIF(f.subtotal, 0)
                           * (f.total - f.iva)) AS monto
                  FROM detalle_factura d
                  JOIN facturas f ON f.id_factura = d.id_factura
                  LEFT JOIN productos p ON p.id_producto = d.id_producto
                  LEFT JOIN planes_membresia pm ON pm.id_plan = d.id_plan
                 WHERE f.estado = 'EMITIDA'
                   AND f.fecha::date BETWEEN %s AND %s
                   {filtro}
                 GROUP BY 1, 2
                 ORDER BY monto DESC
                 LIMIT %s
                """,
                parametros + [limite],
            )
            return cursor.fetchall()

    def por_dia(self, desde, hasta, id_cliente=None) -> list[dict]:
        """Serie diaria del período, para ver la evolución."""
        filtro, parametros = self._parametros(desde, hasta, id_cliente)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT f.fecha::date AS dia,
                       SUM(f.total) AS monto,
                       count(*) AS n_facturas
                  FROM facturas f
                 WHERE f.estado = 'EMITIDA'
                   AND f.fecha::date BETWEEN %s AND %s
                   {filtro}
                 GROUP BY 1
                 ORDER BY 1
                """,
                parametros,
            )
            return cursor.fetchall()

    def por_vendedor(self, desde, hasta, id_cliente=None) -> list[dict]:
        filtro, parametros = self._parametros(desde, hasta, id_cliente)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT e.nombre || ' ' || e.apellido AS vendedor,
                       SUM(f.total) AS monto,
                       count(*) AS n_facturas
                  FROM facturas f
                  JOIN empleados e ON e.id_empleado = f.id_empleado
                 WHERE f.estado = 'EMITIDA'
                   AND f.fecha::date BETWEEN %s AND %s
                   {filtro}
                 GROUP BY 1
                 ORDER BY monto DESC
                """,
                parametros,
            )
            return cursor.fetchall()
