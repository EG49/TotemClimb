"""El Excel diario de ventas, para cargarlas en Contífico.

Los comprobantes electrónicos los emite Contífico. Este sistema cobra,
guarda la venta y entrega el comprobante interno en el momento; al
cerrar el día alguien exporta lo vendido y lo registra allá.

Es una tarea semimanual, y las tareas semimanuales fallan de dos
formas: una venta cargada dos veces deja dos comprobantes autorizados
de la misma venta, y una que no se carga nunca es una venta sin
factura. Ninguna de las dos se nota al día siguiente.

Por eso esto no es solo "generar un archivo":

  * la exportación trae lo que todavía NO se ha cargado, no un rango
    de fechas a secas
  * cuando se confirma la carga, esas facturas quedan marcadas y no
    vuelven a salir
  * el resumen permite cuadrar: si el total del Excel y el de
    Contífico no coinciden, algo quedó afuera

A quién se le factura sale de la misma función que usaba el SRI
(_comprador_de), y no de una copia: si el cliente es un menor, la
factura va a su representante. Dos reglas distintas para lo mismo es
como terminan dos sistemas discrepando.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from app.db import obtener_cursor
from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService
from app.services.sri_service import ServicioSri

# Cómo se llama cada tipo de identificación en Contífico (campo
# `tipo` del cliente): N natural, J jurídica, I pasaporte/extranjero.
# Lo que se muestra es el nombre legible; quien carga lo elige en una
# lista, no escribe el código.
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


class ContificoService:
    """Lo vendido, listo para registrarlo en Contífico."""

    def __init__(self):
        self.bitacora = BitacoraService()

    # --- Qué falta cargar -------------------------------------------

    def pendientes(self, desde: date, hasta: date) -> list[dict]:
        """Las ventas del período que todavía no están en Contífico.

        Se excluyen las anuladas: no hay nada que facturar de una
        venta que se deshizo.
        """
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT f.id_factura, f.numero_factura, f.fecha,
                       f.metodo_pago, f.subtotal, f.iva, f.total,
                       f.descuento_porcentaje,
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
                   AND f.contifico_cargada_en IS NULL
                   AND f.fecha::date BETWEEN %s AND %s
                 ORDER BY f.fecha, f.id_factura
                """,
                (desde, hasta),
            )
            facturas = [dict(f) for f in cursor.fetchall()]

            if not facturas:
                return []

            cursor.execute(
                """
                SELECT d.id_factura, d.cantidad, d.precio_unitario,
                       d.subtotal,
                       COALESCE(p.nombre, pr.nombre, 'Ítem') AS item
                  FROM detalle_factura d
                  LEFT JOIN planes_membresia p ON p.id_plan = d.id_plan
                  LEFT JOIN productos pr ON pr.id_producto = d.id_producto
                 WHERE d.id_factura = ANY(%s)
                 ORDER BY d.id_factura, d.id_detalle
                """,
                ([f["id_factura"] for f in facturas],),
            )
            lineas: dict[int, list] = {}
            for fila in cursor.fetchall():
                lineas.setdefault(fila["id_factura"], []).append(dict(fila))

        for factura in facturas:
            factura["lineas"] = lineas.get(factura["id_factura"], [])
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

    # --- Confirmar la carga -----------------------------------------

    def marcar_cargadas(
        self, ids: list[int], id_empleado: int, desde=None, hasta=None
    ) -> int:
        """Esas ventas ya están en Contífico: no vuelven a salir.

        Se marca por lista de identificadores y no por rango de
        fechas, para que lo que se marca sea exactamente lo que se
        exportó. Si alguien cobra mientras el otro carga, esa venta
        nueva queda pendiente para la próxima, que es lo correcto.
        """
        if not ids:
            return 0

        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE facturas "
                "   SET contifico_cargada_en = NOW(), "
                "       contifico_cargada_por = %s "
                " WHERE id_factura = ANY(%s) "
                "   AND contifico_cargada_en IS NULL",
                (id_empleado, ids),
            )
            marcadas = cursor.rowcount

        try:
            self.bitacora.registrar(
                id_empleado, bit.CONTIFICO_CARGADO, bit.FACTURA, None,
                {"facturas": marcadas,
                 "desde": str(desde) if desde else None,
                 "hasta": str(hasta) if hasta else None},
            )
        except Exception:  # noqa: BLE001
            pass  # la marca es lo que importa; la nota es secundaria

        return marcadas

    def historial(self, limite: int = 30) -> list[dict]:
        """Las últimas cargas confirmadas, por día."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT contifico_cargada_en::date AS dia,
                       COUNT(*) AS facturas,
                       SUM(total) AS total,
                       MAX(e.nombre || ' ' || e.apellido) AS quien
                  FROM facturas f
                  LEFT JOIN empleados e
                         ON e.id_empleado = f.contifico_cargada_por
                 WHERE f.contifico_cargada_en IS NOT NULL
                 GROUP BY contifico_cargada_en::date
                 ORDER BY dia DESC
                 LIMIT %s
                """,
                (limite,),
            )
            return [dict(f) for f in cursor.fetchall()]

    # --- El archivo --------------------------------------------------

    def construir_excel(self, facturas: list[dict], desde: date,
                        hasta: date) -> bytes:
        """El libro con lo vendido, listo para registrar en Contífico."""
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

        libro = Workbook()
        titulo = Font(name="Arial", size=14, bold=True)
        cabecera = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        normal = Font(name="Arial", size=10)
        fuerte = Font(name="Arial", size=10, bold=True)
        fondo = PatternFill("solid", fgColor="27737C")
        borde = Border(bottom=Side(style="thin", color="C9D6D8"))
        money = '"$"#,##0.00'

        def encabezar(hoja, columnas):
            for col, (texto, ancho) in enumerate(columnas, start=1):
                celda = hoja.cell(row=1, column=col, value=texto)
                celda.font = cabecera
                celda.fill = fondo
                celda.alignment = Alignment(vertical="center")
                hoja.column_dimensions[
                    celda.column_letter].width = ancho
            hoja.freeze_panes = "A2"
            hoja.row_dimensions[1].height = 20

        # ── Resumen ────────────────────────────────────────────────
        resumen = libro.active
        resumen.title = "Resumen"
        resumen["A1"] = "Ventas para cargar en Contífico"
        resumen["A1"].font = titulo
        resumen["A2"] = f"Del {desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}"
        resumen["A2"].font = normal

        instrucciones = [
            "",
            "Cómo se usa este archivo:",
            "1. En la hoja «Facturas» está una línea por cada venta, con los datos del comprador.",
            "2. En «Detalle» están los ítems de cada una, buscando por el número de factura.",
            "3. Registre cada factura en Contífico.",
            "4. Cuando termine, vuelva al sistema y pulse «Confirmar carga».",
            "",
            "Mientras no confirme, estas ventas vuelven a salir en la próxima exportación.",
            "Eso es a propósito: es lo que evita que una venta se quede sin facturar.",
            "",
            "Antes de confirmar, cuadre el total de abajo con el de Contífico.",
            "Si no coinciden, algo quedó afuera o se cargó dos veces.",
        ]
        fila = 3
        for texto in instrucciones:
            resumen.cell(row=fila, column=1, value=texto).font = normal
            fila += 1

        fila += 1
        resumen.cell(row=fila, column=1, value="Forma de pago").font = fuerte
        resumen.cell(row=fila, column=2, value="Total").font = fuerte
        datos = self.resumen(facturas)
        for pago, monto in datos["por_pago"].items():
            fila += 1
            resumen.cell(row=fila, column=1, value=pago).font = normal
            # Suma desde la hoja Facturas y no el número calculado en
            # Python: si alguien corrige una fila, el total la sigue.
            celda = resumen.cell(
                row=fila, column=2,
                value=f'=SUMIF(Facturas!H:H,A{fila},Facturas!L:L)',
            )
            celda.font = normal
            celda.number_format = money

        fila += 1
        resumen.cell(row=fila, column=1, value="TOTAL").font = fuerte
        celda = resumen.cell(row=fila, column=2, value="=SUM(Facturas!L:L)")
        celda.font = fuerte
        celda.number_format = money

        fila += 1
        resumen.cell(row=fila, column=1, value="Facturas").font = fuerte
        celda = resumen.cell(row=fila, column=2,
                             value="=COUNTA(Facturas!A:A)-1")
        celda.font = fuerte

        resumen.column_dimensions["A"].width = 46
        resumen.column_dimensions["B"].width = 16

        # ── Facturas ───────────────────────────────────────────────
        hoja = libro.create_sheet("Facturas")
        encabezar(hoja, [
            ("N° venta", 13), ("Fecha", 11), ("Tipo ident.", 16),
            ("Identificación", 16), ("Comprador", 30), ("Correo", 28),
            ("Teléfono", 13), ("Forma de pago", 15), ("Subtotal", 12),
            ("Descuento %", 12), ("IVA", 11), ("Total", 12),
        ])
        for n, f in enumerate(facturas, start=2):
            valores = [
                f["numero_factura"],
                f["fecha"].date() if hasattr(f["fecha"], "date") else f["fecha"],
                ETIQUETA_IDENTIFICACION.get(f["tipo_identificacion"], ""),
                f["identificacion"],
                f["comprador"],
                f["correo_comprador"] or "",
                f["telefono"] or "",
                f["metodo_pago"] or SIN_FORMA_DE_PAGO,
                f["subtotal"], f["descuento_porcentaje"], f["iva"], f["total"],
            ]
            for col, valor in enumerate(valores, start=1):
                celda = hoja.cell(row=n, column=col, value=valor)
                celda.font = normal
                celda.border = borde
                if col == 2:
                    celda.number_format = "DD/MM/YYYY"
                elif col == 4:
                    # Como texto: una cédula que empieza en 0 pierde
                    # el cero si Excel la toma por número.
                    celda.number_format = "@"
                elif col in (9, 11, 12):
                    celda.number_format = money
                elif col == 10:
                    celda.number_format = "0.00"

        # ── Detalle ────────────────────────────────────────────────
        hoja = libro.create_sheet("Detalle")
        encabezar(hoja, [
            ("N° venta", 13), ("Ítem", 34), ("Cantidad", 10),
            ("P. unitario", 13), ("Subtotal", 12),
        ])
        n = 2
        for f in facturas:
            for linea in f["lineas"]:
                valores = [f["numero_factura"], linea["item"],
                           linea["cantidad"], linea["precio_unitario"],
                           linea["subtotal"]]
                for col, valor in enumerate(valores, start=1):
                    celda = hoja.cell(row=n, column=col, value=valor)
                    celda.font = normal
                    celda.border = borde
                    if col in (4, 5):
                        celda.number_format = money
                n += 1

        memoria = BytesIO()
        libro.save(memoria)
        return memoria.getvalue()
