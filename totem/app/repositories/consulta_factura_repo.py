"""Consultas del historial de facturas.

Separado de factura_repo.py, que se ocupa de la escritura durante el
cobro. Aquí solo se lee y se filtra.
"""

from app.db import obtener_cursor
from app.models.factura import Factura

# Traducción de los filtros de la pantalla a condiciones SQL.
_ESTADOS = {
    "todas": None,
    "pagadas": "f.estado = 'EMITIDA'",
    "pendientes": "f.estado = 'PENDIENTE'",
    "anuladas": "f.estado = 'ANULADA'",
}

_TIPOS = {
    "todos": None,
    "membresias": (
        "EXISTS (SELECT 1 FROM detalle_factura d "
        "WHERE d.id_factura = f.id_factura AND d.id_plan IS NOT NULL)"
    ),
    "productos": (
        "EXISTS (SELECT 1 FROM detalle_factura d "
        "WHERE d.id_factura = f.id_factura AND d.id_producto IS NOT NULL)"
    ),
}

# Nombre del ítem de una línea, venga de productos o de planes.
_NOMBRE_ITEM = "COALESCE(p.nombre, pm.nombre)"

_JOIN_ITEMS = """
    LEFT JOIN productos p ON p.id_producto = d.id_producto
    LEFT JOIN planes_membresia pm ON pm.id_plan = d.id_plan
"""


class ConsultaFacturaRepositorio:

    def _condiciones(self, filtros: dict):
        condiciones, parametros = [], []

        if filtros.get("q"):
            condiciones.append(
                "((c.nombre || ' ' || c.apellido) ILIKE %s "
                " OR c.cedula LIKE %s OR f.numero_factura ILIKE %s)"
            )
            patron = f"%{filtros['q']}%"
            parametros += [patron, patron, patron]

        if filtros.get("desde"):
            condiciones.append("f.fecha::date >= %s")
            parametros.append(filtros["desde"])

        if filtros.get("hasta"):
            condiciones.append("f.fecha::date <= %s")
            parametros.append(filtros["hasta"])

        estado = _ESTADOS.get(filtros.get("estado", "todas"))
        if estado:
            condiciones.append(estado)

        tipo = _TIPOS.get(filtros.get("tipo", "todos"))
        if tipo:
            condiciones.append(tipo)

        if filtros.get("metodo") and filtros["metodo"] != "todos":
            condiciones.append("f.metodo_pago = %s")
            parametros.append(filtros["metodo"])

        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
        return where, parametros

    def listar(self, filtros: dict, pagina: int = 1, por_pagina: int = 25) -> list[dict]:
        where, parametros = self._condiciones(filtros)
        desplazamiento = (max(pagina, 1) - 1) * por_pagina

        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT f.id_factura, f.numero_factura, f.fecha, f.metodo_pago,
                       f.descuento_porcentaje, f.iva_porcentaje, f.subtotal,
                       f.iva, f.total, f.estado, f.motivo_anulacion,
                       f.saldo_pendiente,
                       c.nombre || ' ' || c.apellido AS cliente_nombre,
                       c.cedula AS cliente_cedula,
                       e.nombre || ' ' || e.apellido AS empleado_nombre,
                       (SELECT {_NOMBRE_ITEM} FROM detalle_factura d {_JOIN_ITEMS}
                         WHERE d.id_factura = f.id_factura
                         ORDER BY d.id_detalle LIMIT 1) AS primer_item,
                       (SELECT count(*) FROM detalle_factura d
                         WHERE d.id_factura = f.id_factura) AS n_items,
                       (SELECT string_agg({_NOMBRE_ITEM} || ' x' || d.cantidad, ' · '
                                          ORDER BY d.id_detalle)
                          FROM detalle_factura d {_JOIN_ITEMS}
                         WHERE d.id_factura = f.id_factura) AS items_texto,
                       (SELECT count(*) FROM pagos_fiado pf
                         WHERE pf.id_factura = f.id_factura) AS n_abonos
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                  JOIN empleados e ON e.id_empleado = f.id_empleado
                  {where}
                 ORDER BY f.fecha DESC, f.id_factura DESC
                 LIMIT %s OFFSET %s
                """,
                parametros + [por_pagina, desplazamiento],
            )
            return cursor.fetchall()

    def contar(self, filtros: dict) -> int:
        where, parametros = self._condiciones(filtros)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*) AS total
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                  {where}
                """,
                parametros,
            )
            return cursor.fetchone()["total"]

    def resumen(self, filtros: dict) -> dict:
        """Totales del período filtrado.

        Las anuladas no suman, y las fiadas no cuentan como ingreso
        hasta que terminan de pagarse: por eso 'facturado' solo mira las
        EMITIDA.
        """
        where, parametros = self._condiciones(filtros)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                  COALESCE(SUM(f.total) FILTER (WHERE f.estado = 'EMITIDA'), 0)
                    AS facturado,
                  count(*) FILTER (WHERE f.estado <> 'ANULADA') AS n_facturas,
                  count(*) FILTER (WHERE f.estado = 'EMITIDA')  AS n_pagadas,
                  count(*) FILTER (WHERE f.estado = 'ANULADA')  AS n_anuladas,
                  count(*) FILTER (WHERE f.estado = 'PENDIENTE') AS n_pendientes,
                  COALESCE(SUM(f.saldo_pendiente)
                           FILTER (WHERE f.estado = 'PENDIENTE'), 0) AS por_cobrar,
                  COALESCE(SUM(f.subtotal * f.descuento_porcentaje / 100)
                           FILTER (WHERE f.estado <> 'ANULADA'), 0) AS descuentos
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                  {where}
                """,
                parametros,
            )
            fila = cursor.fetchone()

        fila["ticket_promedio"] = (
            fila["facturado"] / fila["n_pagadas"] if fila["n_pagadas"] else 0
        )
        return fila

    def agrupado_por_cliente(self, filtros: dict) -> list[dict]:
        where, parametros = self._condiciones(filtros)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT c.id_cliente,
                       c.nombre || ' ' || c.apellido AS cliente_nombre,
                       c.cedula AS cliente_cedula,
                       count(*) FILTER (WHERE f.estado <> 'ANULADA') AS n_facturas,
                       COALESCE(SUM(f.total)
                                FILTER (WHERE f.estado = 'EMITIDA'), 0) AS facturado,
                       COALESCE(SUM(f.saldo_pendiente)
                                FILTER (WHERE f.estado = 'PENDIENTE'), 0) AS por_cobrar,
                       MAX(f.fecha) AS ultima
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                  {where}
                 GROUP BY c.id_cliente, c.nombre, c.apellido, c.cedula
                HAVING count(*) FILTER (WHERE f.estado <> 'ANULADA') > 0
                 ORDER BY facturado DESC
                """,
                parametros,
            )
            return cursor.fetchall()

    def abonos_de(self, id_factura: int) -> list[dict]:
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT pf.id_pago, pf.monto, pf.metodo_pago, pf.fecha,
                       e.nombre || ' ' || e.apellido AS empleado_nombre
                  FROM pagos_fiado pf
                  JOIN empleados e ON e.id_empleado = pf.id_empleado
                 WHERE pf.id_factura = %s
                 ORDER BY pf.fecha, pf.id_pago
                """,
                (id_factura,),
            )
            return cursor.fetchall()

    def para_exportar(self, filtros: dict) -> list[dict]:
        """Todas las filas del período filtrado, sin paginar."""
        where, parametros = self._condiciones(filtros)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT f.numero_factura, f.fecha,
                       c.nombre || ' ' || c.apellido AS cliente,
                       c.cedula,
                       e.nombre || ' ' || e.apellido AS vendedor,
                       (SELECT string_agg({_NOMBRE_ITEM} || ' x' || d.cantidad, ' | '
                                          ORDER BY d.id_detalle)
                          FROM detalle_factura d {_JOIN_ITEMS}
                         WHERE d.id_factura = f.id_factura) AS items,
                       f.subtotal, f.descuento_porcentaje, f.iva_porcentaje,
                       f.iva, f.total, f.metodo_pago, f.estado,
                       f.saldo_pendiente, f.motivo_anulacion
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                  JOIN empleados e ON e.id_empleado = f.id_empleado
                  {where}
                 ORDER BY f.fecha, f.id_factura
                """,
                parametros,
            )
            return cursor.fetchall()
