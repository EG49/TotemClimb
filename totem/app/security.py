"""Sesión y control de acceso.

El sistema tiene dos roles: VENDEDOR, que es la vista normal de trabajo, y
ADMIN, que además ve la bitácora y puede cambiar el IVA.
"""

from functools import wraps

from flask import flash, g, redirect, session, url_for

from app.models.empleado import ROL_ADMIN


def iniciar_sesion(empleado) -> None:
    session.clear()
    session["id_empleado"] = empleado.id_empleado
    session["nombre"] = empleado.nombre_completo
    session["rol"] = empleado.rol
    session.permanent = True


def cerrar_sesion() -> None:
    session.clear()


def empleado_actual() -> dict | None:
    """Datos del empleado en sesión, o None si no hay sesión."""
    if "id_empleado" not in session:
        return None
    return {
        "id_empleado": session["id_empleado"],
        "nombre": session.get("nombre", ""),
        "rol": session.get("rol", ""),
        "es_admin": session.get("rol") == ROL_ADMIN,
    }


def login_requerido(vista):
    """Exige sesión activa."""

    @wraps(vista)
    def envoltura(*args, **kwargs):
        if empleado_actual() is None:
            return redirect(url_for("auth.login"))
        return vista(*args, **kwargs)

    return envoltura


def admin_requerido(vista):
    """Exige sesión activa y rol ADMIN."""

    @wraps(vista)
    def envoltura(*args, **kwargs):
        actual = empleado_actual()
        if actual is None:
            return redirect(url_for("auth.login"))
        if not actual["es_admin"]:
            flash("Esa sección es solo para el administrador.", "error")
            return redirect(url_for("main.panel"))
        return vista(*args, **kwargs)

    return envoltura


def registrar_contexto(app) -> None:
    """Deja al empleado disponible en g y en todas las plantillas."""

    @app.before_request
    def _cargar_empleado():
        g.empleado = empleado_actual()

    @app.context_processor
    def _inyectar_empleado():
        return {"empleado": empleado_actual()}
