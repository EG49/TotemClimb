"""La pantalla de error dice qué migración falta.

Bajar una versión nueva y olvidar correr la migración es lo más
normal del mundo. Antes eso daba un 500 pelado y había que leer la
traza en la consola para enterarse; en la máquina del gimnasio nadie
mira la consola.

Lo que se comprueba acá es que el archivo que se nombra sea el que de
verdad crea esa columna, y que un fallo que no tiene nada que ver no
se disfrace de migración pendiente.

    python -m pruebas.migracion_faltante
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.errores import _que_migracion_falta  # noqa: E402

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


class ErrorFalso(Exception):
    """Imita el error de psycopg sin necesitar una base rota."""


class UndefinedColumn(ErrorFalso):
    pass


class UndefinedTable(ErrorFalso):
    pass


print("\nSE RECONOCE LA COLUMNA QUE FALTA")

# El mensaje real de psycopg en español, tal cual salió en la máquina
# del gimnasio.
caso = UndefinedColumn("no existe la columna f.contifico_planes_en\n"
                       "LINE 14: AND f.contifico_planes_en IS NULL")
resultado = _que_migracion_falta(caso)
revisar("se saca el nombre sin el alias de la tabla",
        resultado is not None and resultado[0] == "contifico_planes_en",
        str(resultado))
revisar("y se nombra el archivo que la crea",
        resultado is not None and resultado[1] == "alter-contifico.sql",
        str(resultado))

# En inglés, que es como sale si el servidor está en otro idioma.
caso = UndefinedColumn('column "contifico_productos_por" does not exist')
resultado = _que_migracion_falta(caso)
revisar("también con el mensaje en inglés",
        resultado is not None and resultado[1] == "alter-contifico.sql",
        str(resultado))

print("\nY NO SE INVENTA UNA MIGRACIÓN DONDE NO LA HAY")

revisar("un fallo cualquiera no se disfraza de migración",
        _que_migracion_falta(ValueError("se cayó la red")) is None)
revisar("una columna que no crea ninguna migración se admite sin archivo",
        _que_migracion_falta(
            UndefinedColumn("no existe la columna f.inventada_123")
        ) == ("inventada_123", ""))

print("\nCADA MIGRACIÓN SE ENCUENTRA A SÍ MISMA")

# Si una migración agrega una columna y el buscador no la encuentra,
# el día que esa sea la que falte el mensaje no va a servir. Se
# comprueban todas, no solo la del momento.
import re  # noqa: E402

carpeta = Path(__file__).resolve().parent.parent / "Sql"
revisadas = 0
for archivo in sorted(carpeta.glob("alter-*.sql")):
    contenido = archivo.read_text(encoding="utf-8", errors="ignore")
    columnas = re.findall(r"ADD COLUMN (?:IF NOT EXISTS )?(\w+)", contenido,
                          re.IGNORECASE)
    for columna in columnas[:2]:        # con dos por archivo alcanza
        revisadas += 1
        hallado = _que_migracion_falta(
            UndefinedColumn(f"no existe la columna f.{columna}")
        )
        # Puede estar en más de un archivo (una columna que se agrega y
        # luego se amplía); basta con que nombre alguno que la mencione.
        nombrado = hallado[1] if hallado else ""
        bien = bool(nombrado) and columna in (
            carpeta / nombrado
        ).read_text(encoding="utf-8", errors="ignore")
        revisar(f"{archivo.name} → {columna}", bien, str(hallado))

if revisadas == 0:
    revisar("hay migraciones que revisar", False, "no se encontró ninguna")

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
