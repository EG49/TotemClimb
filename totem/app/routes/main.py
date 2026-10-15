"""Rutas principales. Por ahora solo el panel, como punto de entrada."""

from flask import Blueprint, render_template

from app.security import admin_requerido, login_requerido
from app.services.bitacora_service import BitacoraService

bp = Blueprint("main", __name__)


@bp.route("/")
@login_requerido
def panel():
    return render_template("panel.html")


@bp.route("/bitacora")
@admin_requerido
def bitacora():
    """Registro de acciones. Solo para el ADMIN."""
    movimientos = BitacoraService().consultar(limite=100)
    return render_template("bitacora.html", movimientos=movimientos)
