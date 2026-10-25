"""Rutas del historial de facturas."""

import csv
import io
from datetime import date, timedelta

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from app.security import login_requerido
from app.services.correo_service import ServicioCorreo
from app.services.factura_service import FacturaService
from app.services.validaciones import ErrorValidacion

bp = Blueprint("facturas", __name__, url_prefix="/facturas")

POR_PAGINA = 25


def _leer_filtros() -> dict:
    """Arma los filtros desde la URL.

    Sin fechas explícitas, muestra los últimos 30 días, que es lo que se
    consulta a diario.
    """
    hoy = date.today()
    return {
        "q": request.args.get("q", "").strip() or None,
        "desde": request.args.get("desde") or (hoy - timedelta(days=30)).isoformat(),
        "hasta": request.args.get("hasta") or hoy.isoformat(),
        "estado": request.args.get("estado", "todas"),
        "tipo": request.args.get("tipo", "todos"),
        "metodo": request.args.get("metodo", "todos"),
    }


@bp.route("/")
@login_requerido
def lista():
    filtros = _leer_filtros()
    vista = request.args.get("vista", "factura")
    pagina = max(request.args.get("pagina", 1, type=int), 1)

    servicio = FacturaService()
    facturas, total = servicio.listar(filtros, pagina, POR_PAGINA)
    paginas = max((total + POR_PAGINA - 1) // POR_PAGINA, 1)

    # Los abonos solo se consultan para las fiadas que están en pantalla.
    abonos = {
        f["id_factura"]: servicio.abonos_de(f["id_factura"])
        for f in facturas
        if f["n_abonos"]
    }

    return render_template(
        "facturas/lista.html",
        facturas=facturas,
        agrupado=servicio.agrupado(filtros) if vista == "cliente" else [],
        abonos=abonos,
        resumen=servicio.resumen(filtros),
        filtros=filtros,
        vista=vista,
        total=total,
        pagina=pagina,
        paginas=paginas,
    )


@bp.route("/<int:id_factura>/abonar", methods=["POST"])
@login_requerido
def abonar(id_factura):
    try:
        resultado = FacturaService().registrar_abono(
            id_factura, request.form.to_dict(), g.empleado["id_empleado"]
        )
    except ErrorValidacion as e:
        flash(list(e.errores.values())[0], "error")
    except ValueError as e:
        flash(str(e), "error")
    else:
        if resultado["pagada"]:
            flash("Abono registrado. La factura quedó pagada por completo.", "ok")
        else:
            flash(
                f"Abono registrado. Saldo pendiente: ${resultado['saldo']:.2f}", "ok"
            )
    return redirect(request.referrer or url_for("facturas.lista"))


@bp.route("/<int:id_factura>/anular", methods=["POST"])
@login_requerido
def anular(id_factura):
    try:
        FacturaService().anular(
            id_factura, request.form.get("motivo", ""), g.empleado["id_empleado"]
        )
    except ErrorValidacion as e:
        flash(list(e.errores.values())[0], "error")
    except ValueError as e:
        flash(str(e), "error")
    else:
        flash("Factura anulada. Queda en el historial con su motivo.", "ok")
    return redirect(request.referrer or url_for("facturas.lista"))


@bp.route("/<int:id_factura>")
@login_requerido
def detalle(id_factura):
    servicio = FacturaService()
    factura = servicio.obtener(id_factura)
    if factura is None:
        abort(404)
    return render_template(
        "facturas/detalle.html",
        factura=factura,
        abonos=servicio.abonos_de(id_factura),
        correo_disponible=ServicioCorreo.configurado(),
    )


@bp.route("/exportar")
@login_requerido
def exportar():
    filtros = _leer_filtros()
    filas = FacturaService().para_exportar(filtros)

    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow(
        [
            "N° factura", "Fecha", "Cliente", "Cédula", "Vendedor", "Ítems",
            "Subtotal", "Descuento %", "IVA %", "IVA", "Total",
            "Método", "Estado", "Saldo pendiente", "Motivo anulación",
        ]
    )
    for f in filas:
        escritor.writerow(
            [
                f["numero_factura"],
                f["fecha"].strftime("%d/%m/%Y %H:%M"),
                f["cliente"],
                f["cedula"] or "",
                f["vendedor"],
                f["items"] or "",
                f["subtotal"],
                f["descuento_porcentaje"],
                f["iva_porcentaje"],
                f["iva"],
                f["total"],
                f["metodo_pago"] or "",
                f["estado"],
                f["saldo_pendiente"],
                f["motivo_anulacion"] or "",
            ]
        )

    nombre = f"facturas_{filtros['desde']}_a_{filtros['hasta']}.csv"
    # El BOM hace que Excel abra el archivo en UTF-8 y respete las tildes.
    contenido = "﻿" + buffer.getvalue()
    # content_type explícito: con mimetype, Flask añadiría el charset
    # una segunda vez.
    return Response(
        contenido,
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
