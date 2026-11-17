"""Pruebas de la clave de acceso del SRI.

El dígito verificador es donde se equivocan todas las
implementaciones, así que acá no se comprueba que el código esté de
acuerdo consigo mismo. Se lo contrasta contra dos cosas de afuera:

1. La clave de acceso de un RIDE publicado (facturia.ec).
2. El algoritmo de open-factura, una librería ecuatoriana ajena a
   este proyecto, reimplementado abajo tal como está en su código.

Sobre el segundo punto: open-factura recorre los 48 dígitos de
IZQUIERDA a derecha con pesos 7,6,5,4,3,2, y nosotros de DERECHA a
izquierda con 2,3,4,5,6,7. Parecen distintos y dan lo mismo, porque
48 es múltiplo de 6 y los dos ciclos quedan alineados. La prueba lo
verifica sobre miles de claves en lugar de pedir que se confíe.

Advertencia para quien venga después: la documentación de
open-factura muestra como ejemplo la clave

    0112202401123456789000110010010000000014567890117

y ese último dígito, 7, está mal. Ninguna variante del módulo 11 lo
produce; el valor correcto es 9, y el propio código de esa librería
devuelve 9. Es una cadena inventada para ilustrar el formato. Si
alguien la usa para "corregir" este módulo, rompe la facturación.
"""

import random

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.sri import clave_acceso as ca  # noqa: E402

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    if condicion:
        print(f"  OK     {etiqueta}")
    else:
        print(f"  FALLA  {etiqueta}" + (f"  ({detalle})" if detalle else ""))
        fallas.append(etiqueta)


print("\nCONTRA UNA CLAVE DE ACCESO PUBLICADA")

# De un RIDE publicado en facturia.ec.
RIDE = "1510202601099999999900120010010000001241234567812"
revisar("la clave del RIDE se valida", ca.verificar(RIDE))
revisar("su digito verificador es 2",
        ca.digito_verificador(RIDE[:-1]) == "2",
        ca.digito_verificador(RIDE[:-1]))

# Y se la vuelve a armar desde sus campos, para probar el camino
# completo y no solo el digito.
armada = ca.generar(
    fecha_emision=date(2026, 10, 15),
    tipo_comprobante=ca.FACTURA,
    ruc="0999999999001",
    ambiente=ca.AMBIENTE_PRODUCCION,
    establecimiento="001",
    punto_emision="001",
    secuencial=124,
    codigo_numerico="12345678",
)
revisar("se la reconstruye digito por digito", armada == RIDE,
        f"publicada {RIDE}, armada {armada}")

print("\nCONTRA EL ALGORITMO DE OPEN-FACTURA")


def dv_open_factura(cuarenta_y_ocho):
    """El calculo de open-factura: izquierda a derecha, pesos 7..2."""
    total = 0
    peso = 7
    for caracter in cuarenta_y_ocho:
        total += int(caracter) * peso
        peso = peso - 1 if peso > 2 else 7
    verificador = 11 - (total % 11)
    if verificador == 11:
        return "0"
    if verificador == 10:
        return "1"
    return str(verificador)


revisar("coincide en la clave del RIDE",
        dv_open_factura(RIDE[:-1]) == ca.digito_verificador(RIDE[:-1]))

random.seed(7)
discrepancias = 0
for _ in range(20000):
    azar = "".join(random.choice("0123456789") for _ in range(48))
    if dv_open_factura(azar) != ca.digito_verificador(azar):
        discrepancias += 1
revisar("y en 20000 claves al azar", discrepancias == 0,
        f"{discrepancias} discrepancias")

# El ejemplo equivocado de su documentacion, anclado acá para que
# nadie lo tome por bueno. Ver la cabecera del archivo.
EJEMPLO_MALO = "0112202401123456789000110010010000000014567890117"
revisar("el ejemplo erroneo de la documentacion sigue siendo erroneo",
        not ca.verificar(EJEMPLO_MALO))
revisar("y open-factura tampoco lo produce",
        dv_open_factura(EJEMPLO_MALO[:-1]) == "9",
        dv_open_factura(EJEMPLO_MALO[:-1]))

generada = armada

print("\nFORMA DE LA CLAVE")
revisar("tiene 49 digitos", len(generada) == 49, str(len(generada)))
revisar("son todos digitos", generada.isdigit())

partes = ca.descomponer(generada)
revisar("la fecha queda ddmmaaaa", partes["fecha_emision"] == "15102026",
        partes["fecha_emision"])
revisar("el RUC se ubica bien", partes["ruc"] == "0999999999001",
        partes["ruc"])
revisar("el secuencial va con ceros a la izquierda",
        partes["secuencial"] == "000000124", partes["secuencial"])
revisar("el tipo de emision es normal", partes["tipo_emision"] == "1")

print("\nRELLENO DE CEROS")
suelta = ca.generar(
    fecha_emision=date(2026, 1, 5),
    tipo_comprobante=ca.FACTURA,
    ruc="1234567890001",
    ambiente=ca.AMBIENTE_PRODUCCION,
    establecimiento="1",
    punto_emision="2",
    secuencial=47,
    codigo_numerico="7",
)
p = ca.descomponer(suelta)
revisar("el establecimiento se rellena a 3", p["establecimiento"] == "001",
        p["establecimiento"])
revisar("el punto de emision se rellena a 3", p["punto_emision"] == "002",
        p["punto_emision"])
revisar("el secuencial se rellena a 9", p["secuencial"] == "000000047",
        p["secuencial"])
revisar("el codigo numerico se rellena a 8", p["codigo_numerico"] == "00000007",
        p["codigo_numerico"])
revisar("el 5 de enero no pierde el cero", p["fecha_emision"] == "05012026",
        p["fecha_emision"])
revisar("el ambiente de produccion es 2", p["ambiente"] == "2")

print("\nUNA CLAVE ADULTERADA NO PASA")
revisar("cambiar un digito la invalida",
        not ca.verificar(generada[:20] + ("9" if generada[20] != "9" else "8")
                         + generada[21:]))
revisar("48 digitos no pasan", not ca.verificar(generada[:-1]))
revisar("50 digitos no pasan", not ca.verificar(generada + "0"))
revisar("con letras no pasa", not ca.verificar("A" + generada[1:]))

print("\nDATOS QUE NO SIRVEN SE RECHAZAN")


def rechaza(etiqueta, **cambios):
    base = dict(
        fecha_emision=date(2026, 1, 1),
        tipo_comprobante=ca.FACTURA,
        ruc="1234567890001",
        ambiente=ca.AMBIENTE_PRUEBAS,
        establecimiento="001",
        punto_emision="001",
        secuencial=1,
        codigo_numerico="12345678",
    )
    base.update(cambios)
    try:
        ca.generar(**base)
    except ca.ErrorClaveAcceso:
        revisar(etiqueta, True)
    else:
        revisar(etiqueta, False, "no levanto ErrorClaveAcceso")


rechaza("un RUC de 10 digitos (cedula)", ruc="1234567890")
rechaza("un RUC con letras", ruc="123456789000A")
rechaza("un ambiente que no existe", ambiente="3")
rechaza("un tipo de comprobante no contemplado", tipo_comprobante="07")
rechaza("secuencial 0", secuencial=0)
rechaza("secuencial de 10 digitos", secuencial=1234567890)
rechaza("un establecimiento de 4 digitos", establecimiento="0001")
rechaza("un codigo numerico de 9 digitos", codigo_numerico="123456789")

print("\nTODOS LOS DIGITOS VERIFICADORES APARECEN")
# Si el calculo de los casos 10 y 11 estuviera mal, algun digito
# faltaria o sobraria al recorrer muchos secuenciales.
vistos = set()
for n in range(1, 400):
    clave = ca.generar(
        fecha_emision=date(2026, 3, 10),
        tipo_comprobante=ca.FACTURA,
        ruc="1790012345001",
        ambiente=ca.AMBIENTE_PRODUCCION,
        establecimiento="001",
        punto_emision="002",
        secuencial=n,
        codigo_numerico="00000001",
    )
    revisar_silencioso = ca.verificar(clave)
    if not revisar_silencioso:
        fallas.append(f"la clave del secuencial {n} no se valida")
    vistos.add(clave[-1])

revisar("las 400 claves generadas se validan",
        not [f for f in fallas if "no se valida" in str(f)])
revisar("salen los 10 digitos posibles, de 0 a 9",
        vistos == set("0123456789"), f"salieron {sorted(vistos)}")

total = 35
print(f"\n{total} comprobaciones")
if fallas:
    print(f"{len(fallas)} FALLAS: " + ", ".join(str(f) for f in fallas))
    sys.exit(1)
print("TODO OK")
