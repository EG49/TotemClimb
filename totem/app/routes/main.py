"""Rutas principales: panel general, bitácora y configuración."""

from calendar import monthrange
from datetime import date

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from app.repositories.panel_repo import PanelRepositorio
from app.security import admin_requerido, login_requerido
from app.services.calendario_service import CalendarioService, lunes_de
from app.services.bitacora_service import BitacoraService
from app.services.configuracion_service import ConfiguracionService
from app.services.validaciones import ErrorValidacion

bp = Blueprint("main", __name__)

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
DIAS_SEMANA = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _armar_avisos(repositorio: PanelRepositorio) -> tuple[list[dict], int, int, int]:
    """Junta los tres tipos de aviso en una sola lista ordenable.

    Cada aviso trae ya su etiqueta, su detalle y sus acciones, para que
    la plantilla solo tenga que pintarlos.
    """
    avisos = []

    vencimientos = repositorio.membresias_por_vencer()
    for v in vencimientos:
        dias = v["dias"]
        if dias < 0:
            detalle = f"Venció hace {abs(dias)} día{'s' if abs(dias) != 1 else ''}"
            clase = "vencido"
            etiqueta = "Vencida"
        elif dias == 0:
            detalle, clase, etiqueta = "Vence hoy", "por_vencer", "Por vencer"
        else:
            detalle = f"Vence en {dias} día{'s' if dias != 1 else ''}"
            clase, etiqueta = "por_vencer", "Por vencer"

        avisos.append(
            {
                "tipo": "membresia",
                "clase": clase,
                "etiqueta": etiqueta,
                "cliente": v["cliente_nombre"],
                "subtitulo": f"{v['plan_nombre']} · {v['telefono'] or 'sin celular'}",
                "detalle": f"{detalle} ({v['fecha_fin'].strftime('%d/%m/%Y')})",
                "orden": dias,
                "acciones": [
                    (
                        "Renovar",
                        url_for("cobrar.cobrar", cliente=v["id_cliente"]),
                        "btn-lima small",
                    ),
                    (
                        "Editar",
                        url_for("clientes.editar", id_cliente=v["id_cliente"]),
                        "btn-ghost small",
                    ),
                ],
            }
        )

    mayores = repositorio.mayoria_de_edad()
    for m in mayores:
        avisos.append(
            {
                "tipo": "mayoria",
                "clase": "sin_membresia",
                "etiqueta": "Cumplió 18",
                "cliente": m["cliente_nombre"],
                "subtitulo": f"Representado por {m['representante_nombre']}",
                "detalle": (
                    f"Tiene {m['edad']} años y sigue como menor a cargo. "
                    "Debe firmar su propio contrato."
                ),
                "orden": -1000 + m["edad"],
                "acciones": [
                    (
                        "Ver perfil",
                        url_for("clientes.menor", id_cliente=m["id_cliente"]),
                        "btn-ghost small",
                    )
                ],
            }
        )

    fiadas = repositorio.fiadas_pendientes()
    for f in fiadas:
        avisos.append(
            {
                "tipo": "fiado",
                "clase": "por_vencer",
                "etiqueta": "Fiado",
                "cliente": f["cliente_nombre"],
                "subtitulo": f"Factura {f['numero_factura']}",
                "detalle": (
                    f"Debe ${f['saldo_pendiente']:.2f} de ${f['total']:.2f} · "
                    f"hace {f['dias_desde']} día{'s' if f['dias_desde'] != 1 else ''}"
                ),
                "orden": -500 - f["dias_desde"],
                "acciones": [
                    (
                        "Ver factura",
                        url_for("facturas.detalle", id_factura=f["id_factura"]),
                        "btn-ghost small",
                    )
                ],
            }
        )

    avisos.sort(key=lambda a: a["orden"])
    return avisos, len(vencimientos), len(mayores), len(fiadas)


@bp.route("/")
@login_requerido
def panel():
    repositorio = PanelRepositorio()
    avisos, n_membresias, n_mayoria, n_fiado = _armar_avisos(repositorio)

    hoy = date.today()
    primero = hoy.replace(day=1)
    ultimo = hoy.replace(day=monthrange(hoy.year, hoy.month)[1])

    calendario = CalendarioService()

    return render_template(
        "panel.html",
        stats=repositorio.estadisticas(),
        avisos=avisos,
        n_membresias=n_membresias,
        n_mayoria=n_mayoria,
        n_fiado=n_fiado,
        hoy=hoy,
        fecha_larga=f"{hoy.day} de {MESES[hoy.month - 1]} de {hoy.year}",
        nombre_mes=f"{MESES[hoy.month - 1].capitalize()} {hoy.year}",
        dias_semana=DIAS_SEMANA,
        huecos=primero.weekday(),
        dias_mes=[
            date(hoy.year, hoy.month, d) for d in range(1, ultimo.day + 1)
        ],
        marcas=calendario.marcas_por_dia(primero, ultimo),
        proximos=calendario.proximos(4),
    )


@bp.route("/bitacora")
@admin_requerido
def bitacora():
    """Registro de acciones. Solo para el ADMIN."""
    accion = request.args.get("accion") or None
    movimientos = BitacoraService().consultar(accion=accion, limite=150)
    return render_template(
        "bitacora.html", movimientos=movimientos, accion=accion or ""
    )


@bp.route("/configuracion", methods=["GET", "POST"])
@admin_requerido
def configuracion():
    """Parámetros del sistema. Hoy solo el IVA."""
    servicio = ConfiguracionService()

    if request.method == "POST":
        try:
            servicio.cambiar_iva(
                request.form.get("iva_porcentaje"), g.empleado["id_empleado"]
            )
        except ErrorValidacion as e:
            flash(list(e.errores.values())[0], "error")
        else:
            flash(
                "IVA actualizado. Las facturas ya emitidas no cambian.", "ok"
            )
        return redirect(url_for("main.configuracion"))

    return render_template(
        "configuracion.html",
        iva=servicio.iva_vigente(),
        historial=servicio.historial_iva(),
    )
