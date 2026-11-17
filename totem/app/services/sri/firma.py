"""Firma XAdES-BES del comprobante, con el certificado .p12.

Esto es un adaptador delgado sobre la librería `xadessri`
(github.com/jsonfm/xades-bes-sri). La firma misma no se reimplementa:
XAdES-BES tiene una estructura exacta y hacerla a mano es la forma más
común de que el SRI rechace comprobantes.

Por qué esa librería y no la otra
---------------------------------
La alternativa más citada, `xades-bes-sri-ec`, NO sirve en Windows, y
el gimnasio corre en Windows. Dos razones, ninguna de versiones:

  - clava sus dependencias en `cryptography==3.2.1`, `pyOpenSSL==20.0.1`
    y `lxml==4.6.3`, de 2020 y 2021. Ninguna compila en Python 3.12:
    `lxml 4.6.3` falla buscando `longintrepr.h`, que dejó de existir
    en Python 3.11.
  - llama por consola a `xmllint` y a `openssl` con subprocess. En
    Windows esos programas no vienen instalados.

`xadessri` usa `cryptography` y `lxml` modernos, los dos con rueda
precompilada para Windows, y no ejecuta ningún programa externo.

El detalle que hay que respetar
-------------------------------
`xadessri.sign_xml` no acepta un XML que traiga la declaración
`<?xml version="1.0" encoding="UTF-8"?>`, y devuelve el documento sin
ella. El SRI, en cambio, la exige en el archivo que se le envía. Así
que acá se la quita antes de firmar y se la repone después. Si alguien
saca esa parte, el SRI rechaza por estructura.

La firma queda con canonización inclusiva (REC-xml-c14n-20010315) y
RSA-SHA1, que es lo que corresponde al esquema del SRI.
"""

from pathlib import Path

DECLARACION = '<?xml version="1.0" encoding="UTF-8"?>'


class ErrorFirma(RuntimeError):
    """No se pudo firmar el comprobante."""


def _sin_declaracion(xml: str) -> str:
    recortado = xml.lstrip()
    if recortado.startswith("<?xml"):
        _, _, resto = recortado.partition("?>")
        return resto.lstrip()
    return recortado


def _con_declaracion(xml: str) -> str:
    recortado = xml.lstrip()
    if recortado.startswith("<?xml"):
        return recortado
    return f"{DECLARACION}\n{recortado}"


def firmar(xml: str, ruta_p12: str | Path, clave_p12: str) -> str:
    """Devuelve el XML firmado, listo para enviar al SRI.

    `ruta_p12` apunta al certificado en el disco de la máquina donde
    corre esto. El certificado no viaja: se lee local y nada más.
    """
    try:
        import xadessri
    except ImportError as error:
        raise ErrorFirma(
            "falta la librería de firma. Instálela con:\n"
            "  pip install -r requirements.txt"
        ) from error

    ruta = Path(ruta_p12)
    if not ruta.exists():
        raise ErrorFirma(f"no encuentro el certificado en {ruta}")

    try:
        firmado = xadessri.sign_xml(
            str(ruta), clave_p12, _sin_declaracion(xml), read_file=True
        )
    except ValueError as error:
        # El error típico es la clave equivocada, y el mensaje de la
        # librería no lo dice con claridad.
        raise ErrorFirma(
            "no se pudo abrir el certificado. Lo más probable es que "
            f"SRI_P12_CLAVE esté mal. Detalle: {error}"
        ) from error
    except Exception as error:  # noqa: BLE001
        raise ErrorFirma(f"la firma falló: {type(error).__name__}: {error}") from error

    if not firmado or "SignatureValue" not in firmado:
        raise ErrorFirma("la librería devolvió un XML sin firma")

    return _con_declaracion(firmado)
