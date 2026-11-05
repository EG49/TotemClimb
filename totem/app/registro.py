"""Registro técnico de la aplicación (logging).

No confundir con la bitácora. Son dos cosas distintas y conviene no
mezclarlas:

  * La **bitácora** es del negocio: quién cobró, quién anuló, quién
    cambió el IVA. La lee el administrador desde la aplicación y vive
    en la base de datos.
  * Este **registro** es técnico: qué se rompió, cuándo y con qué
    traza. Lo lee quien mantiene el sistema, y vive en un archivo.

Sin esto, cuando el gimnasio diga "ayer no se pudo cobrar" no hay
dónde mirar.

El archivo rota: al llegar al tamaño máximo se renombra y se abre uno
nuevo, conservando unas pocas copias. Así no crece sin control en el
disco del gimnasio.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from flask import request

FORMATO = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
FECHA = "%d/%m/%Y %H:%M:%S"


def configurar(app) -> None:
    """Deja el registro listo. Se llama una vez, al crear la app."""

    carpeta = app.config.get("LOG_DIR") or os.path.join(app.root_path, "..", "logs")
    carpeta = os.path.abspath(carpeta)
    os.makedirs(carpeta, exist_ok=True)

    archivo = os.path.join(carpeta, "totem.log")

    manejador = RotatingFileHandler(
        archivo,
        maxBytes=app.config.get("LOG_MAX_BYTES", 2_000_000),
        backupCount=app.config.get("LOG_COPIAS", 5),
        encoding="utf-8",
    )
    manejador.setFormatter(logging.Formatter(FORMATO, datefmt=FECHA))

    nivel = getattr(logging, str(app.config.get("LOG_NIVEL", "INFO")).upper(), logging.INFO)
    manejador.setLevel(nivel)

    # Evita duplicar manejadores si crear_app se llama dos veces, cosa
    # que pasa en las pruebas.
    if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        app.logger.addHandler(manejador)

    app.logger.setLevel(nivel)

    # En desarrollo el servidor ya escribe por consola; en producción,
    # con gunicorn, el archivo es la única fuente.
    app.logger.info(
        "Totem Climb Gym arrancó | registro en %s | nivel %s",
        archivo, logging.getLevelName(nivel),
    )

    _registrar_peticiones_lentas(app)


def _registrar_peticiones_lentas(app) -> None:
    """Deja constancia de las respuestas con error del servidor.

    Las peticiones normales no se registran: una por línea llenaría el
    archivo de ruido y escondería lo que importa.
    """

    @app.after_request
    def _anotar(respuesta):
        if respuesta.status_code >= 500:
            app.logger.error(
                "Respuesta %s en %s %s",
                respuesta.status_code, request.method, request.path,
            )
        return respuesta


# NOTA SOBRE VARIOS PROCESOS
# --------------------------
# Con gunicorn y más de un worker, todos escriben en el mismo archivo y
# la rotación puede pisarse entre procesos. Para el volumen del gimnasio
# no es un problema real, pero si alguna vez aparecen líneas cortadas,
# las salidas son: levantar gunicorn con un solo worker, o delegar la
# rotación a logrotate del sistema y usar WatchedFileHandler aquí.
