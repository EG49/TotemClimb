"""Prueba de punta a punta contra el ambiente de CERTIFICACION del SRI.

Este script se corre EN LA MAQUINA DONDE ESTA EL CERTIFICADO. No corre
en el entorno de desarrollo de la nube: el .p12 no debe salir de la PC
del gimnasio, y ese entorno tampoco tiene salida a celcer.sri.gob.ec.

Lo que hace, en orden:

  1. Arma el XML de una factura de prueba con los datos del .env
  2. Lo firma con el .p12 (XAdES-BES)
  3. Lo envia a RECEPCION del ambiente de certificacion
  4. Consulta AUTORIZACION y muestra lo que respondio el SRI
  5. Guarda los XML en una carpeta, para poder mirarlos

AVISO: los pasos 3 y 4 (los envios por red) no pudieron probarse
contra el SRI al escribirlos, porque el entorno de desarrollo no
alcanza esos servidores. Todo lo demas SI esta probado: la clave de
acceso, el reparto de la base, el armado del XML y la firma, esta
ultima verificada criptograficamente contra un certificado de prueba
(pruebas/sri_clave_acceso.py, sri_bases.py, sri_factura_xml.py y
sri_firma.py). Si el SRI rechaza, lo mas probable es que falte un
dato del emisor o que el punto de emision no exista todavia.

Como se corre, desde la carpeta totem:

    python -m scripts.sri_prueba

Antes hay que instalar las dependencias de firma, que ya estan en
requirements.txt:

    pip install -r requirements.txt

No hace falta instalar nada mas: ni openssl, ni xmllint, ni un
compilador. Ver app/services/sri/firma.py si interesa por que.
"""

import base64
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.sri import clave_acceso as ca
from app.services.sri import factura_xml as fx

SALIDA = Path("sri_pruebas")

RECEPCION = (
    "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/"
    "RecepcionComprobantesOffline"
)
AUTORIZACION = (
    "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/"
    "AutorizacionComprobantesOffline"
)


def dato(nombre: str, obligatorio: bool = True) -> str:
    valor = (os.environ.get(nombre) or "").strip()
    if obligatorio and not valor:
        print(f"\nFalta {nombre} en el .env. Ver .env.ejemplo.")
        sys.exit(1)
    return valor


def cargar_env() -> None:
    """Lee el .env sin dependencias, como el resto de los scripts."""
    archivo = Path(".env")
    if not archivo.exists():
        print("No encuentro el .env en esta carpeta.")
        sys.exit(1)
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip())


def revisar_que_el_p12_no_este_en_el_repositorio(ruta: Path) -> None:
    """El certificado no puede vivir dentro del repositorio.

    Si se lo guarda acá, tarde o temprano entra en un commit, y
    entonces hay que revocarlo y comprar otro: no se arregla cambiando
    una clave.
    """
    try:
        raiz = Path(__file__).resolve().parent.parent.parent
        ruta.resolve().relative_to(raiz)
    except ValueError:
        return  # está afuera, bien
    print(
        f"\nEl certificado está dentro del repositorio:\n  {ruta}\n\n"
        "Muévalo afuera (por ejemplo a C:\\totem\\certificado.p12) y\n"
        "apunte SRI_P12_RUTA allá. Si alguna vez se sube a Git hay que\n"
        "revocarlo y comprar otro."
    )
    sys.exit(1)


def firmar(xml: str, ruta_p12: Path, clave_p12: str, destino: Path) -> Path:
    """Firma y deja en el disco el antes y el despues.

    Se guarda tambien el XML sin firmar: si el SRI rechaza por
    estructura, ese archivo es el que hay que mirar.
    """
    from app.services.sri.firma import ErrorFirma, firmar as firmar_xades

    destino.with_name(destino.stem + "-sin-firmar.xml").write_text(
        xml, encoding="utf-8"
    )
    try:
        firmado = firmar_xades(xml, ruta_p12, clave_p12)
    except ErrorFirma as error:
        print(f"\n{error}")
        sys.exit(1)
    destino.write_text(firmado, encoding="utf-8")
    return destino


def soap(url: str, cuerpo: str) -> str:
    import urllib.request

    sobre = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv='
        '"http://schemas.xmlsoap.org/soap/envelope/">'
        "<soapenv:Header/><soapenv:Body>"
        f"{cuerpo}"
        "</soapenv:Body></soapenv:Envelope>"
    )
    peticion = urllib.request.Request(
        url,
        data=sobre.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
    )
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:
        return respuesta.read().decode("utf-8", errors="replace")


def enviar_a_recepcion(xml_firmado: bytes) -> str:
    codificado = base64.b64encode(xml_firmado).decode("ascii")
    return soap(
        RECEPCION,
        '<ec:validarComprobante xmlns:ec="http://ec.gob.sri.ws.recepcion">'
        f"<xml>{codificado}</xml>"
        "</ec:validarComprobante>",
    )


def consultar_autorizacion(clave: str) -> str:
    return soap(
        AUTORIZACION,
        '<ec:autorizacionComprobante '
        'xmlns:ec="http://ec.gob.sri.ws.autorizacion">'
        f"<claveAccesoComprobante>{clave}</claveAccesoComprobante>"
        "</ec:autorizacionComprobante>",
    )


def resumir(respuesta: str, titulo: str) -> None:
    """Muestra lo que importa de la respuesta del SRI.

    Las respuestas traen los mensajes de error en nodos <mensaje>,
    <informacionAdicional> e <identificador>. Se los muestra enteros:
    el codigo del SRI es lo que permite buscar la causa.
    """
    from xml.etree import ElementTree as ET

    print(f"\n--- {titulo} ---")
    try:
        raiz = ET.fromstring(respuesta)
    except ET.ParseError:
        print(respuesta[:2000])
        return

    for etiqueta in ("estado", "numeroComprobantes", "numeroAutorizacion",
                     "fechaAutorizacion", "ambiente"):
        for nodo in raiz.iter(etiqueta):
            if nodo.text and nodo.text.strip():
                print(f"  {etiqueta}: {nodo.text.strip()}")

    mensajes = list(raiz.iter("mensaje"))
    if not mensajes:
        print("  sin mensajes de error")
        return
    print("  mensajes:")
    for nodo in mensajes:
        partes = []
        for hijo in ("identificador", "mensaje", "tipo",
                     "informacionAdicional"):
            texto = nodo.findtext(hijo)
            if texto:
                partes.append(f"{hijo}={texto.strip()}")
        # Cuando <mensaje> es hoja, su propio texto es el mensaje.
        if not partes and nodo.text:
            partes.append(nodo.text.strip())
        print("    - " + "  ".join(partes))


def main() -> None:
    cargar_env()
    SALIDA.mkdir(exist_ok=True)

    ruta_p12 = Path(dato("SRI_P12_RUTA"))
    if not ruta_p12.exists():
        print(f"\nNo encuentro el certificado en {ruta_p12}")
        sys.exit(1)
    revisar_que_el_p12_no_este_en_el_repositorio(ruta_p12)
    clave_p12 = dato("SRI_P12_CLAVE")

    emisor = fx.Emisor(
        ruc=dato("SRI_RUC"),
        razon_social=dato("SRI_RAZON_SOCIAL"),
        nombre_comercial=dato("SRI_NOMBRE_COMERCIAL", obligatorio=False) or None,
        direccion_matriz=dato("SRI_DIR_MATRIZ"),
        direccion_establecimiento=dato("SRI_DIR_ESTABLECIMIENTO"),
        establecimiento=dato("SRI_ESTABLECIMIENTO"),
        punto_emision=dato("SRI_PUNTO_EMISION"),
        obligado_contabilidad=dato(
            "SRI_OBLIGADO_CONTABILIDAD", obligatorio=False
        ).upper() in ("SI", "1", "TRUE"),
        contribuyente_rimpe=dato(
            "SRI_CONTRIBUYENTE_RIMPE", obligatorio=False
        ).upper() in ("SI", "1", "TRUE"),
        ruc_proveedor_sistema=dato(
            "SRI_RUC_PROVEEDOR", obligatorio=False
        ) or None,
    )

    # Un secuencial alto y propio de las pruebas, para no pisar la
    # numeracion real del gimnasio por accidente.
    secuencial = int(dato("SRI_SECUENCIAL_PRUEBA", obligatorio=False) or 900000001)
    hoy = date.today()

    clave = ca.generar(
        fecha_emision=hoy,
        tipo_comprobante=ca.FACTURA,
        ruc=emisor.ruc,
        ambiente=ca.AMBIENTE_PRUEBAS,
        establecimiento=emisor.establecimiento,
        punto_emision=emisor.punto_emision,
        secuencial=secuencial,
        codigo_numerico="12345678",
    )

    print(f"\nAmbiente: CERTIFICACION (celcer)")
    print(f"Clave de acceso: {clave}")
    print(f"Secuencial: {secuencial}")

    xml = fx.generar(
        emisor=emisor,
        comprador=fx.Comprador(),  # consumidor final
        lineas=[
            fx.LineaXML("PASE-1", "Pase del dia", 1, Decimal("10.00")),
        ],
        clave_acceso=clave,
        secuencial=secuencial,
        fecha_emision=hoy,
        iva_porcentaje=Decimal("15"),
        ambiente=ca.AMBIENTE_PRUEBAS,
        metodo_pago="EFECTIVO",
    )

    destino = SALIDA / f"{clave}.xml"
    firmado = firmar(xml, ruta_p12, clave_p12, destino)
    print(f"\nXML firmado: {firmado}")

    print("\nEnviando a recepción...")
    try:
        respuesta = enviar_a_recepcion(firmado.read_bytes())
    except Exception as error:  # noqa: BLE001
        print(f"\nNo se pudo llegar a recepción: {error}")
        print("Revise la conexión y que el RUC esté habilitado en pruebas.")
        sys.exit(1)
    (SALIDA / f"{clave}-recepcion.xml").write_text(respuesta, encoding="utf-8")
    resumir(respuesta, "RECEPCION")

    print("\nConsultando autorización...")
    import time

    time.sleep(3)  # el SRI suele autorizar en segundos
    try:
        respuesta = consultar_autorizacion(clave)
    except Exception as error:  # noqa: BLE001
        print(f"\nNo se pudo consultar autorización: {error}")
        sys.exit(1)
    (SALIDA / f"{clave}-autorizacion.xml").write_text(respuesta, encoding="utf-8")
    resumir(respuesta, "AUTORIZACION")

    print(
        f"\nListo. Los XML quedaron en {SALIDA.resolve()}\n"
        "Si algo salió mal, pase el bloque de mensajes de arriba: el\n"
        "identificador del SRI dice exactamente qué campo rechazó.\n"
        "No hace falta mandar el certificado ni su clave."
    )


if __name__ == "__main__":
    main()
