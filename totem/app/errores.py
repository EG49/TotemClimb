"""Páginas de error propias.

Sin esto, un enlace roto muestra la pantalla pelada de Flask y un fallo
del servidor muestra "Internal Server Error" en texto crudo. Ninguna de
las dos le dice nada útil a quien está en el mostrador.

Las plantillas extienden la base, así que conservan el menú y la marca.
Eso es seguro incluso cuando la base de datos está caída, porque el
empleado de la sesión se lee de la cookie, no de la base.
"""

from flask import render_template, request


def registrar(app) -> None:
    """Conecta los manejadores. Se llama una vez, al crear la app."""

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
        return render_template("errores/500.html"), 500
