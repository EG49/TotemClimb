"""Facturas en bloque de los productos sueltos.

Al SRI van automáticamente solo las membresías y los pases. Los
productos —aguas, bebidas, magnesio— se facturan cada tanto, juntando
lo vendido en un periodo en una o varias facturas a consumidor final.

Las tres reglas que ordenan este archivo
----------------------------------------
1. NI UNA UNIDAD SE PIERDE NI SE DUPLICA. Cada unidad vendida entra
   en exactamente una factura en bloque. Lo que se factura queda
   anotado sobre la línea de venta, y el reparto nunca toma lo ya
   anotado.

2. NINGUNA FACTURA PASA DE USD 200, que es el tope de una factura a
   consumidor final. Por eso un periodo puede dar varias facturas, y
   por eso el reparto trabaja por unidades y no por líneas: 400 aguas
   de $0.50 son exactamente el tope y 401 ya no entran juntas.

3. ESTO NO ES UNA VENTA. La plata ya se contó cuando se cobró. Vive
   en su propia tabla justamente para que ninguna consulta de
   contabilidad la alcance. Ver Sql/alter-sri-bloques.sql.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.db import obtener_cursor

CENTAVO = Decimal("0.01")

# El tope de una factura a consumidor final. Arriba de esto el SRI
# exige identificar al comprador, imposible cuando son decenas de
# clientes distintos.
TOPE_CONSUMIDOR_FINAL = Decimal("200.00")


class ErrorBloque(ValueError):
    """No se puede armar la factura en bloque."""


@dataclass
class LineaBloque:
    id_producto: int
    nombre: str
    precio_unitario: Decimal
    cantidad: int

    @property
    def total(self) -> Decimal:
        return (self.precio_unitario * self.cantidad).quantize(CENTAVO)


@dataclass
class BloquePropuesto:
    """Una factura por emitir, con lo que le toca."""

    lineas: list[LineaBloque] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((l.total for l in self.lineas), Decimal("0")).quantize(CENTAVO)

    @property
    def unidades(self) -> int:
        return sum(l.cantidad for l in self.lineas)


class ServicioBloque:

    # --- Qué falta facturar --------------------------------------

    def pendientes(self, desde: date, hasta: date) -> list[dict]:
        """Las unidades de producto vendidas y todavía no facturadas.

        Devuelve una fila por línea de venta, con cuántas unidades le
        quedan pendientes. No agrupa: el detalle hace falta para poder
        anotar después exactamente qué se facturó de cada una.
        """
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT d.id_detalle, d.id_producto, d.precio_unitario,
                       d.cantidad - d.unidades_en_bloque AS pendientes,
                       p.nombre, f.fecha
                  FROM detalle_factura d
                  JOIN productos p ON p.id_producto = d.id_producto
                  JOIN facturas  f ON f.id_factura  = d.id_factura
                 WHERE d.id_producto IS NOT NULL
                   AND d.cantidad > d.unidades_en_bloque
                   AND f.estado <> 'ANULADA'
                   AND f.fecha::date BETWEEN %s AND %s
                 ORDER BY f.fecha, d.id_detalle
                """,
                (desde, hasta),
            )
            return [dict(fila) for fila in cursor.fetchall()]

    def resumen(self, desde: date, hasta: date) -> dict:
        """Cuánto hay por facturar, para mostrarlo antes de emitir."""
        filas = self.pendientes(desde, hasta)
        por_producto: dict[int, LineaBloque] = {}
        for fila in filas:
            linea = por_producto.get(fila["id_producto"])
            if linea is None:
                por_producto[fila["id_producto"]] = LineaBloque(
                    id_producto=fila["id_producto"],
                    nombre=fila["nombre"],
                    precio_unitario=Decimal(fila["precio_unitario"]),
                    cantidad=fila["pendientes"],
                )
            else:
                linea.cantidad += fila["pendientes"]

        lineas = sorted(por_producto.values(), key=lambda l: -l.total)
        total = sum((l.total for l in lineas), Decimal("0")).quantize(CENTAVO)
        return {
            "lineas": lineas,
            "total": total,
            "unidades": sum(l.cantidad for l in lineas),
            "ventas": len({f["id_detalle"] for f in filas}),
            "facturas_necesarias": len(self.repartir(lineas)) if lineas else 0,
        }

    # --- El reparto ----------------------------------------------

    def repartir(
        self, lineas: list[LineaBloque], tope: Decimal = TOPE_CONSUMIDOR_FINAL
    ) -> list[BloquePropuesto]:
        """Parte lo pendiente en facturas que no pasen del tope.

        Trabaja por UNIDADES y no por líneas: una sola línea puede
        pasar el tope por sí misma (400 aguas de $0.50), y entonces
        hay que repartirla entre dos facturas. Las unidades de un
        mismo producto son intercambiables, así que partirlas no
        cambia nada de lo facturado.
        """
        if any(l.cantidad < 0 for l in lineas):
            raise ErrorBloque("hay una cantidad negativa")
        if any(l.precio_unitario <= 0 for l in lineas):
            raise ErrorBloque(
                "hay un producto con precio cero o negativo: no se puede "
                "repartir sin saber cuánto ocupa"
            )
        if any(l.precio_unitario > tope for l in lineas):
            caro = next(l for l in lineas if l.precio_unitario > tope)
            raise ErrorBloque(
                f"'{caro.nombre}' cuesta ${caro.precio_unitario}, más que el "
                f"tope de ${tope} de una factura a consumidor final. Esa "
                "venta hay que facturarla a nombre del cliente."
            )

        # Lo que falta de cada producto, en unidades.
        restante = [
            LineaBloque(l.id_producto, l.nombre, l.precio_unitario, l.cantidad)
            for l in lineas
            if l.cantidad > 0
        ]

        bloques: list[BloquePropuesto] = []
        actual = BloquePropuesto()
        usado = Decimal("0")

        for linea in restante:
            por_colocar = linea.cantidad
            while por_colocar > 0:
                espacio = tope - usado
                caben = int(espacio / linea.precio_unitario)
                if caben <= 0:
                    # No entra ni una: se cierra la factura y sigue en
                    # la próxima.
                    bloques.append(actual)
                    actual = BloquePropuesto()
                    usado = Decimal("0")
                    continue

                toman = min(caben, por_colocar)
                actual.lineas.append(LineaBloque(
                    linea.id_producto, linea.nombre,
                    linea.precio_unitario, toman,
                ))
                usado += (linea.precio_unitario * toman).quantize(CENTAVO)
                por_colocar -= toman

        if actual.lineas:
            bloques.append(actual)

        # Red de seguridad: lo repartido tiene que ser exactamente lo
        # que entró. Si alguna vez no lo fuera, es preferible no
        # emitir nada a emitir de menos o de más.
        esperado = sum(l.cantidad for l in lineas)
        repartido = sum(b.unidades for b in bloques)
        if esperado != repartido:
            raise ErrorBloque(
                f"el reparto no cierra: entraron {esperado} unidades y "
                f"salieron {repartido}"
            )
        for bloque in bloques:
            if bloque.total > tope:
                raise ErrorBloque(
                    f"una de las facturas quedó en ${bloque.total}, "
                    f"por encima del tope de ${tope}"
                )
        return bloques

    # --- Emisión --------------------------------------------------

    def emitir(self, desde: date, hasta: date, id_empleado: int) -> list[dict]:
        """Arma y emite las facturas en bloque del periodo.

        Devuelve una entrada por factura, con su estado ante el SRI.

        Cada factura se crea en su propia transacción, junto con la
        anotación de lo facturado sobre las líneas de venta. Si algo
        falla a la mitad, esa factura no queda a medias: o se creó
        entera y las unidades quedaron marcadas, o no se creó y las
        unidades siguen pendientes.
        """
        from app.services.configuracion_service import ConfiguracionService
        from app.services.sri_service import ServicioSri

        sri = ServicioSri()
        if not sri.configurado():
            raise ErrorBloque(
                "El sistema todavía no está configurado para emitir al SRI. "
                "Revise con: python -m scripts.sri_estado"
            )

        resumen = self.resumen(desde, hasta)
        if not resumen["lineas"]:
            raise ErrorBloque(
                "No hay productos pendientes de facturar en ese periodo."
            )

        iva = ConfiguracionService().iva_vigente()
        resultados = []
        for propuesto in self.repartir(resumen["lineas"]):
            resultados.append(
                self._emitir_uno(propuesto, desde, hasta, id_empleado, iva, sri)
            )
        return resultados

    def _emitir_uno(self, propuesto, desde, hasta, id_empleado, iva, sri):
        """Crea una factura en bloque, la anota y la manda al SRI."""
        total = propuesto.total
        base = (total / (1 + iva / 100)).quantize(
            CENTAVO, rounding=ROUND_HALF_UP
        )

        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO facturas_bloque
                    (desde, hasta, id_empleado, base_imponible, iva, total,
                     iva_porcentaje, sri_estado)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDIENTE')
                RETURNING id_bloque
                """,
                (desde, hasta, id_empleado, base, total - base, total, iva),
            )
            id_bloque = cursor.fetchone()["id_bloque"]

            for linea in propuesto.lineas:
                cursor.execute(
                    """
                    INSERT INTO detalle_bloque
                        (id_bloque, id_producto, cantidad, precio_unitario,
                         subtotal)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (id_bloque, linea.id_producto, linea.cantidad,
                     linea.precio_unitario, linea.total),
                )
                self._anotar(cursor, desde, hasta, linea)

            clave = sri.reservar_bloque(cursor, id_bloque)

        estado = "PENDIENTE"
        if clave:
            try:
                estado = sri.emitir_bloque(id_bloque)
            except Exception as error:  # noqa: BLE001
                estado = f"PENDIENTE ({type(error).__name__})"

        # Queda en la bitácora: alguien decidió facturar un periodo,
        # y eso marca ventas como facturadas de forma irreversible.
        try:
            from app.services.bitacora_service import BitacoraService

            BitacoraService().registrar(
                id_empleado, "BLOQUE_FACTURADO", "FACTURA", None,
                {
                    "id_bloque": id_bloque,
                    "desde": desde.isoformat(),
                    "hasta": hasta.isoformat(),
                    "total": str(total),
                    "unidades": propuesto.unidades,
                    "estado": estado,
                },
            )
        except Exception as error:  # noqa: BLE001
            from flask import current_app

            current_app.logger.warning(
                "No se pudo anotar la factura en bloque %s: %s",
                id_bloque, error,
            )

        return {
            "id_bloque": id_bloque,
            "total": total,
            "unidades": propuesto.unidades,
            "estado": estado,
        }

    @staticmethod
    def _anotar(cursor, desde, hasta, linea) -> None:
        """Marca en las ventas qué unidades entraron en este bloque.

        Va de la venta más vieja a la más nueva, tomando de cada una
        lo que le quede pendiente. Corre con el cursor de la factura
        en bloque, en su misma transacción: si la factura no se crea,
        las unidades no quedan marcadas y siguen disponibles.
        """
        por_marcar = linea.cantidad
        cursor.execute(
            """
            SELECT d.id_detalle, d.cantidad - d.unidades_en_bloque AS libres
              FROM detalle_factura d
              JOIN facturas f ON f.id_factura = d.id_factura
             WHERE d.id_producto = %s
               AND d.cantidad > d.unidades_en_bloque
               AND f.estado <> 'ANULADA'
               AND f.fecha::date BETWEEN %s AND %s
             ORDER BY f.fecha, d.id_detalle
             FOR UPDATE OF d
            """,
            (linea.id_producto, desde, hasta),
        )
        for fila in cursor.fetchall():
            if por_marcar <= 0:
                break
            toman = min(fila["libres"], por_marcar)
            cursor.execute(
                """
                UPDATE detalle_factura
                   SET unidades_en_bloque = unidades_en_bloque + %s
                 WHERE id_detalle = %s
                """,
                (toman, fila["id_detalle"]),
            )
            por_marcar -= toman

        if por_marcar > 0:
            # No deberia pasar: el reparto salio de estas mismas
            # ventas. Si pasa, algo cambio en el medio y es preferible
            # deshacer todo antes que facturar lo que no se vendio.
            raise ErrorBloque(
                f"faltaron {por_marcar} unidades de '{linea.nombre}' por "
                "marcar: las ventas cambiaron mientras se armaba la "
                "factura. No se emitió nada."
            )

    # --- Consulta -------------------------------------------------

    def historial(self, limite: int = 20) -> list[dict]:
        """Las facturas en bloque ya emitidas, de la más nueva primero."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT b.id_bloque, b.desde, b.hasta, b.fecha_emision,
                       b.total, b.sri_estado, b.sri_secuencial,
                       b.sri_establecimiento, b.sri_punto_emision,
                       b.sri_mensaje,
                       (SELECT COALESCE(SUM(cantidad), 0)
                          FROM detalle_bloque d
                         WHERE d.id_bloque = b.id_bloque) AS unidades
                  FROM facturas_bloque b
                 ORDER BY b.fecha_emision DESC
                 LIMIT %s
                """,
                (limite,),
            )
            return [dict(fila) for fila in cursor.fetchall()]
