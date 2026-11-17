"""Firma XAdES-BES del comprobante, con el certificado .p12.

Por qué está escrita acá y no se usa una librería
-------------------------------------------------
Se probaron las dos librerías que aparecen al buscar. Ninguna sirve.

`xades-bes-sri-ec` no corre en Windows: clava cryptography==3.2.1,
pyOpenSSL==20.0.1 y lxml==4.6.3, de 2020 y 2021, que no compilan en
Python 3.12, y por debajo llama por consola a `xmllint` y `openssl`,
que en Windows no vienen instalados.

`xadessri` sí instala y arma una estructura que el SRI acepta en
recepción, pero el comprobante sale NO AUTORIZADO con el error 39,
"FIRMA INVALIDA". Se diagnosticó con una factura real contra el
ambiente de certificación: de las tres referencias firmadas, la de
SignedProperties cerraba y las otras dos no. El motivo es que inserta
el nodo de firma indentado:

    </detalles>
        <ds:Signature ...>

Esos espacios pasan a ser contenido de <factura>. El transform
`enveloped-signature` quita solo el nodo Signature, no los espacios
que quedan alrededor, así que quien verifica calcula el digest sobre
la factura MÁS esos espacios y no coincide con el que la librería
calculó sobre la factura sola. El mismo defecto rompe el digest del
KeyInfo. Y además deja <ds:X509IssuerName> vacío.

De ahí las dos reglas de este archivo:

  1. NADA de espacios ni saltos de línea dentro del nodo de firma, ni
     alrededor. El XML firmado sale en una sola línea. No lo "ordene"
     con pretty_print: eso vuelve a romper la firma.

  2. Los digests se calculan sobre los nodos YA COLOCADOS en el
     documento. La canonización inclusiva arrastra las declaraciones
     de namespace de los ancestros, así que el mismo nodo fuera del
     árbol da otro digest.

Con esta firma el SRI autorizo el comprobante en el ambiente de
certificacion el 16/11/2026, sin mensajes de error.

Lo que el SRI verifica, y que pruebas/sri_firma.py comprueba acá:

  - el digest de la factura sin la firma
  - el digest del KeyInfo
  - el digest de las SignedProperties
  - la firma RSA sobre el SignedInfo canonizado
  - que el digest declarado del certificado sea el del certificado
"""

import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from secrets import randbelow

DS = "http://www.w3.org/2000/09/xmldsig#"
ETSI = "http://uri.etsi.org/01903/v1.3.2#"
TIPO_SIGNED_PROPERTIES = "http://uri.etsi.org/01903#SignedProperties"

C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
RSA_SHA1 = "http://www.w3.org/2000/09/xmldsig#rsa-sha1"
SHA1 = "http://www.w3.org/2000/09/xmldsig#sha1"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"

DECLARACION = '<?xml version="1.0" encoding="UTF-8"?>'


class ErrorFirma(RuntimeError):
    """No se pudo firmar el comprobante."""


def _ds(etiqueta: str) -> str:
    return f"{{{DS}}}{etiqueta}"


def _etsi(etiqueta: str) -> str:
    return f"{{{ETSI}}}{etiqueta}"


def _sin_declaracion(xml: str) -> str:
    recortado = xml.lstrip()
    if recortado.startswith("<?xml"):
        return recortado.partition("?>")[2].lstrip()
    return recortado


def _c14n(nodo) -> bytes:
    """Canonización inclusiva, la que declara el comprobante.

    Inclusiva y no exclusiva: con la exclusiva los digests no cierran,
    y la diferencia hace creer que la firma está mal cuando el
    equivocado es quien verifica.
    """
    from lxml import etree

    return etree.tostring(
        nodo, method="c14n", exclusive=False, with_comments=False
    )


def _digest(datos: bytes) -> str:
    return base64.b64encode(hashlib.sha1(datos).digest()).decode("ascii")


def _entero(valor: int) -> str:
    """Un entero grande en base64, como lo pide RSAKeyValue."""
    largo = (valor.bit_length() + 7) // 8
    return base64.b64encode(valor.to_bytes(largo, "big")).decode("ascii")


def _numero() -> int:
    """Un número para los identificadores internos del nodo de firma."""
    return randbelow(900000) + 100000


def _cargar_certificado(ruta_p12: Path, clave_p12: str):
    from cryptography.hazmat.primitives.serialization import pkcs12

    try:
        privada, certificado, _ = pkcs12.load_key_and_certificates(
            ruta_p12.read_bytes(), clave_p12.encode("utf-8")
        )
    except Exception as error:  # noqa: BLE001
        raise ErrorFirma(
            "no se pudo abrir el certificado. Lo más probable es que "
            f"SRI_P12_CLAVE esté mal. Detalle: {error}"
        ) from error
    if privada is None or certificado is None:
        raise ErrorFirma(
            "el archivo .p12 no trae juntos la clave privada y el "
            "certificado; así no sirve para firmar"
        )
    return privada, certificado


def firmar(xml: str, ruta_p12: str | Path, clave_p12: str) -> str:
    """Devuelve el XML firmado, listo para enviar al SRI.

    El certificado se lee del disco de esta máquina y no viaja a
    ninguna parte.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        from lxml import etree
    except ImportError as error:
        raise ErrorFirma(
            "faltan las dependencias de firma. Instálelas con:\n"
            "  pip install -r requirements.txt"
        ) from error

    ruta = Path(ruta_p12)
    if not ruta.exists():
        raise ErrorFirma(f"no encuentro el certificado en {ruta}")

    privada, certificado = _cargar_certificado(ruta, clave_p12)
    if not isinstance(certificado.public_key(), rsa.RSAPublicKey):
        raise ErrorFirma(
            "el certificado no es RSA, y el esquema del SRI pide RSA"
        )

    try:
        raiz = etree.fromstring(_sin_declaracion(xml).encode("utf-8"))
    except etree.XMLSyntaxError as error:
        raise ErrorFirma(f"el comprobante no es XML válido: {error}") from error

    if raiz.get("id") != "comprobante":
        raise ErrorFirma(
            'el comprobante debe llevar id="comprobante" para poder '
            "referenciarlo en la firma"
        )

    # El digest de la factura se toma ANTES de colgarle la firma, que
    # es justo lo que recalcula quien aplica el transform
    # enveloped-signature. Para que siga coincidiendo, el nodo de
    # firma no puede dejar ni un espacio alrededor.
    digest_comprobante = _digest(_c14n(raiz))

    id_firma = f"Signature{_numero()}"
    id_signed_info = f"Signature-SignedInfo{_numero()}"
    id_signed_props = f"{id_firma}-SignedProperties{_numero()}"
    id_certificado = f"Certificate{_numero()}"
    id_referencia = f"Reference-ID-{_numero()}"
    id_objeto = f"{id_firma}-Object{_numero()}"

    firma = etree.SubElement(
        raiz, _ds("Signature"), {"Id": id_firma},
        nsmap={"ds": DS, "etsi": ETSI},
    )

    # ─── SignedInfo, con las tres referencias ──────────────────────
    signed_info = etree.SubElement(
        firma, _ds("SignedInfo"), {"Id": id_signed_info}
    )
    etree.SubElement(
        signed_info, _ds("CanonicalizationMethod"), {"Algorithm": C14N}
    )
    etree.SubElement(
        signed_info, _ds("SignatureMethod"), {"Algorithm": RSA_SHA1}
    )

    referencia_props = etree.SubElement(
        signed_info, _ds("Reference"),
        {"Id": f"SignedPropertiesID{_numero()}",
         "Type": TIPO_SIGNED_PROPERTIES,
         "URI": f"#{id_signed_props}"},
    )
    etree.SubElement(referencia_props, _ds("DigestMethod"), {"Algorithm": SHA1})
    digest_props = etree.SubElement(referencia_props, _ds("DigestValue"))

    referencia_cert = etree.SubElement(
        signed_info, _ds("Reference"), {"URI": f"#{id_certificado}"}
    )
    etree.SubElement(referencia_cert, _ds("DigestMethod"), {"Algorithm": SHA1})
    digest_cert = etree.SubElement(referencia_cert, _ds("DigestValue"))

    referencia_comp = etree.SubElement(
        signed_info, _ds("Reference"),
        {"Id": id_referencia, "URI": "#comprobante"},
    )
    transformaciones = etree.SubElement(referencia_comp, _ds("Transforms"))
    etree.SubElement(
        transformaciones, _ds("Transform"), {"Algorithm": ENVELOPED}
    )
    etree.SubElement(referencia_comp, _ds("DigestMethod"), {"Algorithm": SHA1})
    etree.SubElement(referencia_comp, _ds("DigestValue")).text = (
        digest_comprobante
    )

    valor_firma = etree.SubElement(firma, _ds("SignatureValue"))

    # ─── KeyInfo: el certificado y la clave pública ────────────────
    der = certificado.public_bytes(serialization.Encoding.DER)
    numeros = certificado.public_key().public_numbers()

    key_info = etree.SubElement(firma, _ds("KeyInfo"), {"Id": id_certificado})
    datos_x509 = etree.SubElement(key_info, _ds("X509Data"))
    etree.SubElement(datos_x509, _ds("X509Certificate")).text = (
        base64.b64encode(der).decode("ascii")
    )
    valor_clave = etree.SubElement(key_info, _ds("KeyValue"))
    valor_rsa = etree.SubElement(valor_clave, _ds("RSAKeyValue"))
    etree.SubElement(valor_rsa, _ds("Modulus")).text = _entero(numeros.n)
    etree.SubElement(valor_rsa, _ds("Exponent")).text = _entero(numeros.e)

    # ─── SignedProperties: la parte propiamente XAdES ──────────────
    objeto = etree.SubElement(firma, _ds("Object"), {"Id": id_objeto})
    cualificadas = etree.SubElement(
        objeto, _etsi("QualifyingProperties"), {"Target": f"#{id_firma}"}
    )
    signed_props = etree.SubElement(
        cualificadas, _etsi("SignedProperties"), {"Id": id_signed_props}
    )
    props_firma = etree.SubElement(
        signed_props, _etsi("SignedSignatureProperties")
    )
    etree.SubElement(props_firma, _etsi("SigningTime")).text = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    cert_firmante = etree.SubElement(props_firma, _etsi("SigningCertificate"))
    nodo_cert = etree.SubElement(cert_firmante, _etsi("Cert"))
    digest_del_cert = etree.SubElement(nodo_cert, _etsi("CertDigest"))
    etree.SubElement(digest_del_cert, _ds("DigestMethod"), {"Algorithm": SHA1})
    etree.SubElement(digest_del_cert, _ds("DigestValue")).text = _digest(der)

    emisor_y_serie = etree.SubElement(nodo_cert, _etsi("IssuerSerial"))
    # El nombre del emisor, que la librería dejaba vacío.
    etree.SubElement(emisor_y_serie, _ds("X509IssuerName")).text = (
        certificado.issuer.rfc4514_string()
    )
    etree.SubElement(emisor_y_serie, _ds("X509SerialNumber")).text = str(
        certificado.serial_number
    )

    props_datos = etree.SubElement(
        signed_props, _etsi("SignedDataObjectProperties")
    )
    formato = etree.SubElement(
        props_datos, _etsi("DataObjectFormat"),
        {"ObjectReference": f"#{id_referencia}"},
    )
    etree.SubElement(formato, _etsi("Description")).text = (
        "contenido comprobante"
    )
    etree.SubElement(formato, _etsi("MimeType")).text = "text/xml"

    # ─── Los digests restantes y la firma ──────────────────────────
    # Se calculan con los nodos ya dentro del arbol. Ver la regla 2 de
    # la cabecera: fuera del arbol dan otro valor.
    digest_props.text = _digest(_c14n(signed_props))
    digest_cert.text = _digest(_c14n(key_info))

    valor_firma.text = base64.b64encode(
        privada.sign(_c14n(signed_info), padding.PKCS1v15(), hashes.SHA1())
    ).decode("ascii")

    # Sin pretty_print y sin retocar espacios: ver la regla 1.
    return f"{DECLARACION}\n{etree.tostring(raiz, encoding='unicode')}"
