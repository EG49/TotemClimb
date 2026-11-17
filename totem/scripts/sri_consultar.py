"""Pregunta al SRI por el estado de un comprobante, por su clave de acceso.

Para que sirve
--------------
En el ambiente de PRUEBAS los comprobantes no aparecen en el portal
del SRI: no se conservan ahi y no tienen validez tributaria. La unica
forma de saber si llegaron y en que estado quedaron es preguntarle al
servicio de autorizacion, que es lo que hace este script.

En PRODUCCION tambien sirve, pero ahi ademas se los puede ver en
SRI en Linea -> Facturacion Electronica -> Produccion -> Consultas.

Como se corre, desde la carpeta totem:

    python -m scripts.sri_consultar 1611202601179001234500120010020009000011234567813

    python -m scripts.sri_consultar <clave> --produccion

Se puede preguntar las veces que haga falta: la consulta no emite ni
cambia nada.

AVISO: el envio por red no pudo probarse al escribirlo, porque el
entorno de desarrollo no alcanza los servidores del SRI.
"""

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.sri.clave_acceso import descomponer, verificar

URL = {
    "pruebas": (
        "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/"
        "AutorizacionComprobantesOffline"
    ),
    "produccion": (
        "https://cel.sri.gob.ec/comprobantes-electronicos-ws/"
        "AutorizacionComprobantesOffline"
    ),
}

# Lo que significa cada estado, en palabras.
ESTADOS = {
    "AUTORIZADO": "El SRI lo acepto. El comprobante es valido.",
    "NO AUTORIZADO": (
        "Llego pero el SRI lo rechazo. El motivo esta en los mensajes de "
        "abajo."
    ),
    "EN PROCESO": (
        "Llego y todavia no se resolvio. Vuelva a consultar en unos "
        "segundos."
    ),
    "RECHAZADA": "Llego y fue rechazado en la recepcion.",
    "DEVUELTA": "Llego y fue devuelto: hay un problema de estructura.",
}


def consultar(clave: str, ambiente: str) -> str:
    import urllib.request

    sobre = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv='
        '"http://schemas.xmlsoap.org/soap/envelope/">'
        "<soapenv:Header/><soapenv:Body>"
        '<ec:autorizacionComprobante '
        'xmlns:ec="http://ec.gob.sri.ws.autorizacion">'
        f"<claveAccesoComprobante>{clave}</claveAccesoComprobante>"
        "</ec:autorizacionComprobante>"
        "</soapenv:Body></soapenv:Envelope>"
    )
    peticion = urllib.request.Request(
        URL[ambiente],
        data=sobre.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""},
    )
    with urllib.request.urlopen(peticion, timeout=60) as respuesta:
        return respuesta.read().decode("utf-8", errors="replace")


def informar(respuesta: str) -> None:
    try:
        raiz = ET.fromstring(respuesta)
    except ET.ParseError:
        print("\nEl SRI contesto algo que no es XML:\n")
        print(respuesta[:1500])
        return

    autorizaciones = list(raiz.iter("autorizacion"))
    if not autorizaciones:
        # Sin nodo de autorizacion: el SRI no tiene ese comprobante.
        print(
            "\nNO LLEGO.\n\n"
            "El SRI no tiene ningun comprobante con esa clave de acceso.\n"
            "Si acaba de enviarlo, espere unos segundos y vuelva a\n"
            "consultar. Si sigue igual, el envio a recepcion no se\n"
            "completo: revise la salida de scripts/sri_prueba.py."
        )
        return

    for autorizacion in autorizaciones:
        estado = (autorizacion.findtext("estado") or "").strip()
        print(f"\nESTADO: {estado or '(vacio)'}")
        if estado.upper() in ESTADOS:
            print(f"  {ESTADOS[estado.upper()]}")

        for etiqueta, titulo in (
            ("numeroAutorizacion", "Numero de autorizacion"),
            ("fechaAutorizacion", "Fecha de autorizacion"),
            ("ambiente", "Ambiente"),
        ):
            valor = (autorizacion.findtext(etiqueta) or "").strip()
            if valor:
                print(f"  {titulo}: {valor}")

        mensajes = list(autorizacion.iter("mensaje"))
        if mensajes:
            print("\n  Mensajes del SRI:")
            for nodo in mensajes:
                partes = []
                for hijo in ("identificador", "mensaje", "tipo",
                             "informacionAdicional"):
                    texto = (nodo.findtext(hijo) or "").strip()
                    if texto:
                        partes.append(f"{hijo}: {texto}")
                if not partes and (nodo.text or "").strip():
                    partes.append(nodo.text.strip())
                print("    - " + "\n      ".join(partes))


def main() -> None:
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(argumentos) != 1:
        print(__doc__)
        sys.exit(1)

    clave = argumentos[0].strip().replace(" ", "")
    ambiente = "produccion" if "--produccion" in sys.argv else "pruebas"

    if not verificar(clave):
        print(
            f"\nEsa clave de acceso no es consistente ({len(clave)} "
            "caracteres).\n"
            "Son 49 digitos y el ultimo es un verificador: si esta mal\n"
            "copiada, no hace falta preguntarle al SRI."
        )
        sys.exit(1)

    partes = descomponer(clave)
    ambiente_clave = "pruebas" if partes["ambiente"] == "1" else "produccion"
    if ambiente_clave != ambiente:
        print(
            f"\nOJO: la clave dice que es del ambiente de {ambiente_clave}, "
            f"y se esta consultando {ambiente}.\n"
            "Se consulta igual, pero lo mas probable es que no aparezca."
        )

    fecha = partes["fecha_emision"]
    print(
        f"\nConsultando en {ambiente.upper()}\n"
        f"  Clave:       {clave}\n"
        f"  Emitida el:  {fecha[:2]}/{fecha[2:4]}/{fecha[4:]}\n"
        f"  Secuencial:  {int(partes['secuencial'])}\n"
        f"  Punto:       {partes['establecimiento']}-{partes['punto_emision']}"
    )

    try:
        respuesta = consultar(clave, ambiente)
    except Exception as error:  # noqa: BLE001
        print(f"\nNo se pudo llegar al SRI: {error}")
        print("Revise la conexion a internet.")
        sys.exit(1)

    informar(respuesta)


if __name__ == "__main__":
    main()
