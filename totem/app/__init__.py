"""Fábrica de la aplicación Flask.

Arma la app, inicializa el pool de la base y registra los blueprints.
Tener esto como función (y no como una app global) permite crear
instancias independientes en las pruebas.
"""

import atexit
from datetime import timedelta

from flask import Flask

from app.db import cerrar_pool, init_pool
from app.security import registrar_contexto
from config import Config


def crear_app(config_clase=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_clase)
    app.permanent_session_lifetime = timedelta(
        seconds=app.config["PERMANENT_SESSION_LIFETIME"]
    )

    init_pool(
        app.config["DATABASE_URL"],
        min_size=app.config["DB_POOL_MIN"],
        max_size=app.config["DB_POOL_MAX"],
    )
    atexit.register(cerrar_pool)

    from app.routes import auth, catalogo, clientes, main

    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(clientes.bp)
    app.register_blueprint(catalogo.bp)

    registrar_contexto(app)

    return app
