"""Los totales que se le muestran a alguien tienen que sumar.

Esta prueba existe porque el mismo error aparecio tres veces en tres
lugares distintos: la pantalla de cobro sumaba el IVA encima del
precio, y la pantalla del comprobante, la de la factura y el correo
mostraban "Subtotal $65.00, IVA $8.48, Total $65.00", que no suma.

La causa de fondo es una sola: los precios del catalogo INCLUYEN el
IVA, asi que el subtotal ya lo trae adentro y no es la base
imponible. Cada vez se arreglo el lugar que alguien habia visto, y el
error seguia en los otros.

Asi que acá no se revisa una pantalla: se renderizan TODAS las que
muestran plata y se comprueba la unica regla que no puede fallar:

    base imponible + IVA = total

Si manana aparece otra pantalla con totales, agreguela a PLANTILLAS.
"""

import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app  # noqa: E402
from app.models.factura import Factura  # noqa: E402

# Las pantallas que muestran plata, con el nombre de la variable que
# cada una espera.
PLANTILLAS = (
    ("cobrar/comprobante.html", "la pantalla despues de cobrar"),
    ("facturas/detalle.html", "la pantalla de la factura"),
    ("correo/comprobante.html", "el correo al cliente"),
)

# Precios reales del catalogo del gimnasio, que son los que importan.
CASOS = (
    ("Membresia Senior", Decimal("65.00")),
    ("Membresia Junior", Decimal("65.00")),
    ("Senior 3 meses", Decimal("145.00")),
    ("Mensualidad duo", Decimal("111.00")),
    ("Pase del dia", Decimal("10.00")),
    ("5 pases", Decimal("30.00")),
    ("10 pases", Decimal("49.00")),
    ("Agua Cielo", Decimal("0.50")),
    ("Sporade", Decimal("0.75")),
    ("Cubo de magnesio", Decimal("5.00")),
)

CENTAVO = Decimal("0.01")
IVA = Decimal("15")

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


def factura_de(nombre: str, precio: Decimal, descuento=Decimal("0")) -> Factura:
    """Una factura armada como la arma el cobro: el precio trae IVA."""
    subtotal = precio
    monto_descuento = (subtotal * descuento / 100).quantize(CENTAVO)
    total = (subtotal - monto_descuento).quantize(CENTAVO)
    base = (total / (1 + IVA / 100)).quantize(CENTAVO)
    iva = (total - base).quantize(CENTAVO)
    return Factura(
        id_factura=1,
        numero_factura="F-000002",
        fecha=datetime(2026, 11, 17, 5, 10),
        metodo_pago="EFECTIVO",
        descuento_porcentaje=descuento,
        iva_porcentaje=IVA,
        subtotal=subtotal,
        iva=iva,
        total=total,
        cliente_nombre="Emily Arreaga",
        cliente_correo="emily@ejemplo.com",
        empleado_nombre="Administrador Totem",
        detalle=[{
            "nombre": nombre, "cantidad": 1,
            "precio_unitario": precio, "subtotal": precio,
            "tipo": "plan",
        }],
    )


def plata(texto: str) -> dict:
    """Los numeros que la pantalla muestra, por su rotulo."""
    limpio = re.sub(r"<[^>]+>", " ", texto)
    limpio = re.sub(r"[ \t\r\f\v]+", " ", limpio)
    limpio = re.sub(r"\n\s*", " ", limpio)
    encontrados = {}
    # Cada importe se toma del signo $ en adelante, y entre el rotulo
    # y el signo no puede haber otro $: asi no se cuela el "15" del
    # porcentaje ni un numero del nombre de un item.
    #
    # El "total" lleva (?<!Sub) y \b porque "Total" tambien esta
    # adentro de "Subtotal", y los rotulos pueden venir con dos puntos
    # ("TOTAL: $65.00" en el correo en texto plano).
    for rotulo, patron in (
        ("base", r"Base imponible[^$]{0,20}\$\s*([\d.,]+)"),
        # El IVA se reconoce por el porcentaje que lo sigue: sin eso,
        # el rotulo "Subtotal con IVA" tambien entraba y se llevaba el
        # importe equivocado.
        ("iva", r"\bIVA\s*[\d.,]+\s*%[^$]{0,20}\$\s*([\d.,]+)"),
        ("total", r"(?<!Sub)(?<!sub)\bTotal\b[^$]{0,20}\$\s*([\d.,]+)"),
    ):
        hallazgo = re.search(patron, limpio, re.IGNORECASE)
        if hallazgo:
            encontrados[rotulo] = Decimal(hallazgo.group(1).replace(",", ""))
    return encontrados


app = crear_app()

print("\nLA BASE IMPONIBLE SALE DEL MODELO, NO DE CADA PLANTILLA")
for nombre, precio in CASOS:
    f = factura_de(nombre, precio)
    revisar(
        f"{nombre} ${precio}: base {f.base_imponible} + IVA {f.iva} = {f.total}",
        f.base_imponible + f.iva == f.total,
        f"da {f.base_imponible + f.iva}",
    )

with app.test_request_context():
    from flask import render_template

    for plantilla, descripcion in PLANTILLAS:
        print(f"\n{descripcion.upper()}  ({plantilla})")
        sin_rotulos = 0
        for nombre, precio in CASOS:
            f = factura_de(nombre, precio)
            try:
                salida = render_template(plantilla, factura=f)
            except Exception as error:  # noqa: BLE001
                revisar(f"{plantilla} se puede dibujar", False,
                        f"{type(error).__name__}: {error}")
                break

            numeros = plata(salida)
            if not {"base", "iva", "total"} <= set(numeros):
                sin_rotulos += 1
                continue
            suma = numeros["base"] + numeros["iva"]
            if suma != numeros["total"]:
                revisar(
                    f"{nombre} ${precio}: lo mostrado suma",
                    False,
                    f"base {numeros['base']} + IVA {numeros['iva']} "
                    f"= {suma}, pero muestra total {numeros['total']}",
                )
            else:
                revisar(
                    f"{nombre} ${precio}: base {numeros['base']} + IVA "
                    f"{numeros['iva']} = {numeros['total']}",
                    True,
                )
        revisar(
            f"{plantilla} muestra la base imponible",
            sin_rotulos == 0,
            f"{sin_rotulos} de {len(CASOS)} casos sin el rotulo 'Base "
            "imponible': si la pantalla no la muestra, nadie puede "
            "comprobar que los numeros cierren",
        )

print("\nLAS LINEAS SUMAN DE ARRIBA ABAJO")
# Sin descuento, el "Subtotal con IVA" es igual al Total. Mostrarlo
# arriba y abajo con el IVA en medio hace pensar que los numeros no
# cuadran: quien lee intenta sumar las tres lineas.
with app.test_request_context():
    from flask import render_template as _dibujar

    for plantilla, descripcion in PLANTILLAS:
        # Sin las etiquetas: en las pantallas el rotulo va como
        # "Subtotal <small>con IVA</small>", y buscar la frase literal
        # en el HTML no la encuentra.
        def rotulos(html):
            limpio = re.sub(r"<[^>]+>", " ", html)
            return re.sub(r"\s+", " ", limpio)

        f = factura_de("Membresia Junior", Decimal("65.00"))
        revisar(f"{descripcion}: sin descuento no repite el subtotal",
                "Subtotal con IVA" not in rotulos(_dibujar(plantilla, factura=f)),
                "aparece junto al total, con el mismo importe")

        con_descuento = factura_de("Membresia Junior", Decimal("65.00"),
                                   Decimal("20"))
        revisar(f"{descripcion}: con descuento si lo muestra",
                "Subtotal con IVA" in rotulos(
                    _dibujar(plantilla, factura=con_descuento)),
                "sin el, no se entiende de donde sale el descuento")

print("\nCON DESCUENTO TAMBIEN")
for descuento in (Decimal("10"), Decimal("20"), Decimal("50")):
    f = factura_de("Membresia Junior", Decimal("65.00"), descuento)
    revisar(
        f"descuento del {descuento}%: {f.base_imponible} + {f.iva} = {f.total}",
        f.base_imponible + f.iva == f.total,
        f"da {f.base_imponible + f.iva}",
    )

print("\nLA VERSION EN TEXTO DEL CORREO")
with app.app_context():
    from app.services.correo_service import ServicioCorreo

    for nombre, precio in CASOS[:4]:
        f = factura_de(nombre, precio)
        texto = ServicioCorreo._version_texto(f)
        numeros = plata(texto)
        completo = {"base", "iva", "total"} <= set(numeros)
        revisar(
            f"{nombre} ${precio}: el texto plano suma",
            completo and numeros["base"] + numeros["iva"] == numeros["total"],
            f"leidos {numeros}",
        )

total = len(fallas)
print(f"\n{'TODO OK' if not total else str(total) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
