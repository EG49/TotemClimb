"""Balance general: lo que entra menos lo que sale.

Dos decisiones que cambian las cifras y conviene entender:

  * **El ingreso va SIN IVA.** Lo cobrado en caja incluye el IVA, pero
    ese dinero se recauda para el SRI: pasa por la caja del gimnasio
    sin ser suyo. Contarlo como ingreso infla el resultado un 15%.
    Por eso el balance parte de la base imponible, y el IVA aparece
    aparte, como lo que es: una deuda con el SRI.

  * **El gasto va COMO SE PAGÓ.** No se le extrae el IVA. Podría
    hacerse, porque parte de ese IVA es crédito tributario, pero solo
    el de los gastos facturados, y eso ya es una decisión contable
    que nadie tomó todavía. Mientras tanto el balance muestra plata
    real que salió, que es lo que el gimnasio necesita saber, y
    separa facturado de no facturado para que se vea qué parte es
    justificable.

El resultado que sale de acá es de caja, no un estado de resultados
con las reglas del SRI. Para eso haría falta además depreciación,
devengado y el crédito tributario.

Sobre los segmentos: una membresía Junior es ingreso Junior, una
Senior es ingreso Senior, y los productos no son de nadie. En los
gastos, los que no se pueden repartir van a GENERAL. Por eso el
resultado por segmento se muestra solo donde las dos mitades
existen, y lo general queda aparte en vez de repartirse con una
regla inventada.
"""

from datetime import date
from decimal import Decimal

from app.repositories.contabilidad_repo import ContabilidadRepositorio
from app.repositories.gasto_repo import GastoRepositorio

CERO = Decimal("0")

# Cómo se llaman las categorías que devuelve el reporte de ingresos.
CATEGORIA_JUNIOR = "Membresías Junior"
CATEGORIA_SENIOR = "Membresías Senior"
CATEGORIA_PRODUCTOS = "Productos"


def _a_decimal(valor) -> Decimal:
    if valor is None:
        return CERO
    return Decimal(str(valor)).quantize(Decimal("0.01"))


class BalanceService:

    def __init__(self, ingresos=None, gastos=None):
        self.ingresos = ingresos or ContabilidadRepositorio()
        self.gastos = gastos or GastoRepositorio()

    def balance(self, desde: date, hasta: date) -> dict:
        resumen_ingresos = self.ingresos.resumen(desde, hasta)
        resumen_gastos = self.gastos.resumen(desde, hasta)
        categorias = self.ingresos.por_categoria(desde, hasta)

        entra = _a_decimal(resumen_ingresos["ingresos"])
        sale = _a_decimal(resumen_gastos["total"])
        resultado = entra - sale

        por_categoria = {c["categoria"]: _a_decimal(c["monto"]) for c in categorias}

        segmentos = [
            {
                "nombre": "Junior",
                "ingresos": por_categoria.get(CATEGORIA_JUNIOR, CERO),
                "gastos": _a_decimal(resumen_gastos["junior"]),
                "comparable": True,
            },
            {
                "nombre": "Senior",
                "ingresos": por_categoria.get(CATEGORIA_SENIOR, CERO),
                "gastos": _a_decimal(resumen_gastos["senior"]),
                "comparable": True,
            },
            {
                # Los productos entran pero no tienen gastos propios, y
                # los gastos generales no tienen ingresos propios. Se
                # muestran juntos y marcados, porque restar uno del otro
                # sugeriría una relación que no existe.
                "nombre": "General",
                "ingresos": por_categoria.get(CATEGORIA_PRODUCTOS, CERO),
                "gastos": _a_decimal(resumen_gastos["general"]),
                "comparable": False,
            },
        ]
        for s in segmentos:
            s["resultado"] = s["ingresos"] - s["gastos"]

        return {
            "desde": desde,
            "hasta": hasta,

            "ingresos": entra,
            "cobrado": _a_decimal(resumen_ingresos["cobrado"]),
            "iva_cobrado": _a_decimal(resumen_ingresos["iva"]),
            "descuentos": _a_decimal(resumen_ingresos["descuentos"]),
            "por_cobrar": _a_decimal(resumen_ingresos["por_cobrar"]),
            "n_facturas": resumen_ingresos["n_pagadas"],

            "gastos": sale,
            "gastos_facturados": _a_decimal(resumen_gastos["facturado"]),
            "gastos_sin_factura": _a_decimal(resumen_gastos["sin_factura"]),
            "n_gastos": resumen_gastos["n"],

            "resultado": resultado,
            "positivo": resultado >= 0,
            "margen": (
                round(float(resultado) / float(entra) * 100, 1) if entra else None
            ),

            "segmentos": segmentos,
            "por_concepto": self.gastos.por_concepto(desde, hasta),
            "categorias_ingreso": categorias,
        }
