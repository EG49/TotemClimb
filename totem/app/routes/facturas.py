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

from app.security import admin_requerido, login_requerido
from app.services.cliente_service import ClienteService
from app.services.correo_service import ServicioCorreo
from app.services.factura_service import FacturaService
from app.services.rebote_service import ReboteService
from app.services.sri_service import ServicioSri
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
        "sri": request.args.get("sri", ""),
        "ident": request.args.get("ident", ""),
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
        comprobante=_estado_sri(id_factura),
        # Que el correo haya salido no quiere decir que haya llegado.
        # Si rebotó, acá es donde alguien lo va a ver.
        envios=ReboteService.de_la_factura(id_factura),
        # De una sola fuente: tenerlo escrito en la plantilla fue lo
        # que dejo el tope viejo de $200 en pantalla mucho despues de
        # que el SRI lo bajara a $50.
        tope_consumidor_final=ServicioSri.TOPE_CONSUMIDOR_FINAL,
    )


def _estado_sri(id_factura: int) -> dict | None:
    """El comprobante electrónico de la factura, si lo tiene.

    Va en la pantalla porque si no, una factura que el SRI rechazó es
    invisible: la venta se ve bien y nadie se entera de que al cliente
    le falta su factura.
    """
    from app.db import obtener_cursor

    with obtener_cursor() as cursor:
        cursor.execute(
            """
            SELECT sri_estado, sri_mensaje, sri_secuencial, sri_intentos,
                   sri_establecimiento, sri_punto_emision,
                   sri_autorizacion, sri_fecha_autorizacion
              FROM facturas WHERE id_factura = %s
            """,
            (id_factura,),
        )
        fila = cursor.fetchone()
    if fila is None or fila["sri_estado"] is None:
        return None
    datos = dict(fila)
    datos["numero"] = (
        f"{datos['sri_establecimiento']}-{datos['sri_punto_emision']}-"
        f"{str(datos['sri_secuencial']).zfill(9)}"
        if datos["sri_secuencial"] else None
    )
    datos["rechazada"] = datos["sri_estado"] in ("NO_AUTORIZADA", "DEVUELTA")
    datos["en_camino"] = datos["sri_estado"] in (
        "PENDIENTE", "FIRMADA", "ENVIADA"
    )
    return datos


@bp.route("/<int:id_factura>/imprimir")
@login_requerido
def imprimir(id_factura):
    """El PDF para entregarle al cliente.

    Si el SRI autorizó la factura, sale el RIDE, que es el documento
    que vale. Si no, sale el comprobante interno: el mismo formato,
    sin número de autorización y diciendo en la cara que no es un
    comprobante de venta autorizado.

    Los dos los dibuja el mismo código a propósito. Si el interno se
    dibujara aparte, con el tiempo dejaría de parecerse.
    """
    from flask import current_app

    from app.db import obtener_cursor
    from app.services.sri.ride import (
        ErrorRide, comprobante_interno, generar, generar_desde_respuesta,
    )

    factura = FacturaService().obtener(id_factura)
    if factura is None:
        abort(404)

    comprobante = _estado_sri(id_factura)
    nombre = f"{factura.numero_factura}.pdf"

    if comprobante and comprobante["sri_estado"] == "AUTORIZADA":
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT sri_xml FROM facturas WHERE id_factura = %s",
                (id_factura,),
            )
            guardado = cursor.fetchone()["sri_xml"]
        try:
            pdf, autorizacion = generar_desde_respuesta(guardado)
            nombre = f"{autorizacion.numero}.pdf"
        except ErrorRide as error:
            current_app.logger.warning(
                "No se pudo armar el RIDE de %s: %s",
                factura.numero_factura, error,
            )
            pdf = None
    else:
        pdf = None

    if pdf is None:
        from app.services.configuracion_service import ConfiguracionService

        configuracion = ConfiguracionService()
        pdf = generar(comprobante_interno(
            factura,
            {
                "razon_social": current_app.config.get("SRI_RAZON_SOCIAL"),
                "nombre_comercial": current_app.config.get(
                    "SRI_NOMBRE_COMERCIAL") or "Totem Climb Gym",
                "ruc": current_app.config.get("SRI_RUC"),
                "direccion": configuracion.datos_del_gym().get("direccion"),
            },
            configuracion.iva_vigente(),
        ))

    return Response(
        pdf,
        mimetype="application/pdf",
        # inline: se abre en el visor del navegador, con su botón de
        # imprimir, en lugar de bajarse un archivo que después hay que
        # buscar.
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )


@bp.route("/<int:id_factura>/reemitir", methods=["POST"])
@admin_requerido
def reemitir(id_factura):
    """Vuelve a emitir una factura que el SRI rechazó.

    Una rechazada no se arregla reintentando: el SRI devolvería el
    mismo error. Hay que corregir el dato y emitir un comprobante
    nuevo, con otro número.
    """
    from app.services.sri_service import ServicioSri

    sin_identificar = request.form.get("consumidor_final") == "si"
    try:
        estado = ServicioSri().reemitir(
            id_factura,
            consumidor_final=sin_identificar,
            id_empleado=g.empleado["id_empleado"],
        )
    except ValueError as error:
        flash(str(error), "error")
    except Exception as error:  # noqa: BLE001
        flash(
            f"No se pudo emitir: {error}. La factura quedó con su "
            "comprobante nuevo reservado; reintente más tarde.", "error",
        )
    else:
        if estado == "AUTORIZADA":
            flash("El SRI autorizó la factura.", "ok")
        elif estado in ("NO_AUTORIZADA", "DEVUELTA"):
            flash(
                "El SRI la volvió a rechazar. Revise el motivo abajo.",
                "error",
            )
        else:
            flash(
                "La factura se envió y todavía no se resuelve. "
                "Vuelva a mirar en un momento.", "aviso",
            )
    return redirect(url_for("facturas.detalle", id_factura=id_factura))


@bp.route("/bloques", methods=["GET", "POST"])
@admin_requerido
def bloques():
    """Facturar al SRI los productos sueltos de un periodo.

    Las membresías y los pases se facturan solos al cobrar. Los
    productos van acá, juntados por periodo. Es de administrador: no
    es una operación de caja y se hace cada tanto, no todos los días.
    """
    from datetime import date, timedelta

    from app.services.bloque_service import ErrorBloque, ServicioBloque

    servicio = ServicioBloque()
    hoy = date.today()

    def leer_fecha(nombre, por_omision):
        texto = (request.values.get(nombre) or "").strip()
        try:
            return date.fromisoformat(texto) if texto else por_omision
        except ValueError:
            return por_omision

    desde = leer_fecha("desde", hoy.replace(day=1))
    hasta = leer_fecha("hasta", hoy)
    if desde > hasta:
        desde, hasta = hasta, desde

    emitidas = None
    if request.method == "POST":
        try:
            emitidas = servicio.emitir(desde, hasta, g.empleado["id_empleado"])
        except ErrorBloque as error:
            flash(str(error), "error")
        else:
            autorizadas = [e for e in emitidas if e["estado"] == "AUTORIZADA"]
            if len(autorizadas) == len(emitidas):
                flash(
                    f"Se emitieron {len(emitidas)} factura"
                    f"{'s' if len(emitidas) != 1 else ''} y el SRI las "
                    "autorizó.", "ok",
                )
            else:
                flash(
                    f"Se emitieron {len(emitidas)} factura"
                    f"{'s' if len(emitidas) != 1 else ''}, "
                    f"{len(autorizadas)} ya autorizada"
                    f"{'s' if len(autorizadas) != 1 else ''}. Las demás "
                    "quedaron en camino; revíselas más tarde.", "aviso",
                )

    return render_template(
        "facturas/bloques.html",
        desde=desde,
        hasta=hasta,
        resumen=servicio.resumen(desde, hasta),
        emitidas=emitidas,
        historial=servicio.historial(),
        tope_consumidor_final=ServicioSri.TOPE_CONSUMIDOR_FINAL,
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


@bp.route("/<int:id_factura>/corregir-cedula", methods=["POST"])
@login_requerido
def corregir_cedula(id_factura):
    """Corrige la cédula del cliente y reemite, sin salir de la factura.

    El SRI rechaza una factura por la identificación del comprador y
    la pantalla decía "hay que corregir la cédula" sin dar con qué:
    había que irse a Clientes, buscar a la persona, editarla, volver a
    encontrar la factura y acordarse de reemitir. Cuatro pantallas
    para cambiar diez dígitos.
    """
    factura = FacturaService().obtener(id_factura)
    if factura is None or factura.id_cliente is None:
        abort(404)

    try:
        ClienteService().corregir_identificacion(
            factura.id_cliente,
            request.form.get("cedula", ""),
            g.empleado["id_empleado"],
        )
    except ErrorValidacion as error:
        flash(list(error.errores.values())[0], "error")
        return redirect(url_for("facturas.detalle", id_factura=id_factura))
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("facturas.detalle", id_factura=id_factura))

    flash("Cédula corregida. Emitiendo de nuevo...", "ok")
    return reemitir(id_factura)


@bp.route("/contifico", methods=["GET", "POST"])
@admin_requerido
def contifico():
    """El Excel del día para registrar las ventas en Contífico.

    Los comprobantes electrónicos los emite Contífico; este sistema
    cobra y entrega el comprobante interno. Acá se exporta lo vendido
    y se confirma la carga.

    La confirmación no es un trámite: mientras no se confirme, esas
    ventas vuelven a salir en la próxima exportación, que es lo que
    evita que una se quede sin facturar. Y una vez confirmadas no
    vuelven a salir, que es lo que evita cargarlas dos veces.
    """
    from datetime import date, timedelta

    from app.services.contifico_service import ContificoService

    servicio = ContificoService()
    hoy = date.today()

    def leer_fecha(nombre, por_omision):
        texto = (request.values.get(nombre) or "").strip()
        try:
            return date.fromisoformat(texto) if texto else por_omision
        except ValueError:
            return por_omision

    desde = leer_fecha("desde", hoy)
    hasta = leer_fecha("hasta", hoy)
    if desde > hasta:
        desde, hasta = hasta, desde

    if request.method == "POST":
        accion = request.form.get("accion")
        facturas = servicio.pendientes(desde, hasta)

        if accion == "confirmar":
            # Se marcan exactamente las que se exportaron. Si alguien
            # cobró mientras el otro cargaba, esa venta queda
            # pendiente para la próxima, que es lo correcto.
            ids = [int(x) for x in request.form.getlist("id_factura")]
            marcadas = servicio.marcar_cargadas(
                ids, g.empleado["id_empleado"], desde, hasta
            )
            flash(
                f"{marcadas} venta{'s' if marcadas != 1 else ''} "
                f"marcada{'s' if marcadas != 1 else ''} como cargada"
                f"{'s' if marcadas != 1 else ''} en Contífico.", "ok",
            )
            return redirect(url_for("facturas.contifico",
                                    desde=desde, hasta=hasta))

        if not facturas:
            flash("No hay ventas pendientes en ese período.", "aviso")
            return redirect(url_for("facturas.contifico",
                                    desde=desde, hasta=hasta))

        libro = servicio.construir_excel(facturas, desde, hasta)
        nombre = f"ventas-{desde:%Y%m%d}-{hasta:%Y%m%d}.xlsx"
        return Response(
            libro,
            mimetype="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
        )

    facturas = servicio.pendientes(desde, hasta)
    return render_template(
        "facturas/contifico.html",
        desde=desde,
        hasta=hasta,
        facturas=facturas,
        resumen=servicio.resumen(facturas),
        historial=servicio.historial(),
    )
