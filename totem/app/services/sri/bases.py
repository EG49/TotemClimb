"""Reparto de la base imponible entre las líneas de la factura.

Acá está el problema que hace rechazar facturas, y conviene entenderlo
antes de tocar este archivo.

Nuestros precios INCLUYEN el IVA: un pase del día cuesta $10 y ya. El
XML del SRI, en cambio, pide los importes SIN IVA: `precioUnitario`,
`precioTotalSinImpuesto` y `baseImponible` de cada línea, y luego
`totalSinImpuestos` de la factura. El SRI valida que las sumas
cuadren; si no cuadran, rechaza el comprobante.

Dividir cada línea entre 1.15 por separado NO cuadra. Con tres pases
del día de $10:

    cada línea:  10 / 1.15 = 8.6956...  →  8.70
    suma:        8.70 * 3            =  26.10
    la factura:  30 / 1.15 = 26.0869...  →  26.09

Sobra un centavo. El SRI ve totalSinImpuestos = 26.09 y la suma de
los detalles = 26.10, y devuelve el comprobante.

La salida es calcular la base de la FACTURA primero —que es la que
tiene que cuadrar con el IVA y con el total— y después repartirla
entre las líneas, dándole el residuo a las líneas más grandes, de a
un centavo. Así la suma de las líneas da exactamente la base de la
factura, y el centavo cae donde menos se nota.
"""

from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")


class ErrorReparto(ValueError):
    """El reparto no pudo cerrar."""


def base_del_total(total: Decimal, iva_porcentaje: Decimal) -> Decimal:
    """La base imponible contenida en un total que ya trae el IVA.

    Se redondea la base y el IVA sale por resta, igual que en
    cobro_service.calcular(). Al revés no cierra: $10 daría una base
    de 8.69 y un IVA de 1.30, que suman 9.99.
    """
    divisor = 1 + iva_porcentaje / 100
    return (total / divisor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def repartir(base_factura: Decimal, pesos: list[Decimal]) -> list[Decimal]:
    """Reparte la base de la factura entre las líneas.

    `pesos` son los importes con IVA de cada línea; el reparto es
    proporcional a ellos. La suma de lo que devuelve es exactamente
    `base_factura`, siempre.

    El residuo se entrega de a un centavo a las líneas de mayor peso.
    Se ordena por peso descendente y, a peso igual, por posición, para
    que dos facturas iguales repartan igual: un reparto que depende
    del orden del diccionario sería imposible de auditar después.
    """
    if not pesos:
        if base_factura != 0:
            raise ErrorReparto("no hay líneas para repartir la base")
        return []
    if any(p < 0 for p in pesos):
        raise ErrorReparto("una línea no puede tener importe negativo")

    suma_pesos = sum(pesos)
    if suma_pesos == 0:
        # Todo a cero: factura de cortesía o descuento del 100%.
        if base_factura != 0:
            raise ErrorReparto(
                "las líneas suman cero pero la base no es cero"
            )
        return [Decimal("0.00") for _ in pesos]

    partes = [
        (base_factura * peso / suma_pesos).quantize(CENTAVO, rounding="ROUND_DOWN")
        for peso in pesos
    ]

    # Lo que falta por redondear hacia abajo, en centavos.
    faltante = base_factura - sum(partes)
    centavos = int((faltante / CENTAVO).to_integral_value())
    if centavos < 0:
        raise ErrorReparto(
            f"el reparto se pasó de la base en {abs(faltante)}"
        )

    orden = sorted(range(len(pesos)), key=lambda i: (-pesos[i], i))
    for vuelta in range(centavos):
        partes[orden[vuelta % len(orden)]] += CENTAVO

    if sum(partes) != base_factura:
        raise ErrorReparto(
            f"el reparto dio {sum(partes)} y la base es {base_factura}"
        )
    return partes
