"""Piezas compartidas por las pruebas de facturacion electronica.

Estan acá y no dentro de una de las pruebas porque importar un
archivo de prueba lo EJECUTA entero: todo lo que esta a nivel de
modulo corre con el import. Al reaprovechar estas funciones desde
pruebas/sri_cobro.py, la otra prueba arrancaba una corrida completa
del cobro antes de empezar la suya.

Acá no hay nada a nivel de modulo salvo constantes: importarlo no
hace nada.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

CLAVE_P12 = "clave-solo-para-esta-prueba"


def certificado_de_prueba(destino: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "EC"),
        x509.NameAttribute(NameOID.COMMON_NAME, "CERTIFICADO DE PRUEBA"),
    ])
    ahora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre).issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(days=1))
        .not_valid_after(ahora + timedelta(days=365))
        .sign(clave, hashes.SHA256())
    )
    destino.write_bytes(pkcs12.serialize_key_and_certificates(
        b"prueba", clave, cert, None,
        serialization.BestAvailableEncryption(CLAVE_P12.encode()),
    ))


RECIBIDA = (
    '<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/'
    'soap/envelope/"><s:Body><RespuestaRecepcionComprobante>'
    "<estado>RECIBIDA</estado><comprobantes/>"
    "</RespuestaRecepcionComprobante></s:Body></s:Envelope>"
)

DEVUELTA = (
    '<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/'
    'soap/envelope/"><s:Body><RespuestaRecepcionComprobante>'
    "<estado>DEVUELTA</estado><comprobantes><comprobante><mensajes><mensaje>"
    "<identificador>43</identificador><mensaje>CLAVE ACCESO REGISTRADA"
    "</mensaje><tipo>ERROR</tipo></mensaje></mensajes></comprobante>"
    "</comprobantes></RespuestaRecepcionComprobante></s:Body></s:Envelope>"
)


def autorizado(clave, comprobante=""):
    """La respuesta del SRI cuando autoriza.

    `comprobante` es el XML firmado, que el SRI devuelve adentro,
    escapado. No es un detalle: el RIDE se arma desde ahi, asi que un
    simulador que lo deje vacio no prueba el camino de verdad.
    """
    from xml.sax.saxutils import escape

    return _autorizado(clave, escape(comprobante))


def _autorizado(clave, comprobante):
    return (
        '<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/'
        'soap/envelope/"><s:Body><RespuestaAutorizacionComprobante>'
        f"<claveAccesoConsultada>{clave}</claveAccesoConsultada>"
        "<numeroComprobantes>1</numeroComprobantes><autorizaciones>"
        "<autorizacion><estado>AUTORIZADO</estado>"
        f"<numeroAutorizacion>{clave}</numeroAutorizacion>"
        "<fechaAutorizacion>2026-11-17T10:00:00-05:00</fechaAutorizacion>"
        f"<ambiente>PRUEBAS</ambiente><comprobante>{comprobante}</comprobante>"
        "<mensajes/>"
        "</autorizacion></autorizaciones>"
        "</RespuestaAutorizacionComprobante></s:Body></s:Envelope>"
    )


class SriDeMentira:
    """Reemplaza la salida a la red. Se le dice como tiene que portarse."""

    def __init__(self):
        self.modo = "bien"
        self.llamadas = 0
        # El ultimo XML firmado que se le envio. Se lo devuelve dentro
        # de la autorizacion, igual que el SRI.
        self.ultimo_comprobante = ""

    def __call__(self, url, cuerpo):
        self.llamadas += 1
        if self.modo == "sin internet":
            raise OSError("no hay conexion (simulado)")
        if self.modo == "lento":
            raise TimeoutError("el SRI no contesto (simulado)")
        # En minusculas: la URL del SRI lleva "Recepcion".
        if "recepcion" in url.lower():
            import base64

            codificado = cuerpo.split("<xml>")[1].split("</xml>")[0]
            self.ultimo_comprobante = base64.b64decode(codificado).decode(
                "utf-8", "replace"
            )
            return DEVUELTA if self.modo == "devuelta" else RECIBIDA
        clave = cuerpo.split("<claveAccesoComprobante>")[1].split("<")[0]
        return autorizado(clave, self.ultimo_comprobante)


