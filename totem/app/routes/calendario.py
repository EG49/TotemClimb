"""Rutas del calendario y de la agenda por cliente."""

from calendar import monthrange
from datetime import date, datetime, timedelta

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
from app.services.calendario_service import CalendarioService, lunes_de, rango_vista
from app.services.validaciones import ErrorValidacion

bp = Blueprint("calendario", __name__, url_prefix="/calendario")

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
DIAS_SEMANA = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _ancla() -> date:
    texto = request.args.get("fecha")
    if texto:
        try:
            return datetime.strptime(texto, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()


def _desplazar(vista: str, ancla: date, pasos: int) -> date:
    if vista == "semana":
        return ancla + timedelta(days=7 * pasos)
    if vista == "anio":
        return ancla.replace(year=ancla.year + pasos, day=1, month=1)
    indice = ancla.month - 1 + pasos
    anio = ancla.year + indice // 12
    mes = indice % 12 + 1
    return date(anio, mes, min(ancla.day, monthrange(anio, mes)[1]))


@bp.route("/")
@login_requerido
def ver():
    vista = request.args.get("vista", "mes")
    if vista not in ("semana", "mes", "anio"):
        vista = "mes"

    ancla = _ancla()
    desde, hasta = rango_vista(vista, ancla)

    servicio = CalendarioService()
    marcas = servicio.marcas_por_dia(desde, hasta)

    # Día seleccionado en el panel lateral
    seleccionado = _ancla() if request.args.get("fecha") else date.today()

    if vista == "semana":
        titulo = (
            f"{desde.day} {MESES[desde.month - 1][:3]} – "
            f"{hasta.day} {MESES[hasta.month - 1][:3]} {hasta.year}"
        )
        dias = [desde + timedelta(days=i) for i in range(7)]
    elif vista == "anio":
        titulo = str(ancla.year)
        dias = []
    else:
        titulo = f"{MESES[ancla.month - 1]} {ancla.year}"
        dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]

    # La vista de año se arma acá y no en la plantilla: calcular los
    # días de cada mes en Jinja resulta ilegible y frágil.
    meses_del_anio = []
    if vista == "anio":
        for mes in range(1, 13):
            primero = date(ancla.year, mes, 1)
            cantidad = monthrange(ancla.year, mes)[1]
            meses_del_anio.append(
                {
                    "numero": mes,
                    "nombre": MESES[mes - 1],
                    "primero": primero,
                    "huecos": primero.weekday(),
                    "dias": [date(ancla.year, mes, d) for d in range(1, cantidad + 1)],
                }
            )

    return render_template(
        "calendario/ver.html",
        meses_del_anio=meses_del_anio,
        vista=vista,
        ancla=ancla,
        titulo=titulo,
        dias=dias,
        marcas=marcas,
        seleccionado=seleccionado,
        marcas_del_dia=marcas.get(seleccionado, []),
        categorias=servicio.listar_categorias(),
        hoy=date.today(),
        mes_actual=ancla.month,
        anterior=_desplazar(vista, ancla, -1),
        siguiente=_desplazar(vista, ancla, 1),
        meses=MESES,
        dias_semana=DIAS_SEMANA,
    )


@bp.route("/evento/nuevo", methods=["GET", "POST"])
@login_requerido
def nuevo_evento():
    servicio = CalendarioService()

    if request.method == "POST":
        ids = [int(i) for i in request.form.getlist("inscritos") if i.isdigit()]
        try:
            servicio.crear_evento(
                request.form.to_dict(), ids, g.empleado["id_empleado"]
            )
        except ErrorValidacion as e:
            flash(list(e.errores.values())[0], "error")
            return render_template(
                "calendario/evento.html",
                evento=None,
                datos=request.form,
                categorias=servicio.listar_categorias(),
                errores=e.errores,
                inscritos=[],
            )
        flash("Evento creado.", "ok")
        return redirect(url_for("calendario.ver", fecha=request.form.get("fecha")))

    fecha = request.args.get("fecha") or date.today().isoformat()
    return render_template(
        "calendario/evento.html",
        evento=None,
        datos={"fecha": fecha, "hora_inicio": "10:00", "hora_fin": "11:00"},
        categorias=servicio.listar_categorias(),
        errores={},
        inscritos=[],
    )


@bp.route("/evento/<int:id_evento>", methods=["GET", "POST"])
@login_requerido
def editar_evento(id_evento):
    servicio = CalendarioService()
    evento = servicio.obtener_evento(id_evento)
    if evento is None:
        abort(404)

    if request.method == "POST":
        try:
            servicio.actualizar_evento(
                id_evento, request.form.to_dict(), g.empleado["id_empleado"]
            )
        except ErrorValidacion as e:
            flash(list(e.errores.values())[0], "error")
            return render_template(
                "calendario/evento.html",
                evento=evento,
                datos=request.form,
                categorias=servicio.listar_categorias(),
                errores=e.errores,
                inscritos=evento.nombres_inscritos,
            )
        flash("Evento actualizado.", "ok")
        return redirect(url_for("calendario.editar_evento", id_evento=id_evento))

    return render_template(
        "calendario/evento.html",
        evento=evento,
        datos={
            "titulo": evento.titulo,
            "id_categoria": evento.id_categoria,
            "fecha": evento.fecha.isoformat(),
            "hora_inicio": evento.hora_inicio.strftime("%H:%M"),
            "hora_fin": evento.hora_fin.strftime("%H:%M"),
            "descripcion": evento.descripcion,
            "cupo_maximo": evento.cupo_maximo,
            "todo_el_dia": "on" if evento.es_todo_el_dia else "",
        },
        categorias=servicio.listar_categorias(),
        errores={},
        inscritos=evento.nombres_inscritos,
    )


@bp.route("/evento/<int:id_evento>/eliminar", methods=["POST"])
@login_requerido
def eliminar_evento(id_evento):
    CalendarioService().eliminar_evento(id_evento, g.empleado["id_empleado"])
    flash("Evento eliminado.", "ok")
    return redirect(url_for("calendario.ver"))


@bp.route("/evento/<int:id_evento>/inscribir", methods=["POST"])
@login_requerido
def inscribir(id_evento):
    try:
        CalendarioService().inscribir(
            id_evento,
            int(request.form.get("id_cliente", 0)),
            g.empleado["id_empleado"],
        )
    except ErrorValidacion as e:
        flash(list(e.errores.values())[0], "error")
    except (ValueError, TypeError):
        flash("Elige un cliente válido.", "error")
    else:
        flash("Cliente inscrito.", "ok")
    return redirect(request.referrer or url_for("calendario.ver"))


@bp.route("/evento/<int:id_evento>/quitar/<int:id_cliente>", methods=["POST"])
@login_requerido
def quitar_inscrito(id_evento, id_cliente):
    CalendarioService().quitar_inscripcion(
        id_evento, id_cliente, g.empleado["id_empleado"]
    )
    flash("Inscripción quitada.", "ok")
    return redirect(request.referrer or url_for("calendario.ver"))


@bp.route("/agenda")
@login_requerido
def agenda():
    servicio = CalendarioService()
    filtros = {
        "busqueda": request.args.get("q", "").strip() or None,
        "id_categoria": request.args.get("categoria", type=int),
        "estado": request.args.get("estado", "proximas"),
    }
    por_cliente = servicio.agenda(**filtros)

    total_inscripciones = sum(len(c["eventos"]) for c in por_cliente.values())
    proximas = sum(
        1
        for c in por_cliente.values()
        for e in c["eventos"]
        if e["es_proxima"]
    )

    return render_template(
        "calendario/agenda.html",
        clientes=sorted(por_cliente.values(), key=lambda c: c["nombre"]),
        categorias=servicio.listar_categorias(),
        filtros=filtros,
        total_inscripciones=total_inscripciones,
        proximas=proximas,
        proximos_eventos=servicio.proximos(20),
    )
