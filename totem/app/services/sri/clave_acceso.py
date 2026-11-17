"""Clave de acceso de los comprobantes electrónicos del SRI.

En el esquema offline la clave de acceso no la da el SRI: la genera el
emisor, y es la que identifica al comprobante de aquí en adelante. Con
ella se consulta la autorización, y con ella el cliente verifica la
factura en el portal del SRI. Si sale mal, el comprobante se rechaza.

Son 49 dígitos, en este orden (ficha técnica del esquema offline):

      8   fecha de emisión, ddmmaaaa
      2   tipo de comprobante (01 factura, 04 nota de crédito)
     13   RUC del emisor
      1   ambiente (1 pruebas, 2 producción)
      6   serie: establecimiento (3) + punto de emisión (3)
      9   secuencial
      8   código numérico
      1   tipo de emisión (1 normal)
      1   dígito verificador, módulo 11
     ---
     49

Para el método de autorización offline solo existe el tipo de emisión
normal, así que TIPO_EMISION_NORMAL es el único valor que se usa.
"""

from datetime import date

LARGO_CLAVE = 49

AMBIENTE_PRUEBAS = "1"
AMBIENTE_PRODUCCION = "2"

TIPO_EMISION_NORMAL = "1"

FACTURA = "01"
NOTA_DE_CREDITO = "04"


class ErrorClaveAcceso(ValueError):
    """Un dato no sirve para armar la clave de acceso."""


def digito_verificador(cuarenta_y_ocho: str) -> str:
    """El dígito verificador módulo 11 de los primeros 48 dígitos.

    Los pesos son 2,3,4,5,6,7 y se aplican de DERECHA a izquierda,
    repitiéndose. Al residuo se lo resta de 11, y los dos casos de
    borde son los que se equivocan siempre: 11 da 0 y 10 da 1.
    """
    if len(cuarenta_y_ocho) != LARGO_CLAVE - 1:
        raise ErrorClaveAcceso(
            f"el dígito verificador se calcula sobre {LARGO_CLAVE - 1} "
            f"dígitos, llegaron {len(cuarenta_y_ocho)}"
        )
    if not cuarenta_y_ocho.isdigit():
        raise ErrorClaveAcceso("la clave de acceso solo admite dígitos")

    total = 0
    peso = 2
    for caracter in reversed(cuarenta_y_ocho):
        total += int(caracter) * peso
        peso = 2 if peso == 7 else peso + 1

    resto = total % 11
    verificador = 11 - resto
    if verificador == 11:
        return "0"
    if verificador == 10:
        return "1"
    return str(verificador)


def _exacto(valor: str, largo: int, nombre: str) -> str:
    texto = str(valor).strip()
    if not texto.isdigit():
        raise ErrorClaveAcceso(f"{nombre} debe ser numérico, llegó {valor!r}")
    if len(texto) > largo:
        raise ErrorClaveAcceso(
            f"{nombre} no cabe en {largo} dígitos, llegó {valor!r}"
        )
    return texto.zfill(largo)


def generar(
    *,
    fecha_emision: date,
    tipo_comprobante: str,
    ruc: str,
    ambiente: str,
    establecimiento: str,
    punto_emision: str,
    secuencial: int,
    codigo_numerico: str,
) -> str:
    """Arma la clave de acceso de 49 dígitos.

    El código numérico es libre: ocho dígitos que el emisor elige. Acá
    se lo pide en lugar de sortearlo adentro, porque la clave tiene que
    poder regenerarse igual a partir de la factura guardada. Si se
    sorteara aquí, un reintento daría una clave distinta y el SRI vería
    dos comprobantes donde hay uno.
    """
    if tipo_comprobante not in (FACTURA, NOTA_DE_CREDITO):
        raise ErrorClaveAcceso(
            f"tipo de comprobante no contemplado: {tipo_comprobante!r}"
        )
    if ambiente not in (AMBIENTE_PRUEBAS, AMBIENTE_PRODUCCION):
        raise ErrorClaveAcceso(f"ambiente inválido: {ambiente!r}")
    if secuencial < 1:
        raise ErrorClaveAcceso("el secuencial arranca en 1")

    ruc = str(ruc).strip()
    if len(ruc) != 13 or not ruc.isdigit():
        raise ErrorClaveAcceso(f"el RUC debe tener 13 dígitos, llegó {ruc!r}")

    cuerpo = (
        fecha_emision.strftime("%d%m%Y")
        + tipo_comprobante
        + ruc
        + ambiente
        + _exacto(establecimiento, 3, "establecimiento")
        + _exacto(punto_emision, 3, "punto de emisión")
        + _exacto(secuencial, 9, "secuencial")
        + _exacto(codigo_numerico, 8, "código numérico")
        + TIPO_EMISION_NORMAL
    )

    # Una red de seguridad: si algún campo cambia de largo, es mejor
    # enterarse acá que por un rechazo del SRI.
    if len(cuerpo) != LARGO_CLAVE - 1:
        raise ErrorClaveAcceso(
            f"la clave quedó de {len(cuerpo) + 1} dígitos y debe tener "
            f"{LARGO_CLAVE}"
        )

    return cuerpo + digito_verificador(cuerpo)


def verificar(clave: str) -> bool:
    """Si una clave de acceso de 49 dígitos es consistente."""
    clave = str(clave).strip()
    if len(clave) != LARGO_CLAVE or not clave.isdigit():
        return False
    return digito_verificador(clave[:-1]) == clave[-1]


def descomponer(clave: str) -> dict:
    """Los campos de una clave de acceso, para mostrarla o auditarla."""
    if not verificar(clave):
        raise ErrorClaveAcceso("la clave de acceso no es consistente")
    return {
        "fecha_emision": clave[0:8],
        "tipo_comprobante": clave[8:10],
        "ruc": clave[10:23],
        "ambiente": clave[23:24],
        "establecimiento": clave[24:27],
        "punto_emision": clave[27:30],
        "secuencial": clave[30:39],
        "codigo_numerico": clave[39:47],
        "tipo_emision": clave[47:48],
        "verificador": clave[48:49],
    }
