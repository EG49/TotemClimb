"""Pruebas del XML de la factura electronica.

Lo que se comprueba no es "el XML tiene tales etiquetas", sino las
reglas aritmeticas que el SRI valida al recibirlo, que son las que
hacen rechazar un comprobante:

  - la suma de precioTotalSinImpuesto de los detalles tiene que dar
    exactamente totalSinImpuestos
  - la suma del IVA de los detalles tiene que dar el valor del
    totalImpuesto
  - totalSinImpuestos + IVA tiene que dar importeTotal

Esas tres se verifican sobre miles de facturas al azar, porque el
descuadre aparece en combinaciones especificas de centavos y no en el
caso simple.
"""

import random
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.sri import factura_xml as fx  # noqa: E402
from app.services.sri import clave_acceso as ca  # noqa: E402

IVA = Decimal("15")
fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


EMISOR = fx.Emisor(
    ruc="1790012345001",
    razon_social="TOTEM CLIMB GYM CIA LTDA",
    nombre_comercial="Totem Climb Gym",
    direccion_matriz="Av. Principal 123, Quito",
    direccion_establecimiento="Av. Principal 123, Quito",
    establecimiento="001",
    punto_emision="002",
    obligado_contabilidad=False,
    contribuyente_rimpe=True,
)

CATALOGO = {
    "MEM-SEN": ("Membresia Senior", Decimal("65.00")),
    "MEM-JUN": ("Membresia Junior", Decimal("65.00")),
    "SEN-3M": ("Senior 3 meses", Decimal("145.00")),
    "PASE-1": ("Pase del dia", Decimal("10.00")),
    "PASE-5": ("5 pases", Decimal("30.00")),
    "AGUA": ("Agua Cielo", Decimal("0.50")),
    "SPORADE": ("Sporade", Decimal("0.75")),
    "MAGNESIO": ("Cubo de magnesio", Decimal("5.00")),
}


def armar(lineas, comprador=None, metodo="EFECTIVO"):
    clave = ca.generar(
        fecha_emision=date(2026, 11, 16),
        tipo_comprobante=ca.FACTURA,
        ruc=EMISOR.ruc,
        ambiente=ca.AMBIENTE_PRUEBAS,
        establecimiento=EMISOR.establecimiento,
        punto_emision=EMISOR.punto_emision,
        secuencial=7,
        codigo_numerico="12345678",
    )
    return fx.generar(
        emisor=EMISOR,
        comprador=comprador or fx.Comprador(),
        lineas=lineas,
        clave_acceso=clave,
        secuencial=7,
        fecha_emision=date(2026, 11, 16),
        iva_porcentaje=IVA,
        ambiente=ca.AMBIENTE_PRUEBAS,
        metodo_pago=metodo,
    )


def dec(raiz, ruta):
    return Decimal(raiz.find(ruta).text)


def cuadra(xml):
    """Las tres reglas de suma del SRI. Devuelve el motivo o None."""
    r = ET.fromstring(xml)
    sin_imp = dec(r, "infoFactura/totalSinImpuestos")
    total = dec(r, "infoFactura/importeTotal")
    iva = dec(r, "infoFactura/totalConImpuestos/totalImpuesto/valor")
    base_t = dec(r, "infoFactura/totalConImpuestos/totalImpuesto/baseImponible")

    suma_bases = sum(Decimal(d.find("precioTotalSinImpuesto").text)
                     for d in r.findall("detalles/detalle"))
    suma_iva = sum(Decimal(d.find("impuestos/impuesto/valor").text)
                   for d in r.findall("detalles/detalle"))

    if suma_bases != sin_imp:
        return f"detalles suman {suma_bases}, totalSinImpuestos {sin_imp}"
    if suma_iva != iva:
        return f"IVA de detalles {suma_iva}, totalImpuesto {iva}"
    if sin_imp + iva != total:
        return f"{sin_imp} + {iva} != {total}"
    if base_t != sin_imp:
        return f"baseImponible {base_t} != totalSinImpuestos {sin_imp}"
    return None


print("\nUNA MEMBRESIA SENIOR, EL CASO DE TODOS LOS DIAS")
xml = armar([fx.LineaXML("MEM-SEN", "Membresia Senior", 1, Decimal("65.00"))])
r = ET.fromstring(xml)
revisar("la version del esquema es 2.1.0", r.get("version") == "2.1.0", r.get("version"))
revisar("el codigo de documento es 01 (factura)",
        r.findtext("infoTributaria/codDoc") == "01")
revisar("el codigo de tarifa del IVA 15% es 4",
        r.findtext("infoFactura/totalConImpuestos/totalImpuesto/codigoPorcentaje") == "4",
        r.findtext("infoFactura/totalConImpuestos/totalImpuesto/codigoPorcentaje"))
revisar("totalSinImpuestos es 56.52",
        r.findtext("infoFactura/totalSinImpuestos") == "56.52",
        r.findtext("infoFactura/totalSinImpuestos"))
revisar("el IVA es 8.48",
        r.findtext("infoFactura/totalConImpuestos/totalImpuesto/valor") == "8.48")
revisar("importeTotal es 65.00",
        r.findtext("infoFactura/importeTotal") == "65.00",
        r.findtext("infoFactura/importeTotal"))
revisar("la fecha va dd/mm/aaaa",
        r.findtext("infoFactura/fechaEmision") == "16/11/2026",
        r.findtext("infoFactura/fechaEmision"))
revisar("el secuencial va con 9 digitos",
        r.findtext("infoTributaria/secuencial") == "000000007",
        r.findtext("infoTributaria/secuencial"))
revisar("lleva la leyenda del RIMPE",
        r.findtext("infoTributaria/contribuyenteRimpe") == fx.LEYENDA_RIMPE)
revisar("la moneda es DOLAR", r.findtext("infoFactura/moneda") == "DOLAR")
revisar("cuadra", cuadra(xml) is None, cuadra(xml))

print("\nEL CASO QUE DESCUADRA SI SE CALCULA LINEA POR LINEA")
xml = armar([fx.LineaXML("PASE-1", "Pase del dia", 3, Decimal("10.00"))])
r = ET.fromstring(xml)
revisar("tres pases de $10: totalSinImpuestos 26.09",
        r.findtext("infoFactura/totalSinImpuestos") == "26.09",
        r.findtext("infoFactura/totalSinImpuestos"))
revisar("y cuadra", cuadra(xml) is None, cuadra(xml))

xml = armar([fx.LineaXML("PASE-1", "Pase del dia", 1, Decimal("10.00")),
             fx.LineaXML("PASE-1b", "Pase del dia", 1, Decimal("10.00")),
             fx.LineaXML("PASE-1c", "Pase del dia", 1, Decimal("10.00"))])
revisar("tres lineas separadas de $10 tambien cuadran",
        cuadra(xml) is None, cuadra(xml))

print("\nCONSUMIDOR FINAL")
xml = armar([fx.LineaXML("AGUA", "Agua Cielo", 1, Decimal("0.50"))])
r = ET.fromstring(xml)
revisar("sin identificacion se emite a consumidor final",
        r.findtext("infoFactura/tipoIdentificacionComprador") == "07")
revisar("la identificacion es 9999999999999",
        r.findtext("infoFactura/identificacionComprador") == "9999999999999")
revisar("el nombre es CONSUMIDOR FINAL",
        r.findtext("infoFactura/razonSocialComprador") == "CONSUMIDOR FINAL")
revisar("un agua de $0.50 cuadra", cuadra(xml) is None, cuadra(xml))

print("\nTIPO DE IDENTIFICACION DEL COMPRADOR")
casos = [("1712345678", "05", "cedula de 10 digitos"),
         ("1790012345001", "04", "RUC de 13 digitos"),
         ("AB123456", "06", "pasaporte")]
for ident, esperado, etiqueta in casos:
    c = fx.Comprador(identificacion=ident, nombre="Cliente de Prueba")
    revisar(f"{etiqueta} va como {esperado}",
            c.tipo_identificacion == esperado, c.tipo_identificacion)

print("\nCORREO Y RUC DEL PROVEEDOR EN infoAdicional")
xml = armar([fx.LineaXML("MEM-SEN", "Membresia Senior", 1, Decimal("65.00"))],
            comprador=fx.Comprador(identificacion="1712345678",
                                   nombre="Cliente de Prueba",
                                   correo="cliente@ejemplo.com"))
r = ET.fromstring(xml)
campos = {c.get("nombre"): c.text for c in r.findall("infoAdicional/campoAdicional")}
revisar("el correo va en infoAdicional", campos.get("Email") == "cliente@ejemplo.com")
revisar("sin RUC de proveedor configurado, el campo no aparece",
        "RUC Proveedor" not in campos, str(list(campos)))

EMISOR.ruc_proveedor_sistema = "1790012345001"
xml = armar([fx.LineaXML("MEM-SEN", "Membresia Senior", 1, Decimal("65.00"))])
campos = {c.get("nombre"): c.text
          for c in ET.fromstring(xml).findall("infoAdicional/campoAdicional")}
revisar("configurado, el campo se llama exactamente 'RUC Proveedor'",
        campos.get("RUC Proveedor") == "1790012345001", str(list(campos)))
EMISOR.ruc_proveedor_sistema = None

print("\nFORMA DE PAGO")
for metodo, esperado in (("EFECTIVO", "01"), ("TRANSFERENCIA", "20")):
    xml = armar([fx.LineaXML("MEM-SEN", "Membresia", 1, Decimal("65.00"))],
                metodo=metodo)
    revisar(f"{metodo} va como {esperado}",
            ET.fromstring(xml).findtext("infoFactura/pagos/pago/formaPago") == esperado)

print("\nDESCUENTO")
xml = armar([fx.LineaXML("MEM-JUN", "Membresia Junior", 1, Decimal("65.00"),
                         descuento_con_iva=Decimal("13.00"))])
r = ET.fromstring(xml)
revisar("el total baja a 52.00", r.findtext("infoFactura/importeTotal") == "52.00",
        r.findtext("infoFactura/importeTotal"))
revisar("totalDescuento queda registrado",
        r.findtext("infoFactura/totalDescuento") == "13.00",
        r.findtext("infoFactura/totalDescuento"))
revisar("con descuento tambien cuadra", cuadra(xml) is None, cuadra(xml))

print("\nIMPORTES SIEMPRE CON DOS DECIMALES")
xml = armar([fx.LineaXML("MEM-SEN", "Membresia", 1, Decimal("65.00"))])
r = ET.fromstring(xml)
sospechosos = [n.tag for n in r.iter()
               if n.tag in ("propina", "totalDescuento", "descuento")
               and n.text in ("0", "0.0")]
revisar("los ceros se escriben 0.00", not sospechosos, str(sospechosos))
revisar("la propina es 0.00", r.findtext("infoFactura/propina") == "0.00",
        r.findtext("infoFactura/propina"))

print("\nDATOS QUE NO SIRVEN SE RECHAZAN")


def rechaza(etiqueta, hacer):
    try:
        hacer()
    except fx.ErrorFacturaXML:
        revisar(etiqueta, True)
    else:
        revisar(etiqueta, False, "no levanto ErrorFacturaXML")


rechaza("una factura sin lineas", lambda: armar([]))
rechaza("un comprador con cedula pero sin nombre",
        lambda: armar([fx.LineaXML("A", "x", 1, Decimal("1.00"))],
                      comprador=fx.Comprador(identificacion="1712345678")))
rechaza("una identificacion de largo raro",
        lambda: fx.Comprador(identificacion="12345",
                             nombre="X").tipo_identificacion)
rechaza("un metodo de pago desconocido",
        lambda: armar([fx.LineaXML("A", "x", 1, Decimal("1.00"))],
                      metodo="CRIPTO"))

malo = fx.Emisor(ruc="123", razon_social="X", direccion_matriz="Y",
                 direccion_establecimiento="Z", establecimiento="001",
                 punto_emision="001")
rechaza("un RUC de emisor invalido", malo.validar)
sin_razon = fx.Emisor(ruc="1790012345001", razon_social="  ",
                      direccion_matriz="Y", direccion_establecimiento="Z",
                      establecimiento="001", punto_emision="001")
rechaza("un emisor sin razon social", sin_razon.validar)


def iva_raro():
    return fx.generar(emisor=EMISOR, comprador=fx.Comprador(),
                      lineas=[fx.LineaXML("A", "x", 1, Decimal("1.00"))],
                      clave_acceso="0" * 49, secuencial=1,
                      fecha_emision=date(2026, 1, 1),
                      iva_porcentaje=Decimal("13"), ambiente="1",
                      metodo_pago="EFECTIVO")


rechaza("un IVA sin codigo de tarifa (13%)", iva_raro)

print("\nAL AZAR: 5000 FACTURAS DEL CATALOGO REAL")
random.seed(23)
codigos = list(CATALOGO)
descuadres = []
for _ in range(5000):
    lineas = []
    for _ in range(random.randint(1, 6)):
        cod = random.choice(codigos)
        nombre, precio = CATALOGO[cod]
        lineas.append(fx.LineaXML(cod, nombre, random.randint(1, 5), precio))
    motivo = cuadra(armar(lineas))
    if motivo:
        descuadres.append(motivo)
revisar("las 5000 cuadran contra las tres reglas del SRI",
        not descuadres, f"{len(descuadres)} descuadres, p.ej. {descuadres[:2]}")

print("\nEL XML SE PARSEA Y NO TRAE SORPRESAS")
xml = armar([fx.LineaXML("MEM-SEN", "Membresia Senior & Pase", 1, Decimal("65.00"))])
revisar("un & en la descripcion no rompe el XML", ET.fromstring(xml) is not None)
revisar("declara la codificacion UTF-8", xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))

total = 46
print(f"\n{total} comprobaciones")
if fallas:
    print(f"{len(fallas)} FALLAS: " + ", ".join(fallas))
    sys.exit(1)
print("TODO OK")
