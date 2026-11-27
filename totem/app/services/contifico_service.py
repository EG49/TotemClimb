"""Los Excel diarios de ventas, para cargarlas en Contífico.

Los comprobantes electrónicos los emite Contífico. Este sistema cobra,
guarda la venta y entrega el comprobante interno en el momento; al
cerrar el día se exporta lo vendido y alguien lo registra allá.

Son TRES archivos, y la separación no es de orden sino de fondo:

  * PLANES Y PASES van a nombre del cliente, con su cédula. Una
    factura por venta.
  * PRODUCTOS SUELTOS van en bloque a consumidor final: son decenas
    de personas distintas que compraron un agua, no hay a quién
    identificar. Por eso se agrupan en facturas que no pasen del tope.
  * POR COBRAR no es para facturar: es quién debe plata. Se exporta
    para cobrar, no para registrar en ningún lado.

Una venta puede llevar las dos cosas -- en esta base, una de cada
cuatro --, y entonces se parte: el plan en un archivo y la bebida en
el otro. Por eso cada tipo tiene su propia marca de cargado. Con una
sola marca, cargar los planes del día daría por cargadas también las
bebidas de esas ventas, que nadie registró.

Es una tarea semimanual, y las semimanuales fallan de dos formas: una
venta cargada dos veces deja dos comprobantes de la misma venta, y
una que no se carga nunca es una venta sin factura. Ninguna se nota
al día siguiente. De ahí el ciclo: sale lo que todavía NO se cargó,
se marca exactamente lo que se exportó, y lo no confirmado vuelve.

A quién se le factura sale de la misma función que usaba el SRI
(_comprador_de) y no de una copia: si el cliente es un menor, la
factura va a su representante.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from app.db import obtener_cursor
from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService
from app.services.bloque_service import (
    TOPE_CONSUMIDOR_FINAL, LineaBloque, ServicioBloque,
)
from app.services.sri_service import ServicioSri

ETIQUETA_IDENTIFICACION = {
    "04": "RUC",
    "05": "Cédula",
    "06": "Pasaporte",
    "07": "Consumidor final",
}

CONSUMIDOR_FINAL = "9999999999999"

# Una factura sin forma de pago se rotula igual en las dos hojas. Con
# el vacío en una y este texto en la otra, el desglose del resumen
# daba cero para esas ventas mientras el total general sí las
# contaba: cuadraba por arriba y mentía por dentro.
SIN_FORMA_DE_PAGO = "SIN ESPECIFICAR"

# Los dos tipos de carga, con las columnas que marcan cada uno.
TIPOS = {
    "planes": ("contifico_planes_en", "contifico_planes_por"),
    "productos": ("contifico_productos_en", "contifico_productos_por"),
}


class ContificoService:
    """Lo vendido, listo para registrarlo en Contífico."""

    def __init__(self):
        self.bitacora = BitacoraService()

    # --- Qué falta cargar -------------------------------------------

    def pendientes(self, tipo: str, desde: date, hasta: date) -> list[dict]:
        """Las ventas del período de ese tipo que faltan cargar.

        Una venta aparece solo si tiene líneas del tipo pedido: una
        membresía sola no sale en el archivo de productos.
        """
        if tipo not in TIPOS:
            raise ValueError(f"Tipo desconocido: {tipo}")
        columna = TIPOS[tipo][0]
        # Las líneas del otro tipo no se traen: el archivo de planes
        # no debe mostrar la bebida que iba en la misma venta.
        condicion = ("d.id_plan IS NOT NULL" if tipo == "planes"
                     else "d.id_producto IS NOT NULL")

        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT f.id_factura, f.numero_factura, f.fecha,
                       f.metodo_pago, f.saldo_pendiente,
                       c.nombre, c.apellido, c.cedula, c.correo,
                       c.telefono, c.id_representante,
                       r.nombre   AS rep_nombre,
                       r.apellido AS rep_apellido,
                       r.cedula   AS rep_cedula,
                       r.correo   AS rep_correo
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                  LEFT JOIN clientes r ON r.id_cliente = c.id_representante
                 WHERE f.estado <> 'ANULADA'
                   AND f.{columna} IS NULL
                   AND f.fecha::date BETWEEN %s AND %s
                   AND EXISTS (SELECT 1 FROM detalle_factura d
                                WHERE d.id_factura = f.id_factura
                                  AND {condicion})
                 ORDER BY f.fecha, f.id_factura
                """,
                (desde, hasta),
            )
            facturas = [dict(f) for f in cursor.fetchall()]

            if not facturas:
                return []

            cursor.execute(
                f"""
                SELECT d.id_factura, d.id_producto, d.cantidad,
                       d.precio_unitario, d.subtotal,
                       COALESCE(p.nombre, pr.nombre, 'Ítem') AS item
                  FROM detalle_factura d
                  LEFT JOIN planes_membresia p ON p.id_plan = d.id_plan
                  LEFT JOIN productos pr ON pr.id_producto = d.id_producto
                 WHERE d.id_factura = ANY(%s) AND {condicion}
                 ORDER BY d.id_factura, d.id_detalle
                """,
                ([f["id_factura"] for f in facturas],),
            )
            lineas: dict[int, list] = {}
            for fila in cursor.fetchall():
                lineas.setdefault(fila["id_factura"], []).append(dict(fila))

        for factura in facturas:
            propias = lineas.get(factura["id_factura"], [])
            factura["lineas"] = propias
            # El total es el de ESTAS líneas y no el de la venta: si
            # la venta llevaba también una bebida, ese monto va en el
            # otro archivo. Sumar el total de la factura acá haría que
            # los dos archivos juntos facturen de más.
            factura["total"] = sum(
                (Decimal(str(l["subtotal"])) for l in propias), Decimal("0")
            )
            factura["items"] = "; ".join(
                f"{l['item']} x{l['cantidad']}" if l["cantidad"] != 1
                else l["item"] for l in propias
            )
            nombre, cedula, correo = ServicioSri._comprador_de(factura)
            factura["comprador"] = nombre
            factura["identificacion"] = cedula or CONSUMIDOR_FINAL
            factura["correo_comprador"] = correo
            factura["tipo_identificacion"] = self._tipo(cedula)
        return facturas

    @staticmethod
    def _tipo(cedula: str | None) -> str:
        """Qué tipo de identificación es, con el criterio del SRI."""
        if not cedula:
            return "07"
        limpia = cedula.strip()
        if not limpia.isdigit():
            return "06"
        if len(limpia) == 13:
            return "04"
        return "05"

    def resumen(self, facturas: list[dict]) -> dict:
        """Totales para cuadrar contra lo que quede en Contífico."""
        por_pago: dict[str, Decimal] = {}
        total = Decimal("0")
        for factura in facturas:
            monto = Decimal(str(factura["total"]))
            total += monto
            pago = factura["metodo_pago"] or SIN_FORMA_DE_PAGO
            por_pago[pago] = por_pago.get(pago, Decimal("0")) + monto
        return {
            "facturas": len(facturas),
            "total": total,
            "por_pago": dict(sorted(por_pago.items())),
        }

    def agrupar_productos(self, facturas: list[dict]) -> list:
        """Reparte los productos en facturas que no pasen del tope.

        Van a consumidor final -- son muchas personas distintas, no
        hay a quién identificar -- y una factura a consumidor final no
        puede pasar del tope. Se reutiliza el reparto del servicio de
        bloques y no se escribe otro: aquel trabaja por unidades, que
        es lo que hace falta cuando una sola línea pasa el tope por sí
        misma.
        """
        juntas: dict[tuple, LineaBloque] = {}
        for factura in facturas:
            for linea in factura["lineas"]:
                clave = (linea["id_producto"], str(linea["precio_unitario"]))
                if clave in juntas:
                    juntas[clave].cantidad += linea["cantidad"]
                else:
                    juntas[clave] = LineaBloque(
                        id_producto=linea["id_producto"],
                        nombre=linea["item"],
                        precio_unitario=Decimal(str(linea["precio_unitario"])),
                        cantidad=linea["cantidad"],
                    )
        if not juntas:
            return []
        return ServicioBloque().repartir(list(juntas.values()))

    # --- Confirmar la carga -----------------------------------------

    def marcar_cargadas(self, tipo: str, ids: list[int], id_empleado: int,
                        desde=None, hasta=None) -> int:
        """Esas ventas ya están en Contífico: no vuelven a salir.

        Se marca por lista de identificadores y no por rango de
        fechas, para que lo que se marca sea exactamente lo que se
        exportó. Si alguien cobra mientras el otro carga, esa venta
        nueva queda pendiente para la próxima, que es lo correcto.
        """
        if tipo not in TIPOS:
            raise ValueError(f"Tipo desconocido: {tipo}")
        if not ids:
            return 0
        cuando, quien = TIPOS[tipo]

        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                f"UPDATE facturas SET {cuando} = NOW(), {quien} = %s "
                f" WHERE id_factura = ANY(%s) AND {cuando} IS NULL",
                (id_empleado, ids),
            )
            marcadas = cursor.rowcount

        try:
            self.bitacora.registrar(
                id_empleado, bit.CONTIFICO_CARGADO, bit.FACTURA, None,
                {"tipo": tipo, "facturas": marcadas,
                 "desde": str(desde) if desde else None,
                 "hasta": str(hasta) if hasta else None},
            )
        except Exception:  # noqa: BLE001
            pass  # la marca es lo que importa; la nota es secundaria

        return marcadas

    def historial(self, limite: int = 30) -> list[dict]:
        """Las últimas cargas confirmadas, por día y tipo."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT dia, tipo, COUNT(*) AS facturas, MAX(quien) AS quien
                  FROM (
                    SELECT contifico_planes_en::date AS dia,
                           'Planes' AS tipo,
                           e.nombre || ' ' || e.apellido AS quien
                      FROM facturas f
                      LEFT JOIN empleados e
                             ON e.id_empleado = f.contifico_planes_por
                     WHERE f.contifico_planes_en IS NOT NULL
                    UNION ALL
                    SELECT contifico_productos_en::date, 'Productos',
                           e.nombre || ' ' || e.apellido
                      FROM facturas f
                      LEFT JOIN empleados e
                             ON e.id_empleado = f.contifico_productos_por
                     WHERE f.contifico_productos_en IS NOT NULL
                  ) AS cargas
                 GROUP BY dia, tipo
                 ORDER BY dia DESC, tipo
                 LIMIT %s
                """,
                (limite,),
            )
            return [dict(f) for f in cursor.fetchall()]

    # --- Por cobrar ---------------------------------------------------

    def por_cobrar(self) -> list[dict]:
        """Quién debe plata, de más viejo a más nuevo.

        Esto no se carga en ningún lado: es para cobrar. Va ordenado
        por antigüedad porque una deuda de hace tres meses importa más
        que una de ayer.
        """
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT f.numero_factura, f.fecha, f.total,
                       f.saldo_pendiente,
                       (f.total - f.saldo_pendiente) AS abonado,
                       (CURRENT_DATE - f.fecha::date) AS dias,
                       c.nombre, c.apellido, c.cedula, c.correo, c.telefono
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                 WHERE f.estado <> 'ANULADA' AND f.saldo_pendiente > 0
                 ORDER BY f.fecha
                """
            )
            return [dict(f) for f in cursor.fetchall()]

    # --- Los archivos --------------------------------------------------

    @staticmethod
    def _estilos():
        from openpyxl.styles import Border, Font, PatternFill, Side
        return {
            "titulo": Font(name="Arial", size=14, bold=True),
            "cabecera": Font(name="Arial", size=10, bold=True, color="FFFFFF"),
            "normal": Font(name="Arial", size=10),
            "fuerte": Font(name="Arial", size=10, bold=True),
            "fondo": PatternFill("solid", fgColor="27737C"),
            "borde": Border(bottom=Side(style="thin", color="C9D6D8")),
            "money": '"$"#,##0.00',
        }

    @staticmethod
    def _encabezar(hoja, columnas, e):
        from openpyxl.styles import Alignment
        for col, (texto, ancho) in enumerate(columnas, start=1):
            celda = hoja.cell(row=1, column=col, value=texto)
            celda.font = e["cabecera"]
            celda.fill = e["fondo"]
            celda.alignment = Alignment(vertical="center")
            hoja.column_dimensions[celda.column_letter].width = ancho
        hoja.freeze_panes = "A2"
        hoja.row_dimensions[1].height = 20

    @staticmethod
    def _fila(hoja, n, valores, e, fechas=(), texto=(), dinero=()):
        for col, valor in enumerate(valores, start=1):
            celda = hoja.cell(row=n, column=col, value=valor)
            celda.font = e["normal"]
            celda.border = e["borde"]
            if col in fechas:
                celda.number_format = "DD/MM/YYYY"
            elif col in texto:
                # Una cédula que empieza en 0 pierde el cero si Excel
                # la toma por número, y deja de ser una cédula.
                celda.number_format = "@"
            elif col in dinero:
                celda.number_format = e["money"]

    @staticmethod
    def _portada(hoja, e, titulo, desde, hasta, lineas):
        hoja["A1"] = titulo
        hoja["A1"].font = e["titulo"]
        hoja["A2"] = (f"Del {desde.strftime('%d/%m/%Y')} "
                      f"al {hasta.strftime('%d/%m/%Y')}")
        hoja["A2"].font = e["normal"]
        fila = 4
        for texto in lineas:
            hoja.cell(row=fila, column=1, value=texto).font = e["normal"]
            fila += 1
        hoja.column_dimensions["A"].width = 54
        hoja.column_dimensions["B"].width = 16
        return fila + 1

    def _totales(self, hoja, e, fila, facturas, nombre, col_pago, col_total):
        hoja.cell(row=fila, column=1, value="Forma de pago").font = e["fuerte"]
        hoja.cell(row=fila, column=2, value="Total").font = e["fuerte"]
        for pago in self.resumen(facturas)["por_pago"]:
            fila += 1
            hoja.cell(row=fila, column=1, value=pago).font = e["normal"]
            # Suma desde la hoja de ventas y no el número calculado en
            # Python: si alguien corrige una fila, el total la sigue.
            celda = hoja.cell(
                row=fila, column=2,
                value=f"=SUMIF({nombre}!{col_pago}:{col_pago},A{fila},"
                      f"{nombre}!{col_total}:{col_total})",
            )
            celda.font = e["normal"]
            celda.number_format = e["money"]
        fila += 1
        hoja.cell(row=fila, column=1, value="TOTAL").font = e["fuerte"]
        celda = hoja.cell(row=fila, column=2,
                          value=f"=SUM({nombre}!{col_total}:{col_total})")
        celda.font = e["fuerte"]
        celda.number_format = e["money"]
        fila += 1
        hoja.cell(row=fila, column=1, value="Ventas").font = e["fuerte"]
        hoja.cell(row=fila, column=2,
                  value=f"=COUNTA({nombre}!A:A)-1").font = e["fuerte"]
        return fila

    @staticmethod
    def _guardar(libro) -> bytes:
        memoria = BytesIO()
        libro.save(memoria)
        return memoria.getvalue()

    def excel_planes(self, facturas, desde: date, hasta: date) -> bytes:
        """Una factura por venta, a nombre del cliente."""
        from openpyxl import Workbook

        e = self._estilos()
        libro = Workbook()
        resumen = libro.active
        resumen.title = "Resumen"
        fila = self._portada(resumen, e, "Membresías y pases", desde, hasta, [
            "Una factura por venta, a nombre del cliente.",
            "",
            "1. En «Ventas» hay una línea por cada una, con la cédula del",
            "   comprador y qué compró.",
            "2. Regístrelas en Contífico.",
            "3. Vuelva al sistema y pulse «Confirmar carga de planes».",
            "",
            "Mientras no confirme, vuelven a salir. Eso es a propósito:",
            "es lo que evita que una venta se quede sin facturar.",
            "",
            "Los productos sueltos van en SU PROPIO archivo, aparte. Si",
            "una venta llevaba también una bebida, acá está solo el plan:",
            "el monto de la bebida está en el otro archivo.",
            "",
            "Antes de confirmar, cuadre el total con el de Contífico.",
        ])
        self._totales(resumen, e, fila, facturas, "Ventas", "I", "K")

        hoja = libro.create_sheet("Ventas")
        self._encabezar(hoja, [
            ("N° venta", 13), ("Fecha", 11), ("Tipo ident.", 16),
            ("Identificación", 16), ("Comprador", 30), ("Correo", 28),
            ("Teléfono", 13), ("Qué compró", 38), ("Forma de pago", 15),
            ("Por cobrar", 12), ("Total", 12),
        ], e)
        for n, f in enumerate(facturas, start=2):
            self._fila(hoja, n, [
                f["numero_factura"],
                f["fecha"].date() if hasattr(f["fecha"], "date") else f["fecha"],
                ETIQUETA_IDENTIFICACION.get(f["tipo_identificacion"], ""),
                f["identificacion"], f["comprador"],
                f["correo_comprador"] or "", f["telefono"] or "",
                f["items"], f["metodo_pago"] or SIN_FORMA_DE_PAGO,
                f["saldo_pendiente"], f["total"],
            ], e, fechas=(2,), texto=(4,), dinero=(10, 11))
        return self._guardar(libro)

    def excel_productos(self, facturas, bloques, desde, hasta) -> bytes:
        """Los productos sueltos, agrupados para consumidor final."""
        from openpyxl import Workbook

        e = self._estilos()
        libro = Workbook()
        resumen = libro.active
        resumen.title = "Resumen"
        tope = f"${TOPE_CONSUMIDOR_FINAL:.0f}"
        fila = self._portada(resumen, e, "Productos sueltos", desde, hasta, [
            "Van a CONSUMIDOR FINAL: son muchas personas distintas que",
            "compraron una bebida, no hay a quién identificar.",
            "",
            f"Una factura a consumidor final no puede pasar de {tope}, así",
            "que en «Agrupado» ya están repartidos en facturas que no lo",
            "pasan. Registre una factura por cada grupo.",
            "",
            "En «Ventas» está de qué venta salió cada unidad, por si hay",
            "que revisar algo. Eso NO se carga: es respaldo.",
            "",
            "Cuando termine, vuelva al sistema y pulse «Confirmar carga",
            "de productos».",
        ])
        resumen.cell(row=fila, column=1, value="Facturas a crear").font = e["fuerte"]
        resumen.cell(row=fila, column=2, value=len(bloques)).font = e["fuerte"]
        fila += 1
        resumen.cell(row=fila, column=1, value="TOTAL").font = e["fuerte"]
        celda = resumen.cell(row=fila, column=2, value="=SUM(Agrupado!E:E)")
        celda.font = e["fuerte"]
        celda.number_format = e["money"]

        hoja = libro.create_sheet("Agrupado")
        self._encabezar(hoja, [
            ("Factura", 10), ("Producto", 34), ("Cantidad", 10),
            ("P. unitario", 13), ("Total", 12),
        ], e)
        n = 2
        for numero, bloque in enumerate(bloques, start=1):
            for linea in bloque.lineas:
                self._fila(hoja, n, [
                    f"#{numero}", linea.nombre, linea.cantidad,
                    linea.precio_unitario, linea.total,
                ], e, dinero=(4, 5))
                n += 1

        hoja = libro.create_sheet("Ventas")
        self._encabezar(hoja, [
            ("N° venta", 13), ("Fecha", 11), ("Cliente", 28),
            ("Producto", 30), ("Cantidad", 10), ("Total", 12),
        ], e)
        n = 2
        for f in facturas:
            for linea in f["lineas"]:
                self._fila(hoja, n, [
                    f["numero_factura"],
                    f["fecha"].date() if hasattr(f["fecha"], "date") else f["fecha"],
                    f"{f['nombre']} {f['apellido']}",
                    linea["item"], linea["cantidad"], linea["subtotal"],
                ], e, fechas=(2,), dinero=(6,))
                n += 1
        return self._guardar(libro)

    def excel_por_cobrar(self, deudas) -> bytes:
        """Quién debe plata. No se carga en ningún lado: se cobra."""
        from openpyxl import Workbook

        e = self._estilos()
        libro = Workbook()
        hoja = libro.active
        hoja.title = "Por cobrar"
        self._encabezar(hoja, [
            ("N° venta", 13), ("Fecha", 11), ("Días", 8), ("Cliente", 30),
            ("Cédula", 14), ("Teléfono", 13), ("Correo", 28),
            ("Total", 12), ("Abonado", 12), ("Debe", 12),
        ], e)
        for n, d in enumerate(deudas, start=2):
            self._fila(hoja, n, [
                d["numero_factura"],
                d["fecha"].date() if hasattr(d["fecha"], "date") else d["fecha"],
                d["dias"], f"{d['nombre']} {d['apellido']}",
                d["cedula"] or "", d["telefono"] or "", d["correo"] or "",
                d["total"], d["abonado"], d["saldo_pendiente"],
            ], e, fechas=(2,), texto=(5,), dinero=(8, 9, 10))

        if deudas:
            fila = len(deudas) + 2
            hoja.cell(row=fila, column=7, value="TOTAL").font = e["fuerte"]
            celda = hoja.cell(row=fila, column=10,
                              value=f"=SUM(J2:J{fila - 1})")
            celda.font = e["fuerte"]
            celda.number_format = e["money"]
        return self._guardar(libro)
