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

from datetime import date, timedelta

from app.security import login_requerido
from app.services.calendario_service import CalendarioService
from app.services.cliente_service import ClienteService
from app.services.validaciones import ErrorValidacion

# Categoría que se usa para las clases de prueba agendadas desde el alta.
NOMBRE_CATEGORIA_PRUEBA = "Clase de prueba"
DIAS_VISIBLES_PRUEBA = 60

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



def _categoria_prueba():
    """Devuelve la categoría 'Clase de prueba', si existe."""
    for c in CalendarioService().listar_categorias():
        if c.nombre.strip().lower() == NOMBRE_CATEGORIA_PRUEBA.lower():
            return c
    return None


def _clases_de_prueba_disponibles():
    """Clases de prueba próximas, para el mini-calendario del alta."""
    categoria = _categoria_prueba()
    if categoria is None:
        return categoria, []
    hoy = date.today()
    eventos = CalendarioService().eventos.de_categoria_entre(
        categoria.id_categoria, hoy, hoy + timedelta(days=DIAS_VISIBLES_PRUEBA)
    )
    return categoria, [e for e in eventos if not e.cupo_lleno]


def _extraer_clase_prueba(formulario) -> dict | None:
    """Lee la sección de clase de prueba del formulario de alta."""
    if formulario.get("agendar_prueba") != "on":
        return None

    id_evento = formulario.get("id_evento_prueba")
    if id_evento and id_evento.isdigit():
        return {"id_evento": id_evento}

    fecha = formulario.get("fecha_prueba")
    if not fecha:
        return None

    categoria = _categoria_prueba()
    if categoria is None:
        return None

    return {
        "fecha": fecha,
        "hora_inicio": formulario.get("hora_inicio_prueba") or "10:00",
        "hora_fin": formulario.get("hora_fin_prueba") or "11:00",
        "id_categoria": categoria.id_categoria,
    }


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
                _extraer_clase_prueba(request.form),
            )
        except ErrorValidacion as e:
            flash("Revisa los campos marcados.", "error")
            categoria, clases = _clases_de_prueba_disponibles()
            return render_template(
                "clientes/formulario.html",
                cliente=None,
                datos=request.form,
                menores=_extraer_menores(request.form),
                errores=e.errores,
                clases_prueba=clases,
                hay_categoria_prueba=categoria is not None,
            )

        flash("Cliente registrado.", "ok")
        if request.form.get("cobrar_ahora") == "1":
            return redirect(url_for("cobrar.cobrar", cliente=id_cliente))
        return redirect(url_for("clientes.editar", id_cliente=id_cliente))

    categoria, clases = _clases_de_prueba_disponibles()
    return render_template(
        "clientes/formulario.html",
        cliente=None,
        datos={},
        menores=[],
        errores={},
        clases_prueba=clases,
        hay_categoria_prueba=categoria is not None,
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
                clases_prueba=[],
                hay_categoria_prueba=False,
            )

        flash("Cambios guardados.", "ok")
        return redirect(url_for("clientes.editar", id_cliente=id_cliente))

    return render_template(
        "clientes/formulario.html",
        cliente=cliente,
        datos=_a_formulario(cliente),
        menores=servicio.menores_de(id_cliente),
        errores={},
        clases_prueba=[],
        hay_categoria_prueba=False,
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
