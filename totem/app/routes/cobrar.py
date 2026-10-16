"""Rutas del cobro."""

import json

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

from app.security import login_requerido
from app.services.cliente_service import ClienteService
from app.services.cobro_service import CobroService
from app.services.validaciones import ErrorValidacion

bp = Blueprint("cobrar", __name__, url_prefix="/cobrar")


def _extraer_items(formulario) -> list[dict]:
    """Lee las líneas del formulario.

    Llegan como JSON en un campo oculto, porque la tabla de ítems se
    arma en el navegador. Solo se confía en el tipo, el id y la
    cantidad: los precios se vuelven a leer de la base.
    """
    crudo = formulario.get("items_json", "[]")
    try:
        items = json.loads(crudo)
    except (ValueError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    return [
        {
            "tipo": i.get("tipo"),
            "id_item": i.get("id_item"),
            "cantidad": i.get("cantidad", 1),
        }
        for i in items
        if isinstance(i, dict)
    ]


@bp.route("/", methods=["GET", "POST"])
@login_requerido
def cobrar():
    servicio = CobroService()
    clientes = ClienteService()

    # Permite llegar desde el alta de un cliente con él ya elegido.
    id_precargado = request.args.get("cliente", type=int)
    cliente = clientes.obtener(id_precargado) if id_precargado else None

    if request.method == "POST":
        try:
            id_factura = servicio.cobrar(
                request.form.to_dict(),
                _extraer_items(request.form),
                g.empleado["id_empleado"],
            )
        except ErrorValidacion as e:
            flash(list(e.errores.values())[0], "error")
            seleccionado = request.form.get("id_cliente", type=int)
            return render_template(
                "cobrar/cobrar.html",
                catalogo=servicio.catalogo_para_cobrar(),
                iva=servicio.iva_vigente(),
                cliente=clientes.obtener(seleccionado) if seleccionado else None,
                errores=e.errores,
            )

        return redirect(url_for("cobrar.comprobante", id_factura=id_factura))

    return render_template(
        "cobrar/cobrar.html",
        catalogo=servicio.catalogo_para_cobrar(),
        iva=servicio.iva_vigente(),
        cliente=cliente,
        errores={},
    )


@bp.route("/comprobante/<int:id_factura>")
@login_requerido
def comprobante(id_factura):
    factura = CobroService().facturas.obtener(id_factura)
    if factura is None:
        abort(404)
    return render_template("cobrar/comprobante.html", factura=factura)


@bp.route("/buscar-clientes")
@login_requerido
def buscar_clientes():
    """Alimenta el buscador de clientes de la pantalla de cobro."""
    termino = request.args.get("q", "").strip()
    if len(termino) < 2:
        return {"clientes": []}

    encontrados, _ = ClienteService().listar(termino, "todos", 1, 8)
    return {
        "clientes": [
            {
                "id": c.id_cliente,
                "nombre": c.nombre_completo,
                "cedula": c.cedula or "—",
                "estado": c.estado_etiqueta,
                "menor": c.tiene_representante,
            }
            for c in encontrados
        ]
    }
