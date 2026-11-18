"""Pruebas del reparto de productos en facturas en bloque.

Lo que se comprueba es lo unico que no puede fallar:

  - ni una unidad se pierde ni se duplica
  - ninguna factura pasa del tope de USD 200

Se prueba con miles de combinaciones al azar, porque el reparto
falla en los bordes: cuando una linea cae justo en el tope, cuando un
producto por si solo lo pasa, cuando sobra espacio para una unidad
pero no para dos.

No toca la base: el reparto es una cuenta, y se prueba como tal.
"""

import random
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.bloque_service import (  # noqa: E402
    ErrorBloque, LineaBloque, ServicioBloque, TOPE_CONSUMIDOR_FINAL,
)

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


servicio = ServicioBloque()

# El catalogo real del gimnasio.
CATALOGO = [
    (1, "Agua Cielo", Decimal("0.50")),
    (2, "Sporade", Decimal("0.75")),
    (3, "Coca-Cola", Decimal("0.75")),
    (4, "Cielo de Toronja", Decimal("0.75")),
    (5, "Agua Splendor", Decimal("1.00")),
    (6, "Cubo de magnesio", Decimal("5.00")),
]


def lineas(*pares):
    return [LineaBloque(CATALOGO[i][0], CATALOGO[i][1], CATALOGO[i][2], n)
            for i, n in pares]


print("\nLO QUE ENTRA EN UNA SOLA FACTURA")
bloques = servicio.repartir(lineas((0, 10), (5, 2)))
revisar("diez aguas y dos magnesios caben juntos", len(bloques) == 1,
        f"{len(bloques)} facturas")
revisar("suman $15.00", bloques[0].total == Decimal("15.00"),
        str(bloques[0].total))

print("\nNADA PARA FACTURAR")
revisar("sin lineas no hay facturas", servicio.repartir([]) == [])
revisar("con todo en cero tampoco", servicio.repartir(lineas((0, 0))) == [])

print("\nJUSTO EN EL TOPE")
# 400 aguas de $0.50 son exactamente $200.
bloques = servicio.repartir(lineas((0, 400)))
revisar("400 aguas entran en una sola factura", len(bloques) == 1,
        f"{len(bloques)} facturas")
revisar("y dan exactamente $200.00", bloques[0].total == Decimal("200.00"),
        str(bloques[0].total))

# Una mas y ya no.
bloques = servicio.repartir(lineas((0, 401)))
revisar("401 aguas necesitan dos facturas", len(bloques) == 2,
        f"{len(bloques)} facturas")
revisar("sin perder ninguna",
        sum(b.unidades for b in bloques) == 401,
        str(sum(b.unidades for b in bloques)))
revisar("y ninguna pasa del tope",
        all(b.total <= TOPE_CONSUMIDOR_FINAL for b in bloques),
        str([str(b.total) for b in bloques]))

print("\nUNA LINEA SOLA QUE PASA EL TOPE SE PARTE")
bloques = servicio.repartir(lineas((5, 100)))  # 100 magnesios a $5
revisar("100 magnesios ($500) dan tres facturas", len(bloques) == 3,
        f"{len(bloques)}: {[str(b.total) for b in bloques]}")
revisar("y suman los 100", sum(b.unidades for b in bloques) == 100,
        str(sum(b.unidades for b in bloques)))

print("\nUN MES ENTERO DE VENTAS")
bloques = servicio.repartir(lineas((0, 180), (1, 120), (4, 90), (5, 14)))
total = sum(b.total for b in bloques)
revisar("se reparte en varias facturas", len(bloques) >= 2,
        f"{len(bloques)}")
revisar("el total no cambia", total == Decimal("340.00"), str(total))
revisar("ninguna pasa del tope",
        all(b.total <= TOPE_CONSUMIDOR_FINAL for b in bloques),
        str([str(b.total) for b in bloques]))

print("\nSE RECHAZA LO QUE NO SE PUEDE REPARTIR")


def rechaza(etiqueta, hacer):
    try:
        hacer()
    except ErrorBloque:
        revisar(etiqueta, True)
    else:
        revisar(etiqueta, False, "no levanto ErrorBloque")


rechaza("una cantidad negativa",
        lambda: servicio.repartir(lineas((0, -5))))
rechaza("un producto con precio cero",
        lambda: servicio.repartir(
            [LineaBloque(9, "Raro", Decimal("0"), 3)]))
rechaza("un producto mas caro que el tope",
        lambda: servicio.repartir(
            [LineaBloque(9, "Algo carisimo", Decimal("250.00"), 1)]))

print("\nAL AZAR: 3000 PERIODOS")
# El reparto falla en los bordes, y los bordes aparecen con volumen.
random.seed(31)
malos = []
for _ in range(3000):
    propuesta = []
    for id_producto, nombre, precio in random.sample(
        CATALOGO, random.randint(1, len(CATALOGO))
    ):
        propuesta.append(
            LineaBloque(id_producto, nombre, precio, random.randint(1, 500))
        )
    repartido = servicio.repartir(propuesta)

    esperado = sum(l.cantidad for l in propuesta)
    salieron = sum(b.unidades for b in repartido)
    if esperado != salieron:
        malos.append(f"unidades {esperado} -> {salieron}")
        continue
    if any(b.total > TOPE_CONSUMIDOR_FINAL for b in repartido):
        malos.append(f"paso el tope: {max(b.total for b in repartido)}")
        continue
    # El dinero tampoco puede cambiar.
    antes = sum(l.total for l in propuesta)
    despues = sum(b.total for b in repartido)
    if antes != despues:
        malos.append(f"total {antes} -> {despues}")
        continue
    # Ni una unidad de mas por producto.
    por_producto = {}
    for bloque in repartido:
        for linea in bloque.lineas:
            por_producto[linea.id_producto] = (
                por_producto.get(linea.id_producto, 0) + linea.cantidad
            )
    for linea in propuesta:
        if por_producto.get(linea.id_producto, 0) != linea.cantidad:
            malos.append(f"{linea.nombre}: {linea.cantidad} -> "
                         f"{por_producto.get(linea.id_producto, 0)}")
            break

revisar("ninguna unidad se pierde ni se duplica, y ninguna pasa el tope",
        not malos, f"{len(malos)} fallos, p.ej. {malos[:2]}")

print("\nLAS FACTURAS SE LLENAN, NO QUEDAN A MEDIAS")
# Si cada factura quedara muy por debajo del tope, se emitirian
# muchas mas de las necesarias: cada una cuesta un secuencial.
bloques = servicio.repartir(lineas((0, 1000)))
minimo = min(b.total for b in bloques)
revisar(f"1000 aguas dan {len(bloques)} facturas, no mas",
        len(bloques) == 3, str(len(bloques)))
revisar("y todas salvo la ultima van llenas",
        all(b.total == TOPE_CONSUMIDOR_FINAL for b in bloques[:-1]),
        str([str(b.total) for b in bloques]))

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
