"""Fábrica de la aplicación Flask.

Arma la app, inicializa el pool de la base y registra los blueprints.
Tener esto como función (y no como una app global) permite crear
instancias independientes en las pruebas.
"""

import atexit
from datetime import timedelta

from flask import Flask
from flask_wtf.csrf import CSRFProtect

from app import errores, registro
from app.db import cerrar_pool, init_pool
from app.security import registrar_contexto
from config import EXPLICACION_SECRET_KEY, Config, revisar_secret_key


class SecretKeyInvalida(RuntimeError):
    """La SECRET_KEY falta o no sirve, y el sistema no debe arrancar."""


def crear_app(config_clase=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_clase)

    # Antes que nada: sin una SECRET_KEY propia, las sesiones son
    # falsificables. Se corta acá y no más adelante porque un sistema
    # que arranca y funciona con una clave conocida no da ninguna
    # señal de que algo ande mal -- se ve exactamente igual que uno
    # seguro. Mejor un error al arrancar, que se ve de inmediato.
    problema = revisar_secret_key(app.config.get("SECRET_KEY"))
    if problema:
        raise SecretKeyInvalida(
            f"\n\nLa SECRET_KEY {problema}.\n{EXPLICACION_SECRET_KEY}"
        )
    app.permanent_session_lifetime = timedelta(
        seconds=app.config["PERMANENT_SESSION_LIFETIME"]
    )

    # Sin esto, cualquier pagina que alguien abra con la sesion
    # iniciada puede mandar un cobro, un gasto o una anulacion a este
    # sistema: el navegador adjunta la cookie de sesion igual, venga
    # el formulario de donde venga, y para el servidor es
    # indistinguible de la persona pulsando el boton.
    #
    # En el PC del gimnasio, en su red local, el riesgo es chico. En
    # internet no: basta un enlace en un correo.
    #
    # Protege TODO lo que llegue por POST, incluido el login: un
    # atacante que puede hacerle iniciar sesion con SU cuenta ve
    # despues lo que la persona haga creyendo que es la suya.
    CSRFProtect(app)

    # Lo primero que se configura, para que cualquier fallo posterior
    # (incluido el de la base) quede registrado.
    registro.configurar(app)

    init_pool(
        app.config["DATABASE_URL"],
        min_size=app.config["DB_POOL_MIN"],
        max_size=app.config["DB_POOL_MAX"],
    )
    atexit.register(cerrar_pool)

    from app.routes import (
        auth,
        calendario,
        catalogo,
        clientes,
        cobrar,
        contabilidad,
        empleados,
        facturas,
        gastos,
        main,
        posibles,
    )

    # El color de texto legible para un fondo de ese mismo tono. Las
    # categorías del calendario las crea el gimnasio, así que el
    # contraste no se puede resolver eligiendo colores a mano.
    from app.colores import legible

    app.jinja_env.filters["color_legible"] = legible

    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(clientes.bp)
    app.register_blueprint(catalogo.bp)
    app.register_blueprint(cobrar.bp)
    app.register_blueprint(facturas.bp)
    app.register_blueprint(contabilidad.bp)
    app.register_blueprint(gastos.bp)
    app.register_blueprint(calendario.bp)
    app.register_blueprint(empleados.bp)
    app.register_blueprint(posibles.bp)

    registrar_contexto(app)
    errores.registrar(app)

    return app
