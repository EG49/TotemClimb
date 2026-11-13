"""Rutas de gastos.

Solo el ADMIN entra aquí: lo acordado es que los gastos los registra
él, no el vendedor del turno.
"""

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from app.models.gasto import GENERAL, SEGMENTOS
from app.security import admin_requerido
from app.services.contabilidad_service import rango_del_periodo
from app.services.gasto_service import GastoService
from app.services.validaciones import ErrorValidacion

bp = Blueprint("gastos", __name__, url_prefix="/gastos")

POR_PAGINA = 50


def _filtros_de_la_url() -> dict:
    """Lee los filtros de la querystring y los normaliza."""
    segmento = request.args.get("segmento", "todos")
    if segmento != "todos" and segmento not in SEGMENTOS:
        segmento = "todos"

    facturado = request.args.get("facturado", "todos")
    if facturado not in ("todos", "si", "no"):
        facturado = "todos"

    estado = request.args.get("estado", "activos")
    if estado not in ("activos", "anulados", "todos"):
        estado = "activos"

    return {
        "segmento": segmento,
        "facturado": facturado,
        "estado": estado,
        "q": (request.args.get("q") or "").strip(),
    }


@bp.route("/")
@admin_requerido
def lista():
    periodo = request.args.get("periodo", "mes")
    desde, hasta, etiqueta = rango_del_periodo(
        periodo, request.args.get("desde"), request.args.get("hasta")
    )

    filtros = _filtros_de_la_url()
    pagina = max(1, request.args.get("pagina", 1, type=int))

    servicio = GastoService()
    gastos, total = servicio.listar(
        desde=desde, hasta=hasta, pagina=pagina,
        por_pagina=POR_PAGINA, **filtros,
    )

    paginas = max(1, -(-total // POR_PAGINA))

    return render_template(
        "gastos/lista.html",
        gastos=gastos,
        total=total,
        pagina=pagina,
        paginas=paginas,
        periodo=periodo,
        desde=desde,
        hasta=hasta,
        etiqueta=etiqueta,
        filtros=filtros,
        resumen=servicio.resumen(desde, hasta),
        por_concepto=servicio.por_concepto(desde, hasta),
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@admin_requerido
def nuevo():
    servicio = GastoService()

    if request.method == "POST":
        try:
            servicio.guardar(
                request.form.to_dict(), id_empleado=g.empleado["id_empleado"]
            )
        except ErrorValidacion as e:
            flash("Revise los campos marcados.", "error")
            return render_template(
                "gastos/formulario.html",
                gasto=None,
                datos=request.form,
                errores=e.errores,
                conceptos=servicio.conceptos_para_sugerir(),
                recurrentes=[],
            )

        flash("Gasto registrado.", "ok")
        return redirect(url_for("gastos.lista"))

    from datetime import date

    hoy = date.today()
    return render_template(
        "gastos/formulario.html",
        gasto=None,
        datos={
            "fecha": hoy.isoformat(),
            "segmento": GENERAL,
            "metodo_pago": "EFECTIVO",
        },
        errores={},
        conceptos=servicio.conceptos_para_sugerir(),
        # Los gastos fijos del mes pasado, para cargarlos de un clic.
        recurrentes=servicio.recurrentes(hoy),
    )


@bp.route("/<int:id_gasto>", methods=["GET", "POST"])
@admin_requerido
def editar(id_gasto):
    servicio = GastoService()
    gasto = servicio.obtener(id_gasto)
    if gasto is None:
        abort(404)

    if gasto.anulado:
        flash("Un gasto anulado no se puede editar.", "error")
        return redirect(url_for("gastos.lista", estado="anulados"))

    if request.method == "POST":
        try:
            servicio.guardar(
                request.form.to_dict(), id_gasto, g.empleado["id_empleado"]
            )
        except ErrorValidacion as e:
            flash("Revise los campos marcados.", "error")
            return render_template(
                "gastos/formulario.html",
                gasto=gasto,
                datos=request.form,
                errores=e.errores,
                conceptos=servicio.conceptos_para_sugerir(),
                recurrentes=[],
            )

        flash("Gasto corregido.", "ok")
        return redirect(url_for("gastos.lista"))

    return render_template(
        "gastos/formulario.html",
        gasto=gasto,
        datos={
            "fecha": gasto.fecha.isoformat() if gasto.fecha else "",
            "monto": gasto.monto,
            "segmento": gasto.segmento,
            "concepto": gasto.concepto,
            "facturado": "on" if gasto.facturado else "",
            "descripcion": gasto.descripcion or "",
            "metodo_pago": gasto.metodo_pago or "",
        },
        errores={},
        conceptos=servicio.conceptos_para_sugerir(),
        recurrentes=[],
    )


@bp.route("/<int:id_gasto>/anular", methods=["POST"])
@admin_requerido
def anular(id_gasto):
    try:
        GastoService().anular(
            id_gasto,
            request.form.get("motivo", ""),
            g.empleado["id_empleado"],
        )
    except ErrorValidacion as e:
        flash(next(iter(e.errores.values())), "error")
        return redirect(url_for("gastos.lista"))

    flash("Gasto anulado. Queda en el historial con su motivo.", "ok")
    return redirect(url_for("gastos.lista"))
