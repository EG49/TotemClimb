"""XML de la factura electrónica, versión 2.1.0 del esquema del SRI.

Esquema offline, ficha técnica 2.34 (julio de 2026).

Lo que hay que tener presente al tocar este archivo:

1. Nuestros precios INCLUYEN IVA; el XML los pide SIN IVA. La
   conversión y el reparto del centavo están en bases.py, no acá.

2. El código de tarifa del IVA 15% es el 4. La tabla oficial es
   0%→0, 12%→2, 14%→3, 15%→4, 5%→5. Hay páginas en internet que
   dicen que el 15% es el código 3: están equivocadas, el 3 es el
   14%, y usarlo hace rechazar la factura.

3. Desde el 26 de septiembre de 2026 el comprobante debe llevar en
   infoAdicional un campo llamado exactamente "RUC Proveedor" con el
   RUC de quien desarrolla el sistema (anexo 26 de la ficha 2.34).
   Para un sistema hecho para uso interno, sin comercializarlo, no
   está claro si corresponde; por eso es configurable y se omite si
   no se la define. Hay que confirmarlo con el contador.

4. Los importes van con dos decimales SIEMPRE, también cuando son
   cero: "0.00" y no "0". El SRI valida el formato.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from app.services.sri import bases
from app.services.sri.clave_acceso import FACTURA

CENTAVO = Decimal("0.01")

VERSION = "2.1.0"
COD_DOC_FACTURA = FACTURA

# Código del impuesto IVA (tabla de impuestos de la ficha técnica).
IMPUESTO_IVA = "2"

# Código de tarifa por porcentaje de IVA. Ver la nota 2 de arriba.
CODIGO_TARIFA = {
    Decimal("0"): "0",
    Decimal("12"): "2",
    Decimal("14"): "3",
    Decimal("15"): "4",
    Decimal("5"): "5",
}

# Tipo de identificación del comprador.
IDENT_RUC = "04"
IDENT_CEDULA = "05"
IDENT_PASAPORTE = "06"
IDENT_CONSUMIDOR_FINAL = "07"

CONSUMIDOR_FINAL_ID = "9999999999999"
CONSUMIDOR_FINAL_NOMBRE = "CONSUMIDOR FINAL"

# Forma de pago. El gimnasio cobra en efectivo o por transferencia;
# "por cobrar" se factura igual y el pago se registra después, así que
# usa el mismo código que el efectivo hasta que se cobre.
PAGO_SIN_SISTEMA_FINANCIERO = "01"
PAGO_CON_SISTEMA_FINANCIERO = "20"

FORMA_PAGO = {
    "EFECTIVO": PAGO_SIN_SISTEMA_FINANCIERO,
    "TRANSFERENCIA": PAGO_CON_SISTEMA_FINANCIERO,
}

LEYENDA_RIMPE = "CONTRIBUYENTE RÉGIMEN RIMPE"


class ErrorFacturaXML(ValueError):
    """Los datos no alcanzan para armar un XML que el SRI acepte."""


@dataclass
class Emisor:
    """Los datos del gimnasio. Salen de la configuración, no del código."""

    ruc: str
    razon_social: str
    direccion_matriz: str
    direccion_establecimiento: str
    establecimiento: str
    punto_emision: str
    obligado_contabilidad: bool = False
    nombre_comercial: str | None = None
    contribuyente_rimpe: bool = False
    ruc_proveedor_sistema: str | None = None

    def validar(self) -> None:
        if len(self.ruc) != 13 or not self.ruc.isdigit():
            raise ErrorFacturaXML(
                f"el RUC del emisor debe tener 13 dígitos, llegó {self.ruc!r}"
            )
        for etiqueta, valor in (
            ("la razón social", self.razon_social),
            ("la dirección de la matriz", self.direccion_matriz),
            ("la dirección del establecimiento", self.direccion_establecimiento),
        ):
            if not (valor or "").strip():
                raise ErrorFacturaXML(f"falta {etiqueta} del emisor")


@dataclass
class Comprador:
    """A quién se le factura.

    Sin identificación se emite a consumidor final, que es lo que
    corresponde para quien entra a comprar un agua y no la pide a su
    nombre.
    """

    identificacion: str | None = None
    nombre: str | None = None
    direccion: str | None = None
    correo: str | None = None

    @property
    def tipo_identificacion(self) -> str:
        ident = (self.identificacion or "").strip()
        if not ident or ident == CONSUMIDOR_FINAL_ID:
            return IDENT_CONSUMIDOR_FINAL
        if not ident.isdigit():
            return IDENT_PASAPORTE
        if len(ident) == 13:
            return IDENT_RUC
        if len(ident) == 10:
            return IDENT_CEDULA
        raise ErrorFacturaXML(
            f"no se reconoce la identificación {ident!r}: no es cédula (10), "
            "RUC (13) ni pasaporte"
        )

    def resueltos(self) -> tuple[str, str]:
        """La identificación y el nombre tal como van en el XML."""
        if self.tipo_identificacion == IDENT_CONSUMIDOR_FINAL:
            return CONSUMIDOR_FINAL_ID, CONSUMIDOR_FINAL_NOMBRE
        nombre = (self.nombre or "").strip()
        if not nombre:
            raise ErrorFacturaXML(
                "una factura con identificación necesita el nombre del cliente"
            )
        return self.identificacion.strip(), nombre


@dataclass
class LineaXML:
    """Una línea, con el precio CON IVA, como lo maneja el gimnasio."""

    codigo: str
    descripcion: str
    cantidad: int
    precio_unitario_con_iva: Decimal
    descuento_con_iva: Decimal = Decimal("0")

    @property
    def total_con_iva(self) -> Decimal:
        bruto = (self.precio_unitario_con_iva * self.cantidad).quantize(CENTAVO)
        return bruto - self.descuento_con_iva


def _dinero(valor: Decimal) -> str:
    """Dos decimales siempre. Ver la nota 4 de la cabecera."""
    return str(Decimal(valor).quantize(CENTAVO))


def _texto(padre, etiqueta, valor):
    nodo = ET.SubElement(padre, etiqueta)
    nodo.text = str(valor)
    return nodo


def generar(
    *,
    emisor: Emisor,
    comprador: Comprador,
    lineas: list[LineaXML],
    clave_acceso: str,
    secuencial: int,
    fecha_emision: date,
    iva_porcentaje: Decimal,
    ambiente: str,
    metodo_pago: str,
    propina: Decimal = Decimal("0"),
) -> str:
    """Arma el XML de la factura, sin firmar.

    Devuelve el XML como texto. La firma es un paso aparte: el nodo de
    firma se agrega adentro del documento, y para eso hace falta el
    .p12, que no vive en este servicio.
    """
    emisor.validar()
    if not lineas:
        raise ErrorFacturaXML("una factura sin líneas no existe")
    if iva_porcentaje not in CODIGO_TARIFA:
        raise ErrorFacturaXML(
            f"no hay código de tarifa para un IVA del {iva_porcentaje}%. "
            f"Los conocidos son {sorted(CODIGO_TARIFA)}"
        )
    if metodo_pago not in FORMA_PAGO:
        raise ErrorFacturaXML(
            f"método de pago no contemplado: {metodo_pago!r}"
        )

    codigo_tarifa = CODIGO_TARIFA[iva_porcentaje]

    # Totales de la factura primero, y después el reparto entre
    # líneas: es el orden que hace cuadrar las sumas. Ver bases.py.
    total_con_iva = sum((l.total_con_iva for l in lineas), Decimal("0"))
    total_con_iva = total_con_iva.quantize(CENTAVO)
    if total_con_iva < 0:
        raise ErrorFacturaXML("el total de la factura quedó negativo")

    base_factura = bases.base_del_total(total_con_iva, iva_porcentaje)
    iva_factura = (total_con_iva - base_factura).quantize(CENTAVO)
    bases_linea = bases.repartir(
        base_factura, [l.total_con_iva for l in lineas]
    )

    raiz = ET.Element("factura", {"id": "comprobante", "version": VERSION})

    trib = ET.SubElement(raiz, "infoTributaria")
    _texto(trib, "ambiente", ambiente)
    _texto(trib, "tipoEmision", "1")
    _texto(trib, "razonSocial", emisor.razon_social)
    if emisor.nombre_comercial:
        _texto(trib, "nombreComercial", emisor.nombre_comercial)
    _texto(trib, "ruc", emisor.ruc)
    _texto(trib, "claveAcceso", clave_acceso)
    _texto(trib, "codDoc", COD_DOC_FACTURA)
    _texto(trib, "estab", emisor.establecimiento)
    _texto(trib, "ptoEmi", emisor.punto_emision)
    _texto(trib, "secuencial", str(secuencial).zfill(9))
    _texto(trib, "dirMatriz", emisor.direccion_matriz)
    if emisor.contribuyente_rimpe:
        _texto(trib, "contribuyenteRimpe", LEYENDA_RIMPE)

    identificacion, nombre_comprador = comprador.resueltos()

    info = ET.SubElement(raiz, "infoFactura")
    _texto(info, "fechaEmision", fecha_emision.strftime("%d/%m/%Y"))
    _texto(info, "dirEstablecimiento", emisor.direccion_establecimiento)
    _texto(
        info,
        "obligadoContabilidad",
        "SI" if emisor.obligado_contabilidad else "NO",
    )
    _texto(info, "tipoIdentificacionComprador", comprador.tipo_identificacion)
    _texto(info, "razonSocialComprador", nombre_comprador)
    _texto(info, "identificacionComprador", identificacion)
    if comprador.direccion:
        _texto(info, "direccionComprador", comprador.direccion)
    _texto(info, "totalSinImpuestos", _dinero(base_factura))

    descuento_total = sum(
        (l.descuento_con_iva for l in lineas), Decimal("0")
    ).quantize(CENTAVO)
    _texto(info, "totalDescuento", _dinero(descuento_total))

    con_impuestos = ET.SubElement(info, "totalConImpuestos")
    total_impuesto = ET.SubElement(con_impuestos, "totalImpuesto")
    _texto(total_impuesto, "codigo", IMPUESTO_IVA)
    _texto(total_impuesto, "codigoPorcentaje", codigo_tarifa)
    _texto(total_impuesto, "baseImponible", _dinero(base_factura))
    _texto(total_impuesto, "valor", _dinero(iva_factura))

    _texto(info, "propina", _dinero(propina))
    _texto(info, "importeTotal", _dinero(total_con_iva + propina))
    _texto(info, "moneda", "DOLAR")

    pagos = ET.SubElement(info, "pagos")
    pago = ET.SubElement(pagos, "pago")
    _texto(pago, "formaPago", FORMA_PAGO[metodo_pago])
    _texto(pago, "total", _dinero(total_con_iva + propina))

    detalles = ET.SubElement(raiz, "detalles")
    for linea, base_linea in zip(lineas, bases_linea):
        iva_linea = (linea.total_con_iva - base_linea).quantize(CENTAVO)
        detalle = ET.SubElement(detalles, "detalle")
        _texto(detalle, "codigoPrincipal", linea.codigo)
        _texto(detalle, "descripcion", linea.descripcion)
        _texto(detalle, "cantidad", _dinero(Decimal(linea.cantidad)))
        # El precio unitario sin IVA sale de la base ya repartida, no
        # de dividir el precio de lista: si se lo recalculara acá, la
        # suma volvería a descuadrar.
        unitario = (base_linea / linea.cantidad).quantize(CENTAVO)
        _texto(detalle, "precioUnitario", _dinero(unitario))
        _texto(detalle, "descuento", _dinero(linea.descuento_con_iva))
        _texto(detalle, "precioTotalSinImpuesto", _dinero(base_linea))

        impuestos = ET.SubElement(detalle, "impuestos")
        impuesto = ET.SubElement(impuestos, "impuesto")
        _texto(impuesto, "codigo", IMPUESTO_IVA)
        _texto(impuesto, "codigoPorcentaje", codigo_tarifa)
        _texto(impuesto, "tarifa", _dinero(iva_porcentaje))
        _texto(impuesto, "baseImponible", _dinero(base_linea))
        _texto(impuesto, "valor", _dinero(iva_linea))

    adicional = ET.SubElement(raiz, "infoAdicional")
    if comprador.correo:
        ET.SubElement(adicional, "campoAdicional", {"nombre": "Email"}).text = (
            comprador.correo
        )
    if emisor.ruc_proveedor_sistema:
        # El nombre del campo es exactamente "RUC Proveedor". Ver la
        # nota 3 de la cabecera.
        ET.SubElement(
            adicional, "campoAdicional", {"nombre": "RUC Proveedor"}
        ).text = emisor.ruc_proveedor_sistema
    if not list(adicional):
        raiz.remove(adicional)

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        raiz, encoding="unicode"
    )
