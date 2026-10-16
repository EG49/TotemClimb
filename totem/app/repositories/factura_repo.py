"""Repositorios de facturas, membresías y configuración.

Los métodos de escritura reciben el cursor desde el servicio, porque un
cobro completo (factura + detalle + membresías + abono) tiene que ocurrir
dentro de una sola transacción.
"""

from datetime import date
from decimal import Decimal

from app.db import obtener_cursor
from app.models.factura import Factura


class ConfiguracionRepositorio:

    def obtener(self, clave: str) -> str | None:
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT valor FROM configuracion WHERE clave = %s", (clave,)
            )
            fila = cursor.fetchone()
        return fila["valor"] if fila else None

    def guardar(self, clave: str, valor: str) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO configuracion (clave, valor, fecha_actualizacion)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (clave) DO UPDATE
                   SET valor = EXCLUDED.valor,
                       fecha_actualizacion = CURRENT_TIMESTAMP
                """,
                (clave, valor),
            )


class FacturaRepositorio:

    def siguiente_numero(self, cursor) -> str:
        """Toma el próximo número de la secuencia.

        Al venir de una secuencia, dos cobros simultáneos nunca reciben
        el mismo número.
        """
        cursor.execute(
            "SELECT 'F-' || lpad(nextval('seq_numero_factura')::text, 6, '0') AS numero"
        )
        return cursor.fetchone()["numero"]

    def crear(self, datos: dict, cursor) -> int:
        cursor.execute(
            """
            INSERT INTO facturas
                (numero_factura, id_cliente, id_empleado, metodo_pago,
                 descuento_porcentaje, iva_porcentaje, subtotal, iva, total,
                 estado, saldo_pendiente)
            VALUES (%(numero_factura)s, %(id_cliente)s, %(id_empleado)s,
                    %(metodo_pago)s, %(descuento_porcentaje)s, %(iva_porcentaje)s,
                    %(subtotal)s, %(iva)s, %(total)s, %(estado)s, %(saldo_pendiente)s)
            RETURNING id_factura
            """,
            datos,
        )
        return cursor.fetchone()["id_factura"]

    def agregar_detalle(
        self,
        id_factura: int,
        id_producto: int | None,
        id_plan: int | None,
        cantidad: int,
        precio_unitario: Decimal,
        subtotal: Decimal,
        cursor,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO detalle_factura
                (id_factura, id_producto, id_plan, cantidad, precio_unitario, subtotal)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (id_factura, id_producto, id_plan, cantidad, precio_unitario, subtotal),
        )

    def registrar_abono(
        self,
        id_factura: int,
        id_empleado: int,
        monto: Decimal,
        metodo_pago: str,
        cursor,
    ) -> int:
        cursor.execute(
            """
            INSERT INTO pagos_fiado (id_factura, id_empleado, monto, metodo_pago)
            VALUES (%s, %s, %s, %s) RETURNING id_pago
            """,
            (id_factura, id_empleado, monto, metodo_pago),
        )
        return cursor.fetchone()["id_pago"]

    def obtener(self, id_factura: int) -> Factura | None:
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT f.*,
                       c.nombre || ' ' || c.apellido AS cliente_nombre,
                       e.nombre || ' ' || e.apellido AS empleado_nombre
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                  JOIN empleados e ON e.id_empleado = f.id_empleado
                 WHERE f.id_factura = %s
                """,
                (id_factura,),
            )
            fila = cursor.fetchone()
            if fila is None:
                return None
            factura = Factura.desde_fila(fila)

            cursor.execute(
                """
                SELECT d.cantidad, d.precio_unitario, d.subtotal,
                       COALESCE(p.nombre, pm.nombre) AS nombre,
                       CASE WHEN d.id_plan IS NULL THEN 'producto' ELSE 'plan' END AS tipo
                  FROM detalle_factura d
                  LEFT JOIN productos p ON p.id_producto = d.id_producto
                  LEFT JOIN planes_membresia pm ON pm.id_plan = d.id_plan
                 WHERE d.id_factura = %s
                 ORDER BY d.id_detalle
                """,
                (id_factura,),
            )
            factura.detalle = cursor.fetchall()
        return factura


class MembresiaRepositorio:

    def fin_vigencia_actual(self, id_cliente: int, cursor) -> date | None:
        """Fecha en la que termina la membresía activa más larga.

        Se usa para que una renovación anticipada arranque donde termina
        la anterior, en vez de hacerle perder los días que le quedaban.
        """
        cursor.execute(
            """
            SELECT MAX(fecha_fin) AS fin
              FROM membresias
             WHERE id_cliente = %s
               AND estado = 'ACTIVA'
               AND fecha_fin >= CURRENT_DATE
            """,
            (id_cliente,),
        )
        fila = cursor.fetchone()
        return fila["fin"] if fila else None

    def crear(self, datos: dict, cursor) -> int:
        cursor.execute(
            """
            INSERT INTO membresias
                (id_cliente, id_plan, id_factura, fecha_inicio, fecha_fin,
                 dias_totales, dias_restantes)
            VALUES (%(id_cliente)s, %(id_plan)s, %(id_factura)s,
                    %(fecha_inicio)s, %(fecha_fin)s,
                    %(dias_totales)s, %(dias_restantes)s)
            RETURNING id_membresia
            """,
            datos,
        )
        return cursor.fetchone()["id_membresia"]

    def enlazar_pareja(self, id_a: int, id_b: int, cursor) -> None:
        """Deja las dos membresías de una promo apuntándose entre sí."""
        cursor.execute(
            "UPDATE membresias SET id_membresia_pareja = %s WHERE id_membresia = %s",
            (id_b, id_a),
        )
        cursor.execute(
            "UPDATE membresias SET id_membresia_pareja = %s WHERE id_membresia = %s",
            (id_a, id_b),
        )

    def actualizar_cache_cliente(self, id_cliente: int, cursor) -> None:
        """Refresca clientes.vigente_hasta.

        La fuente de verdad es membresias; esta columna solo evita tener
        que cruzar tablas en consultas rápidas.
        """
        cursor.execute(
            """
            UPDATE clientes
               SET vigente_hasta = (
                     SELECT MAX(fecha_fin) FROM membresias
                      WHERE id_cliente = %s AND estado = 'ACTIVA'
                   )
             WHERE id_cliente = %s
            """,
            (id_cliente, id_cliente),
        )
