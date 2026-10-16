"""Rutas del reporte de Contabilidad."""

from flask import Blueprint, render_template, request

from app.security import login_requerido
from app.services.cliente_service import ClienteService
from app.services.contabilidad_service import ContabilidadService, rango_del_periodo

bp = Blueprint("contabilidad", __name__, url_prefix="/contabilidad")


@bp.route("/")
@login_requerido
def reporte():
    periodo = request.args.get("periodo", "dia")
    desde, hasta, etiqueta = rango_del_periodo(
        periodo, request.args.get("desde"), request.args.get("hasta")
    )

    id_cliente = request.args.get("cliente", type=int)
    cliente = ClienteService().obtener(id_cliente) if id_cliente else None

    return render_template(
        "contabilidad/reporte.html",
        datos=ContabilidadService().reporte(desde, hasta, id_cliente),
        periodo=periodo,
        desde=desde,
        hasta=hasta,
        etiqueta=etiqueta,
        cliente=cliente,
    )
