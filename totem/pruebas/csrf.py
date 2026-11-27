"""Ningún formulario puede mandar un POST sin su token.

El token es lo que distingue un formulario de este sistema de uno que
llegó de otro lado. Sin él, cualquier página que alguien abra con la
sesión iniciada puede mandar un cobro, un gasto o una anulación: el
navegador adjunta la cookie de sesión igual, venga el formulario de
donde venga, y para el servidor es indistinguible de la persona
pulsando el botón.

Esta prueba existe sobre todo por el formulario que todavía no está
escrito. Poner el token en los cuarenta y cuatro de hoy es un rato;
acordarse el día que se agregue el siguiente es lo que no pasa. Si
alguien escribe un formulario sin token, esto falla antes de que
llegue al gimnasio.

    python -m pruebas.csrf
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app                  # noqa: E402

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


PLANTILLAS = Path(__file__).resolve().parent.parent / "app" / "templates"
APERTURA = re.compile(r"<form\b[^>]*?>", re.IGNORECASE | re.DOTALL)
CIERRE = re.compile(r"</form\s*>", re.IGNORECASE)

print("\nTODOS LOS FORMULARIOS LLEVAN SU TOKEN")

sin_token, total = [], 0
for archivo in sorted(PLANTILLAS.rglob("*.html")):
    texto = archivo.read_text(encoding="utf-8")
    for apertura in APERTURA.finditer(texto):
        if not re.search(r'method\s*=\s*["\']?post', apertura.group(0),
                         re.IGNORECASE):
            continue
        total += 1
        # Se busca dentro de ESTE formulario y no en todo el archivo:
        # una plantilla con dos formularios, uno con token y otro sin,
        # pasaría si se buscara en el archivo entero. Es justo el caso
        # que hay que atrapar.
        cierre = CIERRE.search(texto, apertura.end())
        cuerpo = texto[apertura.end():cierre.start() if cierre else len(texto)]
        if "csrf_token" not in cuerpo:
            linea = texto.count("\n", 0, apertura.start()) + 1
            sin_token.append(
                f"{archivo.relative_to(PLANTILLAS)}:{linea}"
            )

revisar(f"los {total} formularios POST lo llevan",
        not sin_token, ", ".join(sin_token[:6]))
revisar("y hay formularios que revisar", total > 0,
        "no se encontró ninguno: la búsqueda no sirve")

print("\nY EL SERVIDOR LOS RECHAZA SI NO LO TRAEN")
# Lo de arriba mira las plantillas. Esto mira si el servidor de
# verdad lo exige: una plantilla puede llevar el token y el servidor
# no comprobarlo, y entonces el token no sirve de nada.
app = crear_app()
app.config["WTF_CSRF_ENABLED"] = True
with app.test_client() as cliente:
    respuesta = cliente.post("/login", data={
        "usuario": "admin", "password": "Prueba12345",
    })
    revisar("un login sin token no entra",
            respuesta.status_code == 400,
            f"respondio {respuesta.status_code}, deberia ser 400")

print("\nY LOS GET SIGUEN ABIERTOS")
# Si el token se exigiera también en GET, el sistema no se podría ni
# abrir. Se comprueba que no se haya pasado de celoso.
with app.test_client() as cliente:
    revisar("la pantalla de login abre normal",
            cliente.get("/login").status_code == 200)

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
