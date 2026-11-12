"""Rutas del reporte de Contabilidad y del balance general."""

from flask import Blueprint, render_template, request

from app.security import admin_requerido, login_requerido
from app.services.balance_service import BalanceService
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


@bp.route("/balance")
@admin_requerido
def balance():
    """Lo que entró menos lo que salió, en un período.

    Solo para el ADMIN: muestra los gastos, y los gastos son suyos.
    El vendedor sigue viendo el reporte de ventas sin esta pantalla.
    """
    periodo = request.args.get("periodo", "mes")
    desde, hasta, etiqueta = rango_del_periodo(
        periodo, request.args.get("desde"), request.args.get("hasta")
    )

    return render_template(
        "contabilidad/balance.html",
        datos=BalanceService().balance(desde, hasta),
        periodo=periodo,
        desde=desde,
        hasta=hasta,
        etiqueta=etiqueta,
    )
