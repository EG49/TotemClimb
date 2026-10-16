"""Rutas de gestión de empleados. Solo para el ADMIN."""

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

from app.security import admin_requerido
from app.services.empleado_service import EmpleadoService
from app.services.validaciones import ErrorValidacion

bp = Blueprint("empleados", __name__, url_prefix="/empleados")


@bp.route("/")
@admin_requerido
def lista():
    servicio = EmpleadoService()
    empleados = servicio.listar()
    return render_template(
        "empleados/lista.html",
        empleados=empleados,
        actividad={e.id_empleado: servicio.actividad(e.id_empleado) for e in empleados},
        yo=g.empleado["id_empleado"],
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@admin_requerido
def nuevo():
    if request.method == "POST":
        try:
            EmpleadoService().crear(request.form.to_dict(), g.empleado["id_empleado"])
        except ErrorValidacion as e:
            flash("Revisa los campos marcados.", "error")
            return render_template(
                "empleados/formulario.html",
                ficha=None,
                datos=request.form,
                errores=e.errores,
            )
        flash("Empleado creado. Ya puede entrar con su usuario y contraseña.", "ok")
        return redirect(url_for("empleados.lista"))

    return render_template(
        "empleados/formulario.html",
        ficha=None,
        datos={"rol": "VENDEDOR"},
        errores={},
    )


@bp.route("/<int:id_empleado>", methods=["GET", "POST"])
@admin_requerido
def editar(id_empleado):
    servicio = EmpleadoService()
    empleado = servicio.obtener(id_empleado)
    if empleado is None:
        abort(404)

    if request.method == "POST":
        try:
            servicio.actualizar(
                id_empleado, request.form.to_dict(), g.empleado["id_empleado"]
            )
        except ErrorValidacion as e:
            flash(list(e.errores.values())[0], "error")
            return render_template(
                "empleados/formulario.html",
                ficha=empleado,
                datos=request.form,
                errores=e.errores,
                actividad=servicio.actividad(id_empleado),
                yo=g.empleado["id_empleado"],
            )
        flash("Cambios guardados.", "ok")
        return redirect(url_for("empleados.editar", id_empleado=id_empleado))

    return render_template(
        "empleados/formulario.html",
        ficha=empleado,
        datos={
            "nombre": empleado.nombre,
            "apellido": empleado.apellido,
            "usuario": empleado.usuario,
            "rol": empleado.rol,
            "fecha_nacimiento": (
                empleado.fecha_nacimiento.isoformat()
                if empleado.fecha_nacimiento
                else ""
            ),
        },
        errores={},
        actividad=servicio.actividad(id_empleado),
        yo=g.empleado["id_empleado"],
    )


@bp.route("/<int:id_empleado>/password", methods=["POST"])
@admin_requerido
def cambiar_password(id_empleado):
    try:
        EmpleadoService().cambiar_password(
            id_empleado, request.form.to_dict(), g.empleado["id_empleado"]
        )
    except ErrorValidacion as e:
        flash(list(e.errores.values())[0], "error")
    except ValueError as e:
        flash(str(e), "error")
    else:
        flash("Contraseña actualizada.", "ok")
    return redirect(url_for("empleados.editar", id_empleado=id_empleado))


@bp.route("/<int:id_empleado>/estado", methods=["POST"])
@admin_requerido
def estado(id_empleado):
    activo = request.form.get("activo") == "1"
    try:
        EmpleadoService().cambiar_estado(
            id_empleado, activo, g.empleado["id_empleado"]
        )
    except ErrorValidacion as e:
        flash(list(e.errores.values())[0], "error")
    except ValueError as e:
        flash(str(e), "error")
    else:
        flash(
            "Empleado reactivado." if activo else "Empleado desactivado.", "ok"
        )
    return redirect(request.referrer or url_for("empleados.lista"))
