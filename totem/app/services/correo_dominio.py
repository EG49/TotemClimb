"""Revisa el dominio de un correo antes de que el gimnasio lo guarde.

Esto NO comprueba que el buzón exista. Eso no se puede comprobar
antes de enviar: el servidor del destinatario acepta el mensaje y
recién después devuelve el rebote. Lo que sí se puede saber al
instante es si el dominio existe y recibe correo, que es donde está
el error más común: alguien dicta su correo en el mostrador y se
escribe "gmial.com".

Dos revisiones, con intenciones distintas:

  * ``dominio_recibe_correo`` pregunta al DNS si el dominio tiene
    servidor de correo. Si no lo tiene, ese correo no le va a llegar
    a nadie nunca, y vale impedir que se guarde.

  * ``sugerir_dominio`` compara contra los dominios de siempre y
    propone la corrección. Esto solo avisa, nunca bloquea: un
    dominio raro puede ser perfectamente real, y nadie que escribió
    bien su correo debería quedarse sin registrarse porque este
    archivo no conocía su proveedor.

Regla que no se debe romper al tocar esto: **si el DNS no responde,
el correo se acepta**. La computadora del gimnasio se queda sin
internet de vez en cuando, y que no se pueda inscribir a un cliente
porque no hubo señal sería mucho peor que aceptar un correo con un
error de tipeo.
"""

from __future__ import annotations

import re
import time

try:  # pragma: no cover - depende del entorno
    import dns.exception
    import dns.resolver

    HAY_DNS = True
except ImportError:  # pragma: no cover
    HAY_DNS = False


# Cuánto se recuerda una respuesta del DNS. Los dominios de correo no
# aparecen y desaparecen de un minuto a otro, y sin esto se le
# preguntaría por gmail.com en cada registro.
VIDA_CACHE = 60 * 60  # una hora
ESPERA_DNS = 3.0  # segundos; el mostrador no puede quedarse colgado

# Dominios que se escriben todos los días en el gimnasio. La lista es
# corta a propósito: solo sirve para sugerir correcciones, y una lista
# larga de dominios poco frecuentes genera sugerencias equivocadas.
DOMINIOS_CONOCIDOS = (
    "gmail.com",
    "hotmail.com",
    "hotmail.es",
    "outlook.com",
    "outlook.es",
    "yahoo.com",
    "yahoo.es",
    "icloud.com",
    "live.com",
    "msn.com",
    "espol.edu.ec",
    "uees.edu.ec",
    "ucuenca.edu.ec",
    "cue.edu.ec",
)

# Errores de tipeo que no son una letra cambiada sino otra cosa: una
# terminación incompleta, o el dominio de otro país. La distancia de
# edición no los atrapa bien, así que van escritos.
EQUIVALENCIAS = {
    "gmail.co": "gmail.com",
    "gmail.cm": "gmail.com",
    "gmail.con": "gmail.com",
    "gmail.om": "gmail.com",
    "gmail.comm": "gmail.com",
    "gmail.es": "gmail.com",
    "hotmail.co": "hotmail.com",
    "hotmail.con": "hotmail.com",
    "hotmail.cm": "hotmail.com",
    "outlook.co": "outlook.com",
    "outlook.con": "outlook.com",
    "yahoo.co": "yahoo.com",
    "yahoo.con": "yahoo.com",
    "icloud.co": "icloud.com",
}

_cache: dict[str, tuple[bool, float]] = {}


def dominio_de(correo: str) -> str:
    """La parte de después del arroba, en minúsculas."""
    if not correo or "@" not in correo:
        return ""
    return correo.rsplit("@", 1)[1].strip().lower().rstrip(".")


def _distancia(a: str, b: str) -> int:
    """Cuántas letras hay que cambiar para pasar de una a otra.

    Damerau-Levenshtein: cuenta las cuatro operaciones, incluida la de
    cambiar dos letras contiguas de lugar. Esa última importa mucho
    aquí, porque "gmial" por "gmail" es el error de tipeo más común de
    todos y en Levenshtein a secas cuenta como dos cambios, igual que
    un dominio distinto.

    Escrito a mano para no traer una librería por quince líneas. Solo
    se usa con dominios, que son cortos.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    filas = [list(range(len(b) + 1))]
    for i, letra_a in enumerate(a, start=1):
        fila = [i]
        for j, letra_b in enumerate(b, start=1):
            costo = min(
                filas[i - 1][j] + 1,      # borrar
                fila[j - 1] + 1,          # insertar
                filas[i - 1][j - 1] + (letra_a != letra_b),  # cambiar
            )
            if (i > 1 and j > 1
                    and letra_a == b[j - 2] and a[i - 2] == letra_b):
                costo = min(costo, filas[i - 2][j - 2] + 1)  # trasponer
            fila.append(costo)
        filas.append(fila)
    return filas[-1][-1]


def sugerir_dominio(correo: str) -> str | None:
    """Devuelve el correo corregido si el dominio parece mal escrito.

    None si está bien escrito, si no se parece a ninguno conocido, o
    si el parecido es tan lejano que la sugerencia sería adivinanza.
    """
    dominio = dominio_de(correo)
    if not dominio or dominio in DOMINIOS_CONOCIDOS:
        return None

    usuario = correo.rsplit("@", 1)[0]

    if dominio in EQUIVALENCIAS:
        return f"{usuario}@{EQUIVALENCIAS[dominio]}"

    # Una sola letra de diferencia es casi seguro un error de tipeo;
    # dos ya es adivinar, salvo en dominios largos donde dos letras
    # sobre quince siguen siendo un tropiezo y no otro dominio.
    # Se recorre de más parecido a menos, para que "hotmail.cm" no
    # termine sugiriendo "hotmail.es" solo por estar antes en la lista.
    candidatos = sorted(
        DOMINIOS_CONOCIDOS, key=lambda d: (_distancia(dominio, d), d)
    )
    for conocido in candidatos:
        distancia = _distancia(dominio, conocido)
        if distancia == 1 or (distancia == 2 and len(conocido) >= 12):
            return f"{usuario}@{conocido}"
    return None


def dominio_recibe_correo(dominio: str) -> bool:
    """¿El dominio tiene servidor de correo?

    Devuelve True cuando no se puede averiguar: sin internet, sin
    dnspython o con el DNS lento, se prefiere aceptar el correo antes
    que impedir un registro.
    """
    dominio = (dominio or "").strip().lower().rstrip(".")
    if not dominio or not HAY_DNS:
        return True

    # Un dominio con forma inválida no hace falta consultarlo.
    if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)+$", dominio):
        return False

    if not _dns_confiable():
        return True

    recordado = _cache.get(dominio)
    if recordado and time.monotonic() - recordado[1] < VIDA_CACHE:
        return recordado[0]

    resultado = _preguntar_al_dns(dominio)
    if resultado is None:
        return True  # no se pudo averiguar: se acepta, no se recuerda
    _cache[dominio] = (resultado, time.monotonic())
    return resultado


# Un dominio que existe desde siempre y que va a seguir existiendo. Si
# el DNS dice que este no existe, el que miente es el DNS.
DOMINIO_DE_CONTROL = "gmail.com"
VIDA_CONTROL = 10 * 60
_control: tuple[bool, float] | None = None


def _dns_confiable() -> bool:
    """¿Se le puede creer a este DNS cuando dice que algo no existe?

    No siempre. Un portal cautivo, un DNS mal configurado o uno que
    responde NXDOMAIN a todo lo que no conoce harían que el sistema
    rechazara correos perfectamente buenos, y nadie en el mostrador
    podría inscribir a nadie. Antes de creerle una negativa se le
    pregunta por un dominio que con certeza existe: si falla esa, no
    se le cree ninguna.
    """
    global _control
    if _control and time.monotonic() - _control[1] < VIDA_CONTROL:
        return _control[0]

    confiable = _preguntar_al_dns(DOMINIO_DE_CONTROL) is True
    _control = (confiable, time.monotonic())
    return confiable


def _preguntar_al_dns(dominio: str) -> bool | None:
    """True/False si el DNS respondió; None si no se pudo preguntar."""
    resolutor = dns.resolver.Resolver()
    resolutor.timeout = ESPERA_DNS
    resolutor.lifetime = ESPERA_DNS

    try:
        resolutor.resolve(dominio, "MX")
        return True
    except dns.resolver.NoAnswer:
        # El dominio existe pero no declaró MX. El correo igual se
        # entrega al servidor del propio dominio si tiene dirección,
        # así lo manda la norma, y hay dominios pequeños que
        # funcionan así.
        pass
    except dns.resolver.NXDOMAIN:
        return False  # el dominio no existe
    except (dns.exception.Timeout, dns.resolver.NoNameservers,
            dns.exception.DNSException, OSError):
        return None  # no se pudo averiguar

    for tipo in ("A", "AAAA"):
        try:
            resolutor.resolve(dominio, tipo)
            return True
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            continue
        except (dns.exception.Timeout, dns.resolver.NoNameservers,
                dns.exception.DNSException, OSError):
            return None
    return False


def olvidar_cache() -> None:
    """Vacía lo recordado. Para las pruebas."""
    global _control
    _cache.clear()
    _control = None
