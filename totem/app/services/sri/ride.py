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
from pathlib import Path
from xml.etree import ElementTree as ET

AMBIENTE_PRUEBAS = "PRUEBAS"

# El fondo de la pastilla del logo. Ver donde se la dibuja.
COLOR_PASTILLA = (0.125, 0.172, 0.204)

# Blanco entre la pastilla del logo y el nombre del emisor.
ESPACIO_BAJO_EL_LOGO = 17  # puntos, algo menos de 6 mm

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

    # Marca al documento que NO es una factura, sino el comprobante
    # interno de una venta que el SRI todavía no autorizó o rechazó.
    es_interno: bool = False

    @property
    def es_prueba(self) -> bool:
        return self.ambiente.strip().upper() == AMBIENTE_PRUEBAS

    # ─── Lo que distingue a los dos documentos ───────────────────
    # Juntas acá a propósito: el resto del dibujo es idéntico, y ese
    # es el punto. Si se separaran en dos funciones, con el tiempo
    # dejarían de parecerse.

    @property
    def sin_validez(self) -> bool:
        """Si hay que avisar que este papel no vale ante el SRI."""
        return self.es_interno or self.es_prueba

    @property
    def titulo(self) -> str:
        return "COMPROBANTE INTERNO" if self.es_interno else "FACTURA"

    @property
    def marca_de_agua(self) -> str:
        if self.es_interno:
            return "SIN VALIDEZ TRIBUTARIA"
        return "SIN VALIDEZ TRIBUTARIA"

    @property
    def aviso_pie(self) -> str:
        if self.es_interno:
            return ("DOCUMENTO INTERNO DE CONTROL — NO ES UN COMPROBANTE "
                    "DE VENTA AUTORIZADO POR EL SRI")
        return ("COMPROBANTE EMITIDO EN EL AMBIENTE DE PRUEBAS — "
                "SIN VALIDEZ TRIBUTARIA")

    @property
    def leyenda_pie(self) -> str:
        if self.es_interno:
            return ("Comprobante de la venta para control del gimnasio. "
                    "La factura electrónica se entrega aparte cuando el "
                    "SRI la autoriza.")
        return ("Este documento es la representación impresa de un "
                "comprobante electrónico y tiene la misma validez. "
                "Verifíquelo en www.sri.gob.ec con la clave de acceso.")


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


def _ruta_logo():
    """El logo del gimnasio, si está donde se lo espera.

    Se lo busca por ruta y no se lo exige: que falte el archivo no
    puede impedir emitir una factura.
    """
    ruta = (
        Path(__file__).resolve().parents[2] / "static" / "img" / "totem-logo.png"
    )
    return ruta if ruta.exists() else None


def _fecha_legible(texto: str) -> str:
    """La fecha del SRI viene en ISO; se muestra como se lee acá."""
    try:
        momento = datetime.fromisoformat(texto)
    except ValueError:
        return texto
    return momento.strftime("%d/%m/%Y %H:%M:%S")


def _partir_ancho(pdf, texto: str, ancho_max: float, fuente: str,
                  tamano: float) -> list[str]:
    """Corta el texto midiendolo, no contando caracteres.

    Contar caracteres no sirve: "GAIBOR ENCALADA EVANS ALEJANDRO" en
    negrita de 11 puntos entra en 34 caracteres pero se monta encima
    de la columna de la derecha.
    """
    palabras = (texto or "").split()
    lineas: list[str] = []
    actual = ""
    for palabra in palabras:
        tentativa = f"{actual} {palabra}".strip()
        if pdf.stringWidth(tentativa, fuente, tamano) > ancho_max and actual:
            lineas.append(actual)
            actual = palabra
        else:
            actual = tentativa
    if actual:
        lineas.append(actual)
    return lineas or [""]


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

    # ─── Marca de agua, antes que nada ─────────────────────────────
    if autorizacion.sin_validez:
        pdf.saveState()
        pdf.setFillGray(0.85)
        pdf.setFont("Helvetica-Bold", 60)
        # Mas abajo que el centro: arriba cruzaria el codigo de
        # barras y podria estorbar al escanearlo.
        pdf.translate(ancho / 2, alto * 0.32)
        pdf.rotate(45)
        pdf.drawCentredString(0, 0, autorizacion.marca_de_agua)
        pdf.restoreState()

    # ─── Emisor, con el logo si está ───────────────────────────────
    mitad = (ancho - 2 * margen) / 2 - 4 * mm
    arriba = y

    # El logo va arriba y el texto debajo, no al lado: puesto al lado
    # la razon social se monta sobre la columna de la derecha.
    logo = _ruta_logo()
    if logo is not None:
        try:
            from reportlab.lib.utils import ImageReader

            imagen = ImageReader(str(logo))
            ancho_px, alto_px = imagen.getSize()
            alto_logo = 20 * mm
            ancho_logo = alto_logo * ancho_px / alto_px

            # Una pastilla oscura detras del logo. No es decoracion:
            # en el archivo el oso y la palabra TOTEM son blancos
            # sobre fondo transparente, asi que sobre el papel blanco
            # se pierden y solo queda el aro turquesa.
            relleno = 3 * mm
            pdf.saveState()
            pdf.setFillColorRGB(*COLOR_PASTILLA)
            pdf.roundRect(
                margen, y - alto_logo - relleno,
                ancho_logo + 2 * relleno, alto_logo + 2 * relleno,
                2.5 * mm, stroke=0, fill=1,
            )
            pdf.restoreState()
            pdf.drawImage(
                imagen, margen + relleno, y - alto_logo,
                width=ancho_logo, height=alto_logo,
                mask="auto",  # respeta la transparencia del PNG
            )
            # El desplazamiento se mide hasta la LINEA BASE del
            # texto, no hasta donde el texto empieza a dibujarse, asi
            # que hay que sumarle el alto de las mayusculas: si no,
            # el nombre queda pegado a la pastilla.
            from reportlab.pdfbase.pdfmetrics import getAscent

            alto_mayusculas = getAscent("Helvetica-Bold", 11)
            y -= (
                alto_logo + relleno + ESPACIO_BAJO_EL_LOGO + alto_mayusculas
            )
        except Exception:  # noqa: BLE001
            # Un logo que no se puede dibujar no es motivo para dejar
            # al cliente sin su factura.
            pass

    pdf.setFont("Helvetica-Bold", 11)
    for linea in _partir_ancho(pdf, t(trib, "razonSocial"), mitad,
                               "Helvetica-Bold", 11):
        pdf.drawString(margen, y, linea)
        y -= 13
    if t(trib, "nombreComercial"):
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margen, y, t(trib, "nombreComercial"))
        y -= 12

    y -= 2
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
        for linea in _partir_ancho(pdf, dato, mitad, "Helvetica", 8):
            pdf.drawString(margen, y, linea)
            y -= 10

    # ─── Cuadro de la derecha: el comprobante y su autorización ────
    x = margen + mitad + 8 * mm
    yd = arriba
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(x, yd, autorizacion.titulo)
    yd -= 16

    # El comprobante interno no tiene establecimiento ni punto de
    # emisión: lleva solo su número interno. Sin esto salía "--F-0001",
    # con los guiones del formato del SRI y nada en medio.
    numero = "-".join(
        parte for parte in (t(trib, "estab", ""), t(trib, "ptoEmi", ""),
                            t(trib, "secuencial", ""))
        if parte
    )
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(x, yd, f"No. {numero}")
    yd -= 14

    if autorizacion.es_interno:
        # Un documento interno NO lleva número de autorización ni
        # clave de acceso: no los tiene. Poner los rótulos vacíos
        # sería peor que no ponerlos, porque invita a confundirlo
        # con una factura a la que simplemente le falta un dato.
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawString(x, yd, "EMITIDO")
        pdf.setFont("Helvetica", 7)
        pdf.drawString(x + 55, yd, t(info, "fechaEmision"))
        yd -= 24

        pdf.saveState()
        pdf.setFillColorRGB(0.42, 0.11, 0.11)
        pdf.setFont("Helvetica-Bold", 8)
        for linea in ("NO ES UN COMPROBANTE DE VENTA",
                      "AUTORIZADO POR EL SRI"):
            pdf.drawString(x, yd, linea)
            yd -= 10
        pdf.restoreState()
        yd -= 6
    else:
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

    # La identificación solo si la hay: en el comprobante interno no
    # existe, y un rótulo con el espacio en blanco al lado parece un
    # dato que falta.
    identificacion = t(info, "identificacionComprador", "")
    if identificacion:
        tipo = t(info, "tipoIdentificacionComprador")
        pdf.setFont("Helvetica-Bold", 7.5)
        pdf.drawString(
            margen + 4, y - 22,
            f"{ETIQUETA_IDENTIFICACION.get(tipo, 'Identificación')}:",
        )
        pdf.setFont("Helvetica", 7.5)
        pdf.drawString(margen + 150, y - 22, identificacion)

    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(margen + 300, y - 22, "Fecha de emisión:")
    pdf.setFont("Helvetica", 7.5)
    pdf.drawString(margen + 390, y - 22, t(info, "fechaEmision"))
    y -= 46

    # ─── Detalle, como tabla ───────────────────────────────────────
    # Se arma con Table y no dibujando a mano: el relleno de las
    # celdas, el alto de las filas y las lineas quedan parejos solos.
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    encabezados = ["Cód.", "Descripción", "Cant.", "P. unit.", "Dcto.", "Total"]
    filas = [encabezados]
    for detalle in factura.findall("detalles/detalle"):
        filas.append([
            t(detalle, "codigoPrincipal"),
            "\n".join(_partir(t(detalle, "descripcion"), 44)),
            t(detalle, "cantidad"),
            t(detalle, "precioUnitario"),
            t(detalle, "descuento"),
            t(detalle, "precioTotalSinImpuesto"),
        ])

    anchos = [60, 215, 45, 55, 50, 60]
    sobra = (ancho - 2 * margen) - sum(anchos)
    anchos[1] += sobra  # la descripcion se queda con lo que sobre

    tabla = Table(filas, colWidths=anchos, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eceff1")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        # Relleno: es lo que faltaba. Sin esto el texto queda pegado
        # al borde del sombreado y se lee apretado.
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#90a4ae")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f7f9fa")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cfd8dc")),
    ]))

    ancho_tabla, alto_tabla = tabla.wrapOn(pdf, ancho - 2 * margen, alto)
    tabla.drawOn(pdf, margen, y - alto_tabla)
    y -= alto_tabla + 18

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
    if autorizacion.sin_validez:
        pdf.setFillGray(0)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawCentredString(ancho / 2, margen + 14, autorizacion.aviso_pie)
        pdf.setFont("Helvetica", 6.5)
        pdf.setFillGray(0.35)
    pdf.drawCentredString(ancho / 2, margen, autorizacion.leyenda_pie)

    pdf.showPage()
    pdf.save()
    return salida.getvalue()


def generar_desde_respuesta(respuesta_xml: str) -> tuple[bytes, Autorizacion]:
    """Atajo: del XML de respuesta del SRI al PDF."""
    autorizacion = leer_autorizacion(respuesta_xml)
    return generar(autorizacion), autorizacion


def comprobante_interno(factura, emisor: dict, iva_porcentaje) -> Autorizacion:
    """El comprobante de una venta que el SRI no autorizó (o todavía no).

    Arma la MISMA estructura que trae una autorización del SRI, para
    que la dibuje el mismo código. Es a propósito: si el documento
    interno se dibujara aparte, con el tiempo dejaría de parecerse al
    RIDE, y la idea es justamente que se lean igual.

    Lo que no lleva, porque no existe, es el número de autorización y
    la clave de acceso. En su lugar va el aviso de que no es un
    comprobante de venta autorizado.
    """
    from decimal import ROUND_HALF_UP, Decimal
    from xml.sax.saxutils import escape

    centavo = Decimal("0.01")
    total = Decimal(factura.total)
    iva = Decimal(iva_porcentaje)
    base = (total / (1 + iva / 100)).quantize(centavo, rounding=ROUND_HALF_UP)

    def nodo(etiqueta, valor):
        return f"<{etiqueta}>{escape(str(valor))}</{etiqueta}>"

    detalles = []
    for linea in factura.detalle or []:
        cantidad = int(linea.get("cantidad") or 1)
        unitario = Decimal(linea.get("precio_unitario") or 0)
        subtotal = Decimal(linea.get("subtotal") or 0)
        # Los importes del comprobante interno van CON IVA, que es lo
        # que el cliente pagó. No se separa la base por línea: eso es
        # cosa de la factura, y acá no hay factura.
        detalles.append(
            "<detalle>"
            + nodo("codigoPrincipal", linea.get("codigo") or "—")
            + nodo("descripcion", linea.get("nombre") or "")
            + nodo("cantidad", f"{cantidad:.2f}")
            + nodo("precioUnitario", f"{unitario:.2f}")
            + nodo("descuento", "0.00")
            + nodo("precioTotalSinImpuesto", f"{subtotal:.2f}")
            + "<impuestos><impuesto>"
            + nodo("codigo", "2") + nodo("codigoPorcentaje", "")
            + nodo("tarifa", f"{iva:.2f}")
            + nodo("baseImponible", f"{subtotal:.2f}")
            + nodo("valor", "0.00")
            + "</impuesto></impuestos></detalle>"
        )

    comprobante = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<factura id="comprobante" version="2.1.0"><infoTributaria>'
        + nodo("ambiente", "")
        + nodo("razonSocial", emisor.get("razon_social") or "TOTEM CLIMB GYM")
        + nodo("nombreComercial", emisor.get("nombre_comercial") or "")
        + nodo("ruc", emisor.get("ruc") or "")
        + nodo("estab", "") + nodo("ptoEmi", "")
        + nodo("secuencial", factura.numero_factura or "")
        + nodo("dirMatriz", emisor.get("direccion") or "")
        + "</infoTributaria><infoFactura>"
        + nodo("fechaEmision", factura.fecha.strftime("%d/%m/%Y"))
        + nodo("dirEstablecimiento", emisor.get("direccion") or "")
        + nodo("obligadoContabilidad", "NO")
        + nodo("tipoIdentificacionComprador", "")
        + nodo("razonSocialComprador", factura.cliente_nombre or "")
        + nodo("identificacionComprador", "")
        + nodo("totalSinImpuestos", f"{base:.2f}")
        + nodo("totalDescuento", "0.00")
        + "<totalConImpuestos><totalImpuesto>"
        + nodo("codigo", "2") + nodo("codigoPorcentaje", "")
        + nodo("baseImponible", f"{base:.2f}")
        + nodo("valor", f"{total - base:.2f}")
        + "</totalImpuesto></totalConImpuestos>"
        + nodo("propina", "0.00")
        + nodo("importeTotal", f"{total:.2f}")
        + nodo("moneda", "DOLAR")
        + "<pagos><pago>"
        + nodo("formaPago", "01") + nodo("total", f"{total:.2f}")
        + "</pago></pagos></infoFactura><detalles>"
        + "".join(detalles)
        + "</detalles></factura>"
    )

    return Autorizacion(
        estado="INTERNO",
        numero="",
        fecha="",
        ambiente="",
        comprobante=comprobante,
        es_interno=True,
    )
