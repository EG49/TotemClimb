"""Rutas del módulo de clientes."""

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
from app.services.validaciones import ErrorValidacion

bp = Blueprint("clientes", __name__, url_prefix="/clientes")

POR_PAGINA = 20


CAMPOS_FORMULARIO = (
    "nombre", "apellido", "cedula", "fecha_nacimiento", "correo", "telefono",
    "genero", "contacto_emergencia", "referencia", "seguro_nombre", "seguro_numero",
)


def _a_formulario(cliente) -> dict:
    """Convierte un Cliente en el diccionario que espera la plantilla."""
    datos = {c: getattr(cliente, c) for c in CAMPOS_FORMULARIO}
    if datos["fecha_nacimiento"]:
        datos["fecha_nacimiento"] = datos["fecha_nacimiento"].isoformat()
    return datos



def _extraer_menores(formulario) -> list[dict]:
    """Reconstruye las tarjetas de menores del formulario.

    Los campos llegan como menor_nombre, menor_apellido, etc., repetidos
    una vez por tarjeta; getlist los devuelve en orden.
    """
    nombres = formulario.getlist("menor_nombre")
    apellidos = formulario.getlist("menor_apellido")
    fechas = formulario.getlist("menor_fecha_nacimiento")
    cedulas = formulario.getlist("menor_cedula")

    menores = []
    for i in range(len(nombres)):
        menores.append(
            {
                "nombre": nombres[i],
                "apellido": apellidos[i] if i < len(apellidos) else "",
                "fecha_nacimiento": fechas[i] if i < len(fechas) else "",
                "cedula": cedulas[i] if i < len(cedulas) else "",
            }
        )
    return menores


@bp.route("/")
@login_requerido
def lista():
    busqueda = request.args.get("q", "").strip() or None
    filtro = request.args.get("filtro", "todos")
    pagina = max(request.args.get("pagina", 1, type=int), 1)

    servicio = ClienteService()
    clientes, total = servicio.listar(busqueda, filtro, pagina, POR_PAGINA)
    paginas = max((total + POR_PAGINA - 1) // POR_PAGINA, 1)

    return render_template(
        "clientes/lista.html",
        clientes=clientes,
        total=total,
        pagina=pagina,
        paginas=paginas,
        busqueda=busqueda or "",
        filtro=filtro,
        conteos=servicio.conteos(),
    )


@bp.route("/nuevo", methods=["GET", "POST"])
@login_requerido
def nuevo():
    if request.method == "POST":
        try:
            id_cliente = ClienteService().crear(
                request.form.to_dict(),
                _extraer_menores(request.form),
                g.empleado["id_empleado"],
            )
        except ErrorValidacion as e:
            flash("Revisa los campos marcados.", "error")
            return render_template(
                "clientes/formulario.html",
                cliente=None,
                datos=request.form,
                menores=_extraer_menores(request.form),
                errores=e.errores,
            )

        flash("Cliente registrado.", "ok")
        # El botón del formulario es "Guardar y cobrar ahora": en cuanto
        # exista el módulo de cobro, aquí se redirige hacia allá con el
        # cliente precargado.
        return redirect(url_for("clientes.editar", id_cliente=id_cliente))

    return render_template(
        "clientes/formulario.html", cliente=None, datos={}, menores=[], errores={}
    )


@bp.route("/<int:id_cliente>", methods=["GET", "POST"])
@login_requerido
def editar(id_cliente):
    servicio = ClienteService()
    cliente = servicio.obtener(id_cliente)
    if cliente is None:
        abort(404)

    # Un menor se edita en su propia pantalla, que además muestra el
    # representante y el aviso de mayoría de edad.
    if cliente.tiene_representante:
        return redirect(url_for("clientes.menor", id_cliente=id_cliente))

    if request.method == "POST":
        try:
            servicio.actualizar(
                id_cliente, request.form.to_dict(), g.empleado["id_empleado"]
            )
        except ErrorValidacion as e:
            flash("Revisa los campos marcados.", "error")
            return render_template(
                "clientes/formulario.html",
                cliente=cliente,
                datos=request.form,
                menores=servicio.menores_de(id_cliente),
                errores=e.errores,
            )

        flash("Cambios guardados.", "ok")
        return redirect(url_for("clientes.editar", id_cliente=id_cliente))

    return render_template(
        "clientes/formulario.html",
        cliente=cliente,
        datos=_a_formulario(cliente),
        menores=servicio.menores_de(id_cliente),
        errores={},
    )


@bp.route("/<int:id_cliente>/menor", methods=["GET", "POST"])
@login_requerido
def menor(id_cliente):
    servicio = ClienteService()
    cliente = servicio.obtener(id_cliente)
    if cliente is None:
        abort(404)
    if not cliente.tiene_representante:
        return redirect(url_for("clientes.editar", id_cliente=id_cliente))

    if request.method == "POST":
        try:
            servicio.actualizar(
                id_cliente, request.form.to_dict(), g.empleado["id_empleado"]
            )
        except ErrorValidacion as e:
            flash("Revisa los campos marcados.", "error")
            return render_template(
                "clientes/menor.html", cliente=cliente, datos=request.form,
                errores=e.errores,
            )

        flash("Cambios guardados.", "ok")
        return redirect(url_for("clientes.menor", id_cliente=id_cliente))

    return render_template(
        "clientes/menor.html", cliente=cliente, datos=_a_formulario(cliente), errores={}
    )


@bp.route("/<int:id_cliente>/quitar-representante", methods=["POST"])
@login_requerido
def quitar_representante(id_cliente):
    ClienteService().quitar_representante(id_cliente, g.empleado["id_empleado"])
    flash("El cliente quedó como titular independiente.", "ok")
    return redirect(url_for("clientes.editar", id_cliente=id_cliente))
