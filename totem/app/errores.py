"""Páginas de error propias.

Sin esto, un enlace roto muestra la pantalla pelada de Flask y un fallo
del servidor muestra "Internal Server Error" en texto crudo. Ninguna de
las dos le dice nada útil a quien está en el mostrador.

Las plantillas extienden la base, así que conservan el menú y la marca.
Eso es seguro incluso cuando la base de datos está caída, porque el
empleado de la sesión se lee de la cookie, no de la base.
"""

import re
from pathlib import Path

from flask import render_template, request

# Dónde viven las migraciones, para poder decir cuál falta.
CARPETA_SQL = Path(__file__).resolve().parent.parent / "Sql"


def _que_migracion_falta(error) -> tuple[str, str] | None:
    """Si el fallo es una columna o tabla que no existe, de dónde sale.

    Bajar una rama y olvidar la migración es lo más normal del mundo, y
    hasta ahora eso daba una pantalla de error sin pistas: había que
    leer la traza en la consola para enterarse. Peor todavía en la
    máquina del gimnasio, donde nadie mira la consola.

    Se busca el nombre en los archivos de Sql en lugar de llevar una
    lista: una lista hay que acordarse de actualizarla con cada
    migración nueva, y la que se olvida es justo la que hace falta.
    """
    nombre_error = type(error).__name__
    if nombre_error not in ("UndefinedColumn", "UndefinedTable"):
        return None

    texto = str(error)
    hallado = re.search(r'no existe la columna "?([\w.]+)"?', texto) \
        or re.search(r'column "?([\w.]+)"? does not exist', texto) \
        or re.search(r'no existe la relación "?([\w.]+)"?', texto) \
        or re.search(r'relation "?([\w.]+)"? does not exist', texto)
    if not hallado:
        return None

    # Viene como f.contifico_planes_en: lo que se busca es el nombre.
    que_falta = hallado.group(1).split(".")[-1]
    if not CARPETA_SQL.is_dir():
        return que_falta, ""

    for archivo in sorted(CARPETA_SQL.glob("*.sql")):
        try:
            contenido = archivo.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(rf"(ADD COLUMN[^;]*?|CREATE TABLE[^;]*?)\b{re.escape(que_falta)}\b",
                     contenido, re.IGNORECASE | re.DOTALL):
            return que_falta, archivo.name
    return que_falta, ""


def registrar(app) -> None:
    """Conecta los manejadores. Se llama una vez, al crear la app."""

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def _token_vencido(error):
        """El formulario se mandó sin un token válido.

        Casi siempre no es un ataque: es alguien que dejó la pantalla
        abierta, se le venció la sesión y le dio a guardar. Un 400
        pelado en esa situación parece que el sistema se rompió, y lo
        que hace falta es decirle qué pasó y cómo seguir.

        Se registra igual, porque la otra posibilidad -- que sí lo
        sea -- conviene que quede anotada.
        """
        app.logger.warning(
            "Formulario rechazado por token invalido en %s %s: %s",
            request.method, request.path, error.description,
        )
        return render_template("errores/token.html"), 400

    @app.errorhandler(404)
    def _no_encontrado(error):
        # Un 404 es normal: alguien escribió mal una dirección o siguió
        # un enlace viejo. Se anota como aviso, no como error.
        app.logger.warning("404 en %s", request.path)
        return render_template("errores/404.html"), 404

    @app.errorhandler(500)
    @app.errorhandler(Exception)
    def _fallo_interno(error):
        # Las excepciones HTTP con su propio código (403, 405...) se
        # dejan pasar tal cual; aquí solo se atienden los fallos reales.
        codigo = getattr(error, "code", None)
        if codigo and codigo != 500:
            return error

        # exception() guarda la traza completa en el archivo. Es lo
        # único que permite diagnosticar después.
        app.logger.exception("Fallo no controlado en %s %s", request.method, request.path)

        falta = _que_migracion_falta(error)
        if falta:
            que, archivo = falta
            app.logger.error(
                "Parece una migración sin correr: falta «%s»%s",
                que, f", la crea {archivo}" if archivo else "",
            )
            return render_template(
                "errores/500.html", falta_migracion=que, archivo_sql=archivo,
            ), 500

        return render_template("errores/500.html"), 500
