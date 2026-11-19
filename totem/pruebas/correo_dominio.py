"""Lo que se revisa del correo antes de guardarlo.

Dos cosas distintas, que conviene no confundir:

  * el dominio existe y recibe correo -> si no, se rechaza al guardar
  * el dominio parece mal escrito -> solo se sugiere, nunca se bloquea

Ninguna de las dos comprueba que el buzon exista. Eso no se puede
antes de enviar; para eso esta el lector de rebotes.

Lo que mas se prueba aqui no es que detecte los dominios malos sino
lo contrario: que **no rechace correos buenos**. Un dominio raro pero
real, un DNS caido, una computadora sin internet, un DNS que miente
-- en todos esos casos el correo tiene que pasar. Rechazar un correo
bueno significa que alguien en el mostrador no puede inscribir a un
cliente, y eso es peor que dejar pasar un correo con un error.

Las consultas al DNS van contra un resolutor de mentira, para que las
pruebas no dependan de que haya internet ni de que gmail.com siga
existiendo.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dns.exception  # noqa: E402
import dns.resolver  # noqa: E402

from app.services import correo_dominio  # noqa: E402
from app.services.correo_dominio import (  # noqa: E402
    dominio_de, dominio_recibe_correo, olvidar_cache, sugerir_dominio,
)

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


class ResolutorFalso:
    """Responde lo que diga el libreto, sin tocar la red.

    El libreto es {(dominio, tipo): resultado}, donde el resultado es
    "ok" o la excepcion que se debe lanzar. Lo que no este en el
    libreto no existe.
    """

    libreto: dict = {}
    consultas: list = []

    def __init__(self):
        self.timeout = 0
        self.lifetime = 0

    def resolve(self, dominio, tipo):
        ResolutorFalso.consultas.append((dominio, tipo))
        respuesta = ResolutorFalso.libreto.get((dominio, tipo), "nxdomain")
        if respuesta == "ok":
            return ["algo"]
        if respuesta == "nxdomain":
            raise dns.resolver.NXDOMAIN(f"no existe: {dominio}")
        raise respuesta


def montar(libreto, control=True):
    """Pone el resolutor falso con ese libreto. control: si gmail.com responde."""
    if control:
        libreto = {("gmail.com", "MX"): "ok", **libreto}
    ResolutorFalso.libreto = libreto
    ResolutorFalso.consultas = []
    correo_dominio.dns.resolver.Resolver = ResolutorFalso
    olvidar_cache()


original = dns.resolver.Resolver

print("\nNO SE RECHAZA UN CORREO BUENO")
# Esto es lo que importa de verdad.

montar({("empresa.ec", "MX"): "ok"})
revisar("un dominio con servidor de correo pasa",
        dominio_recibe_correo("empresa.ec"))

montar({("chiquito.ec", "MX"): dns.resolver.NoAnswer(),
        ("chiquito.ec", "A"): "ok"})
revisar("sin MX pero con direccion, igual pasa",
        dominio_recibe_correo("chiquito.ec"),
        "la norma entrega al propio dominio si no declaro MX")

montar({("empresa.ec", "MX"): dns.exception.Timeout()})
revisar("si el DNS no contesta a tiempo, pasa",
        dominio_recibe_correo("empresa.ec"))

montar({("empresa.ec", "MX"): dns.resolver.NoNameservers("sin servidores")})
revisar("si no hay a quien preguntar, pasa",
        dominio_recibe_correo("empresa.ec"))

montar({("empresa.ec", "MX"): OSError("sin red")})
revisar("sin internet, pasa", dominio_recibe_correo("empresa.ec"))

# Un DNS que responde "no existe" a todo -- portal cautivo, DNS mal
# configurado -- bloquearia todos los registros del gimnasio.
montar({}, control=False)
revisar("si el DNS miente sobre gmail.com, no se le cree nada",
        dominio_recibe_correo("empresa.ec"))

correo_dominio.HAY_DNS = False
olvidar_cache()
revisar("sin dnspython instalado, pasa", dominio_recibe_correo("empresa.ec"))
correo_dominio.HAY_DNS = True

print("\nSE RECHAZA LO QUE NO LE VA A LLEGAR A NADIE")
montar({})
revisar("un dominio que no existe se rechaza",
        not dominio_recibe_correo("dominio-que-no-existe-99.ec"))

montar({("vacio.ec", "MX"): dns.resolver.NoAnswer(),
        ("vacio.ec", "A"): dns.resolver.NoAnswer(),
        ("vacio.ec", "AAAA"): dns.resolver.NoAnswer()})
revisar("existe pero no recibe correo, se rechaza",
        not dominio_recibe_correo("vacio.ec"))

montar({})
revisar("un dominio con forma invalida se rechaza sin consultar",
        not dominio_recibe_correo("sin-punto")
        and ("sin-punto", "MX") not in ResolutorFalso.consultas)

print("\nNO SE LE PREGUNTA DOS VECES AL DNS POR LO MISMO")
montar({("empresa.ec", "MX"): "ok"})
dominio_recibe_correo("empresa.ec")
antes = len(ResolutorFalso.consultas)
for _ in range(5):
    dominio_recibe_correo("empresa.ec")
revisar("la respuesta se recuerda",
        len(ResolutorFalso.consultas) == antes,
        f"{len(ResolutorFalso.consultas) - antes} consultas de mas")

montar({("empresa.ec", "MX"): dns.exception.Timeout()})
dominio_recibe_correo("empresa.ec")
antes = len(ResolutorFalso.consultas)
dominio_recibe_correo("empresa.ec")
revisar("un 'no se pudo averiguar' NO se recuerda",
        len(ResolutorFalso.consultas) > antes,
        "si se recordara, una falla de red de un segundo valdria una hora")

correo_dominio.dns.resolver.Resolver = original
olvidar_cache()

print("\nSE SUGIERE LA CORRECCION DEL DOMINIO")
casos = [
    ("ana@gmial.com", "ana@gmail.com", "dos letras cambiadas de lugar"),
    ("ana@gmail.cm", "ana@gmail.com", "falta una letra"),
    ("ana@gmail.con", "ana@gmail.com", "n por m"),
    ("ana@hotmial.com", "ana@hotmail.com", "transposicion"),
    ("ana@outlok.com", "ana@outlook.com", "falta una o"),
    ("ana@yaho.com", "ana@yahoo.com", "falta una o"),
    ("ana@espol.edu.e", "ana@espol.edu.ec", "dominio largo incompleto"),
]
for escrito, esperado, por_que in casos:
    revisar(f"{escrito} -> {esperado}  ({por_que})",
            sugerir_dominio(escrito) == esperado, sugerir_dominio(escrito))

print("\nY NO SE SUGIERE NADA CUANDO ESTA BIEN")
# Sugerir de mas es peor que no sugerir: el del mostrador va a hacer
# caso, y le va a cambiar el correo bueno a un cliente.
for bueno in ["ana@gmail.com", "ana@hotmail.es", "ana@ucuenca.edu.ec",
              "ana@mipropiodominio.ec", "ana@totemclimbgym.com",
              "ana@empresa-de-ana.com.ec", "ana@a.ec"]:
    revisar(f"{bueno} se deja en paz", sugerir_dominio(bueno) is None,
            sugerir_dominio(bueno))

revisar("un correo sin arroba no revienta", sugerir_dominio("ana") is None)
revisar("vacio no revienta", sugerir_dominio("") is None)
revisar("dominio_de con texto raro", dominio_de("sin arroba") == "")
revisar("dominio_de normaliza", dominio_de("Ana@GMAIL.com.") == "gmail.com")

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
