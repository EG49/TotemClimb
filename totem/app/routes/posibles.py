"""Rutas de posibles clientes: las clases de prueba.

Las ve cualquier vendedor, porque agendarlas es trabajo de mostrador.
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

from app.security import login_requerido
from app.services.empleado_service import EmpleadoService
from app.services.posible_cliente_service import PosibleClienteService
from app.services.validaciones import ErrorValidacion

bp = Blueprint("posibles", __name__, url_prefix="/posibles")


@bp.route("/")
@login_requerido
def lista():
    servicio = PosibleClienteService()
    estado = request.args.get("estado") or None
    busqueda = (request.args.get("q") or "").strip() or None
    try:
        id_coach = int(request.args.get("coach") or 0) or None
    except ValueError:
        id_coach = None

    return render_template(
        "posibles/lista.html",
        posibles=servicio.listar(estado, id_coach, busqueda),
        resumen=servicio.resumen(),
        coaches=EmpleadoService().listar_coaches(),
        estado=estado,
        id_coach=id_coach,
        busqueda=busqueda or "",
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_requerido
def nuevo():
    servicio = PosibleClienteService()
    if request.method == "POST":
        try:
            servicio.agendar(request.form.to_dict(), g.empleado["id_empleado"])
        except ErrorValidacion as e:
            flash("Revisa los campos marcados.", "error")
            return render_template(
                "posibles/formulario.html",
                ficha=None,
                datos=request.form,
                errores=e.errores,
                coaches=EmpleadoService().listar_coaches(),
            )
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("posibles.lista"))

        flash("Clase de prueba agendada.", "ok")
        return redirect(url_for("posibles.lista"))

    return render_template(
        "posibles/formulario.html",
        ficha=None,
        datos={"hora_inicio": "10:00"},
        errores={},
        coaches=EmpleadoService().listar_coaches(),
    )


@bp.route("/<int:id_posible>", methods=["GET", "POST"])
@login_requerido
def editar(id_posible):
    servicio = PosibleClienteService()
    ficha = servicio.obtener(id_posible)
    if ficha is None:
        abort(404)

    if request.method == "POST":
        try:
            servicio.actualizar(
                id_posible, request.form.to_dict(), g.empleado["id_empleado"]
            )
        except ErrorValidacion as e:
            flash("Revisa los campos marcados.", "error")
            return render_template(
                "posibles/formulario.html",
                ficha=ficha,
                datos=request.form,
                errores=e.errores,
                coaches=EmpleadoService().listar_coaches(),
            )
        flash("Cambios guardados.", "ok")
        return redirect(url_for("posibles.editar", id_posible=id_posible))

    return render_template(
        "posibles/formulario.html",
        ficha=ficha,
        datos={
            "nombre": ficha.nombre,
            "apellido": ficha.apellido,
            "correo": ficha.correo,
            "telefono": ficha.telefono,
            "id_coach": ficha.id_coach,
        },
        errores={},
        coaches=EmpleadoService().listar_coaches(),
    )


@bp.route("/<int:id_posible>/asistencia", methods=["POST"])
@login_requerido
def asistencia(id_posible):
    valor = request.form.get("asistio")
    asistio = {"si": True, "no": False}.get(valor)

    try:
        PosibleClienteService().marcar_asistencia(
            id_posible, asistio, g.empleado["id_empleado"]
        )
    except ValueError as e:
        flash(str(e), "error")
    else:
        flash(
            {True: "Marcado como asistió.", False: "Marcado como no asistió."}.get(
                asistio, "Asistencia sin marcar."
            ),
            "ok",
        )
    return redirect(request.referrer or url_for("posibles.lista"))


@bp.route("/<int:id_posible>/deshacer-conversion", methods=["POST"])
@login_requerido
def deshacer_conversion(id_posible):
    try:
        PosibleClienteService().deshacer_conversion(
            id_posible, g.empleado["id_empleado"]
        )
    except ValueError as e:
        flash(str(e), "error")
    else:
        flash("Se deshizo el enlace con el cliente.", "ok")
    return redirect(request.referrer or url_for("posibles.lista"))
