"""Consultas agregadas para el reporte de Contabilidad.

A diferencia de Facturas, que lista transacción por transacción, aquí
todo viene sumado: lo que interesa es el total del período, no cada
venta.

Regla que atraviesa todas las consultas: solo las facturas EMITIDA
cuentan como ingreso. Las ANULADA no valen y las PENDIENTE (fiadas)
todavía no se cobraron.
"""

from app.db import obtener_cursor

_FILTRO_CLIENTE = "AND f.id_cliente = %s"


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
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                  COALESCE(SUM(f.total) FILTER (WHERE f.estado = 'EMITIDA'), 0)
                    AS ingresos,
                  count(*) FILTER (WHERE f.estado = 'EMITIDA')  AS n_pagadas,
                  count(*) FILTER (WHERE f.estado = 'ANULADA')  AS n_anuladas,
                  count(*) FILTER (WHERE f.estado = 'PENDIENTE') AS n_pendientes,
                  COALESCE(SUM(f.total) FILTER (WHERE f.estado = 'ANULADA'), 0)
                    AS monto_anulado,
                  COALESCE(SUM(f.saldo_pendiente)
                           FILTER (WHERE f.estado = 'PENDIENTE'), 0) AS por_cobrar,
                  COALESCE(SUM(f.subtotal * f.descuento_porcentaje / 100)
                           FILTER (WHERE f.estado = 'EMITIDA'), 0) AS descuentos,
                  COALESCE(SUM(f.iva) FILTER (WHERE f.estado = 'EMITIDA'), 0) AS iva
                  FROM facturas f
                 WHERE f.fecha::date BETWEEN %s AND %s
                 {filtro}
                """,
                parametros,
            )
            fila = cursor.fetchone()

        fila["ticket_promedio"] = (
            fila["ingresos"] / fila["n_pagadas"] if fila["n_pagadas"] else 0
        )
        return fila

    def por_metodo_pago(self, desde, hasta, id_cliente=None) -> list[dict]:
        """Cuánto entró por efectivo y cuánto por transferencia.

        Suma los abonos de las fiadas que ya se saldaron, no el total de
        la factura, porque una fiada puede haberse pagado con métodos
        distintos en cada abono.
        """
        filtro, parametros = self._parametros(desde, hasta, id_cliente)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT f.metodo_pago AS metodo,
                       SUM(f.total) AS monto,
                       count(*) AS n_facturas
                  FROM facturas f
                 WHERE f.estado = 'EMITIDA'
                   AND f.metodo_pago IS NOT NULL
                   AND f.fecha::date BETWEEN %s AND %s
                   {filtro}
                 GROUP BY f.metodo_pago
                 ORDER BY monto DESC
                """,
                parametros,
            )
            return cursor.fetchall()

    def por_categoria(self, desde, hasta, id_cliente=None) -> list[dict]:
        """Separa lo vendido entre membresías y productos.

        Suma el subtotal de las líneas, no el total de la factura, para
        poder repartir una factura que lleve de ambos.
        """
        filtro, parametros = self._parametros(desde, hasta, id_cliente)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT CASE WHEN d.id_plan IS NOT NULL THEN 'Membresías'
                            ELSE 'Productos' END AS categoria,
                       SUM(d.subtotal) AS monto,
                       SUM(d.cantidad) AS unidades
                  FROM detalle_factura d
                  JOIN facturas f ON f.id_factura = d.id_factura
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
                       SUM(d.subtotal) AS monto
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
