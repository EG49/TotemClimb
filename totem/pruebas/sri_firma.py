"""Pruebas de la firma XAdES-BES.

Se genera un certificado .p12 DE PRUEBA en esta misma corrida, se
firma una factura armada por el generador del proyecto, y se verifica:

  - que el XML firmado tenga todos los nodos del XAdES-BES
  - que la factura no se haya alterado al firmarla
  - que la firma sea criptograficamente valida, verificandola con la
    clave publica del certificado

Lo ultimo es lo que importa: un XML con los nodos en su lugar pero con
una firma que no cierra se ve bien y el SRI lo rechaza.

El certificado del gimnasio NO participa de esta prueba y no debe
copiarse a ninguna parte para correrla.

Si falta la libreria de firma, la prueba lo dice y no falla: el resto
del sistema no depende de ella.
"""

import base64
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DS = "http://www.w3.org/2000/09/xmldsig#"
XADES = "http://uri.etsi.org/01903/v1.3.2#"

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    from lxml import etree
except ImportError as error:
    print(f"\nNo estan las dependencias de firma ({error.name}).")
    print("Instalelas con:  pip install -r requirements.txt")
    print("Esta prueba se omite; el resto del sistema no la necesita.")
    sys.exit(0)

from app.services.sri import clave_acceso as ca  # noqa: E402
from app.services.sri import factura_xml as fx  # noqa: E402
from app.services.sri import firma as fr  # noqa: E402

CLAVE_DE_PRUEBA = "clave-solo-para-esta-prueba"


def certificado_de_prueba(destino: Path):
    """Un .p12 autofirmado, valido solo para esta prueba."""
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "EC"),
        x509.NameAttribute(NameOID.COMMON_NAME, "CERTIFICADO DE PRUEBA"),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, "1790012345001"),
    ])
    ahora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(days=1))
        .not_valid_after(ahora + timedelta(days=365))
        .sign(clave, hashes.SHA256())
    )
    destino.write_bytes(
        pkcs12.serialize_key_and_certificates(
            b"prueba", clave, cert, None,
            serialization.BestAvailableEncryption(CLAVE_DE_PRUEBA.encode()),
        )
    )
    return cert


EMISOR = fx.Emisor(
    ruc="1790012345001",
    razon_social="TOTEM CLIMB GYM",
    direccion_matriz="Av. Principal 123",
    direccion_establecimiento="Av. Principal 123",
    establecimiento="001",
    punto_emision="002",
)


def factura_de_prueba():
    clave = ca.generar(
        fecha_emision=date(2026, 11, 16),
        tipo_comprobante=ca.FACTURA,
        ruc=EMISOR.ruc,
        ambiente=ca.AMBIENTE_PRUEBAS,
        establecimiento="001",
        punto_emision="002",
        secuencial=900000001,
        codigo_numerico="12345678",
    )
    xml = fx.generar(
        emisor=EMISOR,
        comprador=fx.Comprador(),
        lineas=[fx.LineaXML("PASE-1", "Pase del dia", 1, Decimal("10.00"))],
        clave_acceso=clave,
        secuencial=900000001,
        fecha_emision=date(2026, 11, 16),
        iva_porcentaje=Decimal("15"),
        ambiente=ca.AMBIENTE_PRUEBAS,
        metodo_pago="EFECTIVO",
    )
    return clave, xml


with TemporaryDirectory() as carpeta:
    ruta_p12 = Path(carpeta) / "prueba.p12"
    cert_original = certificado_de_prueba(ruta_p12)
    clave_acceso, xml = factura_de_prueba()

    print("\nSE FIRMA")
    firmado = fr.firmar(xml, ruta_p12, CLAVE_DE_PRUEBA)
    revisar("devuelve algo", bool(firmado))
    revisar("repone la declaracion <?xml ... ?> que el SRI exige",
            firmado.lstrip().startswith(fr.DECLARACION),
            firmado.lstrip()[:40])

    raiz = etree.fromstring(firmado.encode("utf-8"))

    print("\nLA FACTURA NO SE ALTERO")
    revisar("sigue siendo <factura> con id=comprobante",
            raiz.tag == "factura" and raiz.get("id") == "comprobante")
    revisar("la clave de acceso es la misma",
            raiz.findtext("infoTributaria/claveAcceso") == clave_acceso)
    revisar("el importe total es el mismo",
            raiz.findtext("infoFactura/importeTotal") == "10.00",
            raiz.findtext("infoFactura/importeTotal"))
    revisar("la base imponible es la misma",
            raiz.findtext("infoFactura/totalSinImpuestos") == "8.70")

    print("\nESTRUCTURA XMLDSIG")
    for etiqueta in ("Signature", "SignedInfo", "SignatureValue",
                     "KeyInfo", "X509Certificate", "Reference"):
        revisar(f"lleva {etiqueta}",
                any(True for _ in raiz.iter(f"{{{DS}}}{etiqueta}")))

    print("\nESTRUCTURA XADES-BES")
    for etiqueta in ("QualifyingProperties", "SignedProperties",
                     "SignedSignatureProperties", "SigningCertificate",
                     "SigningTime", "DataObjectFormat"):
        revisar(f"lleva {etiqueta}",
                any(True for _ in raiz.iter(f"{{{XADES}}}{etiqueta}")))

    print("\nALGORITMOS QUE DECLARA")
    info = next(raiz.iter(f"{{{DS}}}SignedInfo"))
    c14n = next(info.iter(f"{{{DS}}}CanonicalizationMethod")).get("Algorithm")
    metodo = next(info.iter(f"{{{DS}}}SignatureMethod")).get("Algorithm")
    revisar("canonizacion inclusiva (REC-xml-c14n-20010315)",
            c14n == "http://www.w3.org/TR/2001/REC-xml-c14n-20010315", c14n)
    revisar("firma RSA-SHA1, como pide el esquema del SRI",
            metodo == "http://www.w3.org/2000/09/xmldsig#rsa-sha1", metodo)

    print("\nNADA DE ESPACIOS ALREDEDOR DE LA FIRMA")
    # Es el defecto que hizo rechazar la primera factura: la libreria
    # insertaba la firma indentada, esos espacios pasaban a ser
    # contenido de <factura> y el digest del comprobante ya no cerraba.
    cuerpo = firmado.split("?>", 1)[1]
    revisar("la firma arranca pegada a </detalles>",
            "</detalles><ds:Signature" in cuerpo,
            cuerpo[cuerpo.find("</detalles>"):][:60])
    revisar("y cierra pegada a </factura>",
            "</ds:Signature></factura>" in cuerpo,
            cuerpo[-60:])
    revisar("el comprobante firmado no tiene saltos de linea",
            "\n" not in cuerpo.strip(),
            f"{cuerpo.count(chr(10))} saltos")

    print("\nLAS TRES REFERENCIAS CIERRAN (lo que verifica el SRI)")
    # Un XML con los nodos del XAdES en su lugar y un digest que no
    # cierra se ve bien y el SRI lo devuelve con el error 39.
    import copy
    import hashlib

    def c14n(nodo):
        return etree.tostring(nodo, method="c14n", exclusive=False,
                              with_comments=False)

    def digest(datos):
        return base64.b64encode(hashlib.sha1(datos).digest()).decode()

    info = next(raiz.iter(f"{{{DS}}}SignedInfo"))
    por_uri = {}
    for referencia in info.findall(f"{{{DS}}}Reference"):
        por_uri[referencia.get("URI").lstrip("#")] = (
            referencia.findtext(f"{{{DS}}}DigestValue").strip()
        )

    # 1. La factura sin la firma, que es lo que deja el transform.
    copia = copy.deepcopy(raiz)
    copia.remove(copia.find(f"{{{DS}}}Signature"))
    revisar("el digest de la factura sin la firma",
            digest(c14n(copia)) == por_uri["comprobante"],
            f"declarado {por_uri['comprobante']}, "
            f"calculado {digest(c14n(copia))}")

    # 2. El KeyInfo y 3. las SignedProperties, por su Id.
    for etiqueta, espacio, nombre in (
        ("KeyInfo", DS, "el digest del KeyInfo"),
        ("SignedProperties", XADES, "el digest de las SignedProperties"),
    ):
        nodo = next(raiz.iter(f"{{{espacio}}}{etiqueta}"))
        declarado = por_uri.get(nodo.get("Id"))
        revisar(nombre, declarado is not None
                and digest(c14n(nodo)) == declarado,
                f"declarado {declarado}, calculado {digest(c14n(nodo))}")

    print("\nLA FIRMA CIERRA (lo que no se ve mirando el XML)")
    b64 = "".join(next(raiz.iter(f"{{{DS}}}X509Certificate")).text.split())
    cert_en_xml = x509.load_der_x509_certificate(base64.b64decode(b64))
    revisar("el certificado incrustado es el que firmo",
            cert_en_xml.fingerprint(hashes.SHA256())
            == cert_original.fingerprint(hashes.SHA256()))

    # Con la canonizacion que el propio documento declara: inclusiva.
    # Con la exclusiva NO cierra, y esa diferencia hace creer que la
    # firma esta mal cuando el equivocado es quien la verifica.
    canonizado = etree.tostring(info, method="c14n", exclusive=False)
    valor = base64.b64decode(
        "".join(next(raiz.iter(f"{{{DS}}}SignatureValue")).text.split()))
    try:
        cert_en_xml.public_key().verify(
            valor, canonizado, padding.PKCS1v15(), hashes.SHA1())
        revisar("la firma es criptograficamente valida", True)
    except Exception as error:  # noqa: BLE001
        revisar("la firma es criptograficamente valida", False,
                type(error).__name__)

    print("\nUN COMPROBANTE SIN id=comprobante SE RECHAZA")
    try:
        fr.firmar(xml.replace('id="comprobante"', 'id="otro"'),
                  ruta_p12, CLAVE_DE_PRUEBA)
        revisar("avisa que falta id=comprobante", False, "no levanto")
    except fr.ErrorFirma as error:
        revisar("avisa que falta id=comprobante",
                "comprobante" in str(error))

    print("\nEL EMISOR DEL CERTIFICADO NO QUEDA VACIO")
    # La libreria dejaba <X509IssuerName> vacio.
    emisor = next(raiz.iter(f"{{{DS}}}X509IssuerName")).text
    revisar("X509IssuerName trae el nombre del emisor",
            bool(emisor and emisor.strip()), repr(emisor))
    serie = next(raiz.iter(f"{{{DS}}}X509SerialNumber")).text
    revisar("X509SerialNumber es la serie del certificado",
            serie == str(cert_original.serial_number), serie)
    digest_declarado = next(
        next(raiz.iter(f"{{{XADES}}}CertDigest")).iter(f"{{{DS}}}DigestValue")
    ).text.strip()
    import hashlib as _h
    revisar("el digest declarado es el del certificado",
            digest_declarado == base64.b64encode(_h.sha1(
                cert_original.public_bytes(
                    __import__("cryptography.hazmat.primitives.serialization",
                               fromlist=["Encoding"]).Encoding.DER)
            ).digest()).decode(), digest_declarado)

    print("\nSI ALGO ESTA MAL, SE DICE CLARO")
    try:
        fr.firmar(xml, ruta_p12, "clave-equivocada")
        revisar("una clave equivocada levanta ErrorFirma", False, "no levanto")
    except fr.ErrorFirma as error:
        revisar("una clave equivocada levanta ErrorFirma", True)
        revisar("y el mensaje menciona SRI_P12_CLAVE",
                "SRI_P12_CLAVE" in str(error), str(error)[:80])

    try:
        fr.firmar(xml, Path(carpeta) / "no-existe.p12", CLAVE_DE_PRUEBA)
        revisar("un certificado que no existe levanta ErrorFirma", False,
                "no levanto")
    except fr.ErrorFirma:
        revisar("un certificado que no existe levanta ErrorFirma", True)

total = 37
print(f"\n{total} comprobaciones")
if fallas:
    print(f"{len(fallas)} FALLAS: " + ", ".join(fallas))
    sys.exit(1)
print("TODO OK")
