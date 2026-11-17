"""RIDE: la representación impresa del comprobante electrónico.

El XML es la factura ante el SRI; el RIDE es la versión que se lee y
se le entrega al cliente, y tiene la misma validez. Lleva la clave de
acceso de 49 dígitos, también como código de barras, el número de
autorización y la fecha y hora en que el SRI autorizó.

Dos cosas que importan acá:

1. El RIDE se arma desde el XML ya AUTORIZADO, no desde los datos del
   sistema. Si se lo armara aparte, podría mostrar un total distinto
   del que el SRI autorizó, y entonces el papel que recibe el cliente
   y la factura ante el SRI dirían cosas diferentes. Lo que se
   imprime sale del comprobante autorizado y de nada más.

2. Un RIDE del ambiente de PRUEBAS sale con una marca de agua y un
   aviso bien visibles. Esos comprobantes no tienen validez
   tributaria, y un PDF de prueba que parece real termina en las
   manos de un cliente o en la contabilidad.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from xml.etree import ElementTree as ET

AMBIENTE_PRUEBAS = "PRUEBAS"

ETIQUETA_IDENTIFICACION = {
    "04": "RUC",
    "05": "Cédula",
    "06": "Pasaporte",
    "07": "Consumidor final",
}

ETIQUETA_PAGO = {
    "01": "Sin utilización del sistema financiero",
    "15": "Compensación de deudas",
    "16": "Tarjeta de débito",
    "17": "Dinero electrónico",
    "18": "Tarjeta prepago",
    "19": "Tarjeta de crédito",
    "20": "Otros con utilización del sistema financiero",
    "21": "Endoso de títulos",
}


class ErrorRide(ValueError):
    """No se pudo armar el RIDE."""


@dataclass
class Autorizacion:
    """Lo que respondió el SRI. Sin esto no hay RIDE que valga."""

    estado: str
    numero: str
    fecha: str
    ambiente: str
    comprobante: str

    @property
    def es_prueba(self) -> bool:
        return self.ambiente.strip().upper() == AMBIENTE_PRUEBAS


def leer_autorizacion(respuesta_xml: str) -> Autorizacion:
    """Saca del XML de respuesta del SRI lo necesario para el RIDE.

    `respuesta_xml` es el sobre SOAP que devuelve el servicio de
    autorización, tal como lo guardan los scripts.
    """
    try:
        raiz = ET.fromstring(respuesta_xml.encode("utf-8")
                             if isinstance(respuesta_xml, str)
                             else respuesta_xml)
    except ET.ParseError as error:
        raise ErrorRide(f"la respuesta del SRI no es XML: {error}") from error

    nodo = next(raiz.iter("autorizacion"), None)
    if nodo is None:
        raise ErrorRide(
            "la respuesta no trae ninguna autorización: el SRI no tiene "
            "ese comprobante"
        )

    estado = (nodo.findtext("estado") or "").strip()
    if estado.upper() != "AUTORIZADO":
        mensajes = []
        for mensaje in nodo.iter("mensaje"):
            texto = " ".join(
                parte.strip()
                for etiqueta in ("identificador", "mensaje",
                                 "informacionAdicional")
                if (parte := mensaje.findtext(etiqueta))
            )
            if texto:
                mensajes.append(texto)
        detalle = ("; ".join(mensajes)) if mensajes else "sin mensajes"
        raise ErrorRide(
            f"el comprobante está {estado or 'sin estado'}, no autorizado. "
            f"No se le puede entregar un RIDE al cliente. SRI dice: {detalle}"
        )

    comprobante = nodo.findtext("comprobante") or ""
    if not comprobante.strip():
        raise ErrorRide("la autorización no trae el comprobante dentro")

    return Autorizacion(
        estado=estado,
        numero=(nodo.findtext("numeroAutorizacion") or "").strip(),
        fecha=(nodo.findtext("fechaAutorizacion") or "").strip(),
        ambiente=(nodo.findtext("ambiente") or "").strip(),
        comprobante=comprobante,
    )


def _fecha_legible(texto: str) -> str:
    """La fecha del SRI viene en ISO; se muestra como se lee acá."""
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError:
        return texto
    return momento.strftime("%d/%m/%Y %H:%M:%S")


def _partir(texto: str, ancho: int) -> list[str]:
    """Corta un texto en líneas de a lo sumo `ancho` caracteres."""
    palabras = (texto or "").split()
    lineas: list[str] = []
    actual = ""
    for palabra in palabras:
        if len(actual) + len(palabra) + 1 > ancho:
            if actual:
                lineas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}".strip()
    if actual:
        lineas.append(actual)
    return lineas or [""]


def generar(autorizacion: Autorizacion) -> bytes:
    """Devuelve el PDF del RIDE a partir de la autorización del SRI."""
    try:
        from reportlab.graphics.barcode import code128
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError as error:
        raise ErrorRide(
            "falta reportlab. Instálelo con:\n  pip install -r requirements.txt"
        ) from error

    factura = ET.fromstring(autorizacion.comprobante.encode("utf-8"))
    trib = factura.find("infoTributaria")
    info = factura.find("infoFactura")
    if trib is None or info is None:
        raise ErrorRide("el comprobante autorizado no tiene la forma esperada")

    def t(nodo, etiqueta, por_omision=""):
        valor = nodo.findtext(etiqueta) if nodo is not None else None
        return (valor or por_omision).strip()

    salida = BytesIO()
    pdf = rl_canvas.Canvas(salida, pagesize=A4)
    ancho, alto = A4
    pdf.setTitle(f"Factura {t(trib, 'claveAcceso')}")

    margen = 15 * mm
    y = alto - margen

    # ─── Marca de prueba, antes que nada ───────────────────────────
    if autorizacion.es_prueba:
        pdf.saveState()
        pdf.setFillGray(0.85)
        pdf.setFont("Helvetica-Bold", 60)
        pdf.translate(ancho / 2, alto / 2)
        pdf.rotate(45)
        pdf.drawCentredString(0, 0, "SIN VALIDEZ TRIBUTARIA")
        pdf.restoreState()

    # ─── Emisor ────────────────────────────────────────────────────
    mitad = (ancho - 2 * margen) / 2 - 4 * mm
    arriba = y

    pdf.setFont("Helvetica-Bold", 11)
    for linea in _partir(t(trib, "razonSocial"), 42):
        pdf.drawString(margen, y, linea)
        y -= 13
    if t(trib, "nombreComercial"):
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margen, y, t(trib, "nombreComercial"))
        y -= 12

    pdf.setFont("Helvetica", 8)
    datos_emisor = [
        f"RUC: {t(trib, 'ruc')}",
        f"Dirección matriz: {t(trib, 'dirMatriz')}",
        f"Dirección sucursal: {t(info, 'dirEstablecimiento')}",
        f"Obligado a llevar contabilidad: {t(info, 'obligadoContabilidad')}",
    ]
    if t(trib, "contribuyenteRimpe"):
        datos_emisor.append(t(trib, "contribuyenteRimpe"))
    for dato in datos_emisor:
        for linea in _partir(dato, 60):
            pdf.drawString(margen, y, linea)
            y -= 10

    # ─── Cuadro de la derecha: el comprobante y su autorización ────
    x = margen + mitad + 8 * mm
    yd = arriba
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(x, yd, "FACTURA")
    yd -= 16

    numero = (
        f"{t(trib, 'estab')}-{t(trib, 'ptoEmi')}-{t(trib, 'secuencial')}"
    )
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(x, yd, f"No. {numero}")
    yd -= 14

    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(x, yd, "NÚMERO DE AUTORIZACIÓN")
    yd -= 9
    pdf.setFont("Helvetica", 6.5)
    for linea in _partir(autorizacion.numero, 40):
        pdf.drawString(x, yd, linea)
        yd -= 8

    yd -= 2
    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(x, yd, "FECHA Y HORA DE AUTORIZACIÓN")
    yd -= 9
    pdf.setFont("Helvetica", 7)
    pdf.drawString(x, yd, _fecha_legible(autorizacion.fecha))
    yd -= 11

    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(x, yd, "AMBIENTE")
    pdf.setFont("Helvetica", 7)
    pdf.drawString(x + 55, yd, autorizacion.ambiente)
    yd -= 10
    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(x, yd, "EMISIÓN")
    pdf.setFont("Helvetica", 7)
    pdf.drawString(x + 55, yd, "NORMAL")
    yd -= 12

    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(x, yd, "CLAVE DE ACCESO")
    yd -= 22

    clave = t(trib, "claveAcceso")
    barras = code128.Code128(
        clave, barHeight=12 * mm, barWidth=0.33, humanReadable=False
    )
    barras.drawOn(pdf, x, yd - 12 * mm + 10)
    yd -= 12 * mm
    pdf.setFont("Helvetica", 6)
    pdf.drawString(x, yd - 2, clave)

    y = min(y, yd) - 16

    # ─── Comprador ─────────────────────────────────────────────────
    pdf.setStrokeGray(0.6)
    pdf.rect(margen, y - 34, ancho - 2 * margen, 34)
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(margen + 4, y - 11, "Razón social / Nombres y apellidos:")
    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(margen + 150, y - 11, t(info, "razonSocialComprador"))

    tipo = t(info, "tipoIdentificacionComprador")
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(margen + 4, y - 22,
                   f"{ETIQUETA_IDENTIFICACION.get(tipo, 'Identificación')}:")
    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(margen + 150, y - 22, t(info, "identificacionComprador"))

    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(margen + 300, y - 22, "Fecha de emisión:")
    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(margen + 390, y - 22, t(info, "fechaEmision"))
    y -= 46

    # ─── Detalle ───────────────────────────────────────────────────
    columnas = (
        ("Cód.", margen + 4, 55),
        ("Descripción", margen + 62, 230),
        ("Cant.", margen + 300, 40),
        ("P. unit.", margen + 348, 50),
        ("Dcto.", margen + 404, 45),
        ("Total", margen + 455, 55),
    )
    pdf.setFillGray(0.92)
    pdf.rect(margen, y - 13, ancho - 2 * margen, 13, stroke=0, fill=1)
    pdf.setFillGray(0)
    pdf.setFont("Helvetica-Bold", 7.5)
    for titulo, cx, _ in columnas:
        pdf.drawString(cx, y - 9, titulo)
    y -= 15

    pdf.setFont("Helvetica", 7.5)
    for detalle in factura.findall("detalles/detalle"):
        descripciones = _partir(t(detalle, "descripcion"), 48)
        pdf.drawString(columnas[0][1], y, t(detalle, "codigoPrincipal"))
        pdf.drawString(columnas[1][1], y, descripciones[0])
        pdf.drawRightString(columnas[2][1] + 30, y, t(detalle, "cantidad"))
        pdf.drawRightString(columnas[3][1] + 42, y, t(detalle, "precioUnitario"))
        pdf.drawRightString(columnas[4][1] + 36, y, t(detalle, "descuento"))
        pdf.drawRightString(columnas[5][1] + 46, y,
                            t(detalle, "precioTotalSinImpuesto"))
        y -= 10
        for extra in descripciones[1:]:
            pdf.drawString(columnas[1][1], y, extra)
            y -= 10
        y -= 2

    y -= 6
    pdf.setStrokeGray(0.6)
    pdf.line(margen, y, ancho - margen, y)
    y -= 16

    # ─── Totales ───────────────────────────────────────────────────
    impuesto = factura.find("infoFactura/totalConImpuestos/totalImpuesto")
    tarifa = ""
    for nodo in factura.findall("detalles/detalle/impuestos/impuesto"):
        tarifa = t(nodo, "tarifa")
        break
    try:
        tarifa_texto = f"{Decimal(tarifa).normalize():f}%" if tarifa else ""
    except Exception:  # noqa: BLE001
        tarifa_texto = f"{tarifa}%"

    filas = [
        ("SUBTOTAL SIN IMPUESTOS", t(info, "totalSinImpuestos")),
        ("DESCUENTO", t(info, "totalDescuento")),
        (f"IVA {tarifa_texto}".strip(), t(impuesto, "valor")),
        ("PROPINA", t(info, "propina")),
    ]
    izquierda = ancho - margen - 200
    pdf.setFont("Helvetica", 8)
    for etiqueta, valor in filas:
        pdf.drawString(izquierda, y, etiqueta)
        pdf.drawRightString(ancho - margen - 4, y, f"$ {valor}")
        y -= 11

    y -= 2
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(izquierda, y, "VALOR TOTAL")
    pdf.drawRightString(ancho - margen - 4, y, f"$ {t(info, 'importeTotal')}")
    y -= 20

    # ─── Forma de pago ─────────────────────────────────────────────
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(margen, y, "Forma de pago")
    y -= 10
    pdf.setFont("Helvetica", 7.5)
    for pago in factura.findall("infoFactura/pagos/pago"):
        codigo = t(pago, "formaPago")
        pdf.drawString(
            margen, y,
            f"{ETIQUETA_PAGO.get(codigo, codigo)} — $ {t(pago, 'total')}"
        )
        y -= 10

    # ─── Información adicional ─────────────────────────────────────
    adicionales = factura.findall("infoAdicional/campoAdicional")
    if adicionales:
        y -= 6
        pdf.setFont("Helvetica-Bold", 7.5)
        pdf.drawString(margen, y, "Información adicional")
        y -= 10
        pdf.setFont("Helvetica", 7.5)
        for campo in adicionales:
            pdf.drawString(
                margen, y,
                f"{campo.get('nombre', '')}: {(campo.text or '').strip()}"
            )
            y -= 10

    # ─── Pie ───────────────────────────────────────────────────────
    pdf.setFont("Helvetica", 6.5)
    pdf.setFillGray(0.35)
    if autorizacion.es_prueba:
        pdf.setFillGray(0)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawCentredString(
            ancho / 2, margen + 14,
            "COMPROBANTE EMITIDO EN EL AMBIENTE DE PRUEBAS — "
            "SIN VALIDEZ TRIBUTARIA"
        )
        pdf.setFont("Helvetica", 6.5)
        pdf.setFillGray(0.35)
    pdf.drawCentredString(
        ancho / 2, margen,
        "Este documento es la representación impresa de un comprobante "
        "electrónico y tiene la misma validez. "
        "Verifíquelo en www.sri.gob.ec con la clave de acceso."
    )

    pdf.showPage()
    pdf.save()
    return salida.getvalue()


def generar_desde_respuesta(respuesta_xml: str) -> tuple[bytes, Autorizacion]:
    """Atajo: del XML de respuesta del SRI al PDF."""
    autorizacion = leer_autorizacion(respuesta_xml)
    return generar(autorizacion), autorizacion
