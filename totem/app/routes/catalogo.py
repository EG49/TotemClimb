"""Rutas del catálogo: productos y planes de membresía."""

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
from app.services.catalogo_service import CatalogoService
from app.services.validaciones import ErrorValidacion

bp = Blueprint("catalogo", __name__, url_prefix="/catalogo")


@bp.route("/")
@login_requerido
def lista():
    pestana = request.args.get("pestana", "productos")
    if pestana not in ("productos", "planes"):
        pestana = "productos"

    ver_inactivos = request.args.get("inactivos") == "1"
    servicio = CatalogoService()

    return render_template(
        "catalogo/lista.html",
        pestana=pestana,
        ver_inactivos=ver_inactivos,
        productos=servicio.listar_productos(ver_inactivos),
        planes=servicio.listar_planes(ver_inactivos),
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_requerido
def nuevo():
    """Formulario único con toggle Producto / Membresía."""
    tipo_item = request.values.get("tipo_item", "producto")
    servicio = CatalogoService()

    if request.method == "POST":
        try:
            if tipo_item == "membresia":
                servicio.guardar_plan(request.form.to_dict(), id_empleado=g.empleado['id_empleado'])
                destino = "planes"
            else:
                servicio.guardar_producto(request.form.to_dict(), id_empleado=g.empleado['id_empleado'])
                destino = "productos"
        except ErrorValidacion as e:
            flash("Revisa los campos marcados.", "error")
            return render_template(
                "catalogo/formulario.html",
                item=None,
                tipo_item=tipo_item,
                datos=request.form,
                errores=e.errores,
            )

        flash("Ítem agregado al catálogo.", "ok")
        return redirect(url_for("catalogo.lista", pestana=destino))

    return render_template(
        "catalogo/formulario.html",
        item=None,
        tipo_item=tipo_item,
        datos={"permite_descuento": "on", "duracion": 1, "unidad_duracion": "MES"},
        errores={},
    )


@bp.route("/producto/<int:id_producto>", methods=["GET", "POST"])
@login_requerido
def editar_producto(id_producto):
    servicio = CatalogoService()
    producto = servicio.obtener_producto(id_producto)
    if producto is None:
        abort(404)

    if request.method == "POST":
        try:
            servicio.guardar_producto(request.form.to_dict(), id_producto, g.empleado['id_empleado'])
        except ErrorValidacion as e:
            flash("Revisa los campos marcados.", "error")
            return render_template(
                "catalogo/formulario.html",
                item=producto,
                tipo_item="producto",
                datos=request.form,
                errores=e.errores,
            )
        flash("Producto actualizado.", "ok")
        return redirect(url_for("catalogo.lista", pestana="productos"))

    return render_template(
        "catalogo/formulario.html",
        item=producto,
        tipo_item="producto",
        datos={"nombre": producto.nombre, "precio": producto.precio},
        errores={},
    )


@bp.route("/plan/<int:id_plan>", methods=["GET", "POST"])
@login_requerido
def editar_plan(id_plan):
    servicio = CatalogoService()
    plan = servicio.obtener_plan(id_plan)
    if plan is None:
        abort(404)

    if request.method == "POST":
        try:
            servicio.guardar_plan(request.form.to_dict(), id_plan, g.empleado['id_empleado'])
        except ErrorValidacion as e:
            flash("Revisa los campos marcados.", "error")
            return render_template(
                "catalogo/formulario.html",
                item=plan,
                tipo_item="membresia",
                datos=request.form,
                errores=e.errores,
            )
        flash("Plan actualizado.", "ok")
        return redirect(url_for("catalogo.lista", pestana="planes"))

    return render_template(
        "catalogo/formulario.html",
        item=plan,
        tipo_item="membresia",
        datos={
            "nombre": plan.nombre,
            "tipo": plan.tipo,
            "precio": plan.precio,
            "duracion": plan.duracion,
            "unidad_duracion": plan.unidad_duracion,
            "dias_incluidos": plan.dias_incluidos,
            "permite_pareja": "on" if plan.permite_pareja else "",
            "permite_descuento": "on" if plan.permite_descuento else "",
        },
        errores={},
    )


@bp.route("/producto/<int:id_producto>/estado", methods=["POST"])
@login_requerido
def estado_producto(id_producto):
    activo = request.form.get("activo") == "1"
    CatalogoService().cambiar_estado_producto(id_producto, activo, g.empleado['id_empleado'])
    flash("Producto reactivado." if activo else "Producto desactivado.", "ok")
    return redirect(url_for("catalogo.lista", pestana="productos", inactivos="1"))


@bp.route("/plan/<int:id_plan>/estado", methods=["POST"])
@login_requerido
def estado_plan(id_plan):
    activo = request.form.get("activo") == "1"
    CatalogoService().cambiar_estado_plan(id_plan, activo, g.empleado['id_empleado'])
    flash("Plan reactivado." if activo else "Plan desactivado.", "ok")
    return redirect(url_for("catalogo.lista", pestana="planes", inactivos="1"))
