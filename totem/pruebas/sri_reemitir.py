"""Reemitir una factura que el SRI rechazo.

El caso real: una membresia cuyo cliente tiene una cedula que el SRI
no acepta. La venta esta bien, pero el comprobante queda
NO_AUTORIZADA y antes no habia forma de resolverlo: el reintento no
la toma —reintentar sin cambiar nada da el mismo error— y el script
de emision se niega porque ya tiene clave.

Se comprueba que:

  - una rechazada se puede reemitir, con numero y clave NUEVOS
  - se puede emitir a consumidor final, que es la salida cuando la
    cedula no se puede corregir
  - eso solo vale hasta USD 200
  - una AUTORIZADA no se reemite por accidente
  - queda anotado que hubo un intento fallido, para poder explicar
    el hueco en la numeracion

Todo lo que escribe queda deshecho al terminar.
"""

import os
import re
import sys
from decimal import Decimal
from pathlib import Path

PUNTO = "003"
P12 = Path("/tmp/reemitir_prueba.p12")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pruebas.ayudas_sri import (  # noqa: E402
    CLAVE_P12, SriDeMentira, SriQueYaLoTiene, certificado_de_prueba,
)

certificado_de_prueba(P12)
os.environ.update({
    "SRI_AMBIENTE": "1", "SRI_RUC": "1790012345001",
    "SRI_RAZON_SOCIAL": "TOTEM CLIMB GYM", "SRI_DIR_MATRIZ": "Av 123",
    "SRI_DIR_ESTABLECIMIENTO": "Av 123", "SRI_ESTABLECIMIENTO": "001",
    "SRI_PUNTO_EMISION": PUNTO, "SRI_P12_RUTA": str(P12),
    "SRI_P12_CLAVE": CLAVE_P12,
})

from xml.etree import ElementTree as ET  # noqa: E402

from app import crear_app  # noqa: E402
from app.db import obtener_cursor  # noqa: E402
from app.services import sri_service  # noqa: E402
from app.services.cobro_service import CobroService  # noqa: E402
from app.services.sri_service import ServicioSri  # noqa: E402

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


RECHAZO_69 = (
    '<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/'
    'soap/envelope/"><s:Body><RespuestaAutorizacionComprobante>'
    "<numeroComprobantes>1</numeroComprobantes><autorizaciones><autorizacion>"
    "<estado>NO AUTORIZADO</estado><ambiente>PRUEBAS</ambiente>"
    "<comprobante></comprobante><mensajes><mensaje>"
    "<identificador>69</identificador>"
    "<mensaje>ERROR EN LA IDENTIFICACION DEL RECEPTOR</mensaje>"
    "<tipo>ERROR</tipo></mensaje></mensajes>"
    "</autorizacion></autorizaciones>"
    "</RespuestaAutorizacionComprobante></s:Body></s:Envelope>"
)


class SriQueRechazaLaCedula(SriDeMentira):
    """Como el de siempre, pero rechaza mientras rechaza_cedula sea True."""

    def __init__(self):
        super().__init__()
        self.rechaza_cedula = True

    def __call__(self, url, cuerpo):
        if "recepcion" not in url.lower() and self.rechaza_cedula:
            self.llamadas += 1
            return RECHAZO_69
        return super().__call__(url, cuerpo)


def estado(id_factura):
    with obtener_cursor() as cursor:
        cursor.execute(
            "SELECT sri_estado, sri_secuencial, sri_clave_acceso, "
            "sri_mensaje, sri_xml, sri_autorizacion, total "
            "FROM facturas WHERE id_factura = %s",
            (id_factura,),
        )
        return dict(cursor.fetchone())


app = crear_app()
creadas = []

with app.app_context():
    with obtener_cursor(commit=True) as cursor:
        cursor.execute("DELETE FROM facturas WHERE sri_punto_emision = %s",
                       (PUNTO,))
        cursor.execute("DELETE FROM sri_secuenciales WHERE punto_emision = %s",
                       (PUNTO,))
        cursor.execute(
            "INSERT INTO sri_secuenciales VALUES ('001', %s, '01', 0)",
            (PUNTO,),
        )
        cursor.execute("SELECT id_cliente FROM clientes WHERE cedula IS NOT NULL LIMIT 1")
        id_cliente = cursor.fetchone()["id_cliente"]
        cursor.execute("SELECT id_empleado FROM empleados LIMIT 1")
        id_empleado = cursor.fetchone()["id_empleado"]
        cursor.execute(
            "SELECT id_plan FROM planes_membresia WHERE activo "
            "ORDER BY precio LIMIT 1"
        )
        id_plan = cursor.fetchone()["id_plan"]

    falso = SriQueRechazaLaCedula()
    sri_service.ServicioSri._soap = staticmethod(falso)
    servicio = ServicioSri()

    print("\nUNA MEMBRESIA CON CEDULA QUE EL SRI NO ACEPTA")
    id_factura, _ = CobroService().cobrar(
        {"id_cliente": str(id_cliente), "metodo_pago": "EFECTIVO"},
        [{"tipo": "plan", "id_item": id_plan, "cantidad": 1}],
        id_empleado,
    )
    creadas.append(id_factura)
    sri_service.esperar_envios(30)

    f = estado(id_factura)
    revisar("queda NO_AUTORIZADA", f["sri_estado"] == "NO_AUTORIZADA",
            str(f["sri_estado"]))
    revisar("con el motivo del SRI guardado",
            f["sri_mensaje"] and "69" in f["sri_mensaje"],
            str(f["sri_mensaje"])[:50])
    clave_vieja = f["sri_clave_acceso"]
    secuencial_viejo = f["sri_secuencial"]

    print("\nEL REINTENTO NO LA TOMA, Y HACE BIEN")
    # Reintentar sin cambiar nada daria el mismo error.
    revisar("no aparece entre las pendientes",
            all(p["id_factura"] != id_factura
                for p in servicio.repo.pendientes()))

    print("\nSE CORRIGE LA CEDULA Y SE REEMITE")
    falso.rechaza_cedula = False
    nuevo_estado = servicio.reemitir(id_factura, id_empleado=id_empleado)
    f = estado(id_factura)
    revisar("queda AUTORIZADA", nuevo_estado == "AUTORIZADA", nuevo_estado)
    revisar("con un secuencial NUEVO",
            f["sri_secuencial"] != secuencial_viejo,
            f"{secuencial_viejo} -> {f['sri_secuencial']}")
    revisar("y una clave de acceso nueva",
            f["sri_clave_acceso"] != clave_vieja)

    print("\nREEMITIR UNA FACTURA DE OTRO DIA")
    # El caso que faltaba. La clave de acceso lleva la fecha en sus
    # primeros ocho digitos y el SRI exige que sea la MISMA que
    # declara el XML. El dia del cobro las dos salen iguales aunque
    # vengan de lugares distintos, asi que un reemitir el mismo dia
    # -- lo que probaba esta suite -- nunca lo nota. Al reemitir dias
    # despues, la clave salia con la fecha de hoy y el XML con la de
    # la venta, y el SRI respondia error 58.
    falso.rechaza_cedula = True
    id_vieja, _ = CobroService().cobrar(
        {"id_cliente": str(id_cliente), "metodo_pago": "EFECTIVO"},
        [{"tipo": "plan", "id_item": id_plan, "cantidad": 1}],
        id_empleado,
    )
    creadas.append(id_vieja)
    sri_service.esperar_envios(30)

    # Se la manda al pasado, como si la venta hubiera sido hace una
    # semana y recien hoy se corrigiera el dato y se reemitiera.
    with obtener_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE facturas SET fecha = fecha - INTERVAL '7 days' "
            " WHERE id_factura = %s RETURNING fecha",
            (id_vieja,),
        )
        fecha_venta = cursor.fetchone()["fecha"]
    if hasattr(fecha_venta, "date"):
        fecha_venta = fecha_venta.date()

    falso.rechaza_cedula = False
    servicio.reemitir(id_vieja, id_empleado=id_empleado)
    f = estado(id_vieja)

    esperada = fecha_venta.strftime("%d%m%Y")
    en_la_clave = (f["sri_clave_acceso"] or "")[:8]
    revisar("la clave lleva la fecha de la venta, no la de hoy",
            en_la_clave == esperada,
            f"clave dice {en_la_clave}, la venta fue {esperada}")

    # Y que el XML diga lo mismo, que es lo que el SRI compara.
    crudo = f["sri_xml"] or ""
    hallado = re.search(r"<fechaEmision>([^<]*)</fechaEmision>", crudo) or \
        re.search(r"&lt;fechaEmision&gt;([^&]*)&lt;", crudo)
    en_el_xml = hallado.group(1).replace("/", "") if hallado else ""
    revisar("y el XML declara esa misma fecha",
            en_el_xml == esperada, f"el XML dice {en_el_xml!r}")
    revisar("las dos coinciden, que es lo que el SRI exige",
            bool(en_la_clave) and en_la_clave == en_el_xml,
            f"clave {en_la_clave} vs xml {en_el_xml}")

    print("\nEL SRI DICE QUE YA LO TIENE (error 45)")
    # Cuando el primer envio llega pero la respuesta no vuelve, el
    # reintento manda la misma clave y el SRI contesta "SECUENCIAL
    # REGISTRADO". Eso NO es un rechazo: es que el comprobante ya
    # esta alla.
    #
    # Darlo por rechazado es peligroso, no solo incomodo: la factura
    # aparece rechazada, alguien pulsa Reemitir, y se emite un SEGUNDO
    # comprobante para una venta que ya tiene el suyo autorizado. Dos
    # comprobantes validos para una sola venta.
    ya_lo_tiene = SriQueYaLoTiene()
    sri_service.ServicioSri._soap = staticmethod(ya_lo_tiene)
    servicio_2 = ServicioSri()

    id_perdida, _ = CobroService().cobrar(
        {"id_cliente": str(id_cliente), "metodo_pago": "EFECTIVO"},
        [{"tipo": "plan", "id_item": id_plan, "cantidad": 1}],
        id_empleado,
    )
    creadas.append(id_perdida)
    sri_service.esperar_envios(30)

    f = estado(id_perdida)
    revisar("NO queda como rechazada", f["sri_estado"] != "DEVUELTA",
            str(f["sri_estado"]))
    revisar("se consulta y queda AUTORIZADA",
            f["sri_estado"] == "AUTORIZADA", str(f["sri_estado"]))
    revisar("con su numero de autorizacion",
            bool(f["sri_autorizacion"]), str(f["sri_autorizacion"]))
    revisar("y no se gasto un numero nuevo",
            ya_lo_tiene.consultas >= 1,
            f"consultas={ya_lo_tiene.consultas}")

    secuencial_antes = f["sri_secuencial"]
    revisar("el comprobante sigue siendo el mismo",
            secuencial_antes is not None)

    sri_service.ServicioSri._soap = staticmethod(falso)

    print("\nA CONSUMIDOR FINAL, CUANDO LA CEDULA NO SE PUEDE CORREGIR")
    falso.rechaza_cedula = True
    id_segunda, _ = CobroService().cobrar(
        {"id_cliente": str(id_cliente), "metodo_pago": "EFECTIVO"},
        [{"tipo": "plan", "id_item": id_plan, "cantidad": 1}],
        id_empleado,
    )
    creadas.append(id_segunda)
    sri_service.esperar_envios(30)
    revisar("la segunda tambien queda rechazada",
            estado(id_segunda)["sri_estado"] == "NO_AUTORIZADA")

    falso.rechaza_cedula = False
    servicio.reemitir(id_segunda, consumidor_final=True,
                      id_empleado=id_empleado)
    f = estado(id_segunda)
    revisar("queda AUTORIZADA", f["sri_estado"] == "AUTORIZADA",
            str(f["sri_estado"]))

    raiz = ET.fromstring(f["sri_xml"].encode("utf-8"))
    xml = ET.fromstring(
        next(raiz.iter("comprobante")).text.encode("utf-8")
    )
    revisar("y sale sin identificar al comprador",
            xml.findtext("infoFactura/tipoIdentificacionComprador") == "07",
            xml.findtext("infoFactura/tipoIdentificacionComprador"))
    revisar("como CONSUMIDOR FINAL",
            xml.findtext("infoFactura/razonSocialComprador")
            == "CONSUMIDOR FINAL")

    print("\nQUEDA ANOTADO QUE HUBO UN INTENTO FALLIDO")
    # Para poder explicar el hueco en la numeracion.
    # En la bitacora y no en el mensaje de la factura: al emitir de
    # nuevo, el mensaje se pisa con el resultado nuevo.
    with obtener_cursor() as cursor:
        cursor.execute(
            """
            SELECT detalle FROM bitacora
             WHERE accion = 'COMPROBANTE_REEMITIDO' AND id_entidad = ANY(%s)
             ORDER BY id_bitacora DESC
            """,
            (creadas,),
        )
        anotados = [dict(f) for f in cursor.fetchall()]
    revisar("queda anotado en la bitacora", len(anotados) >= 2,
            f"{len(anotados)} anotaciones")
    if anotados:
        detalle = anotados[0]["detalle"]
        revisar("con la clave del comprobante que fallo",
                "clave_anterior" in str(detalle), str(detalle)[:70])
        revisar("y el motivo que dio el SRI",
                "69" in str(detalle), str(detalle)[:70])

    print("\nLO QUE NO SE PERMITE")

    def rechaza(etiqueta, hacer, texto=None):
        try:
            hacer()
        except ValueError as error:
            revisar(etiqueta, texto is None or texto in str(error),
                    str(error)[:70])
        else:
            revisar(etiqueta, False, "no levanto ValueError")

    rechaza("reemitir una AUTORIZADA",
            lambda: servicio.reemitir(id_factura), "solo se reemiten")

    # A consumidor final solo hasta USD 200.
    falso.rechaza_cedula = True
    id_cara, _ = CobroService().cobrar(
        {"id_cliente": str(id_cliente), "metodo_pago": "EFECTIVO"},
        [{"tipo": "plan", "id_item": id_plan, "cantidad": 4}],
        id_empleado,
    )
    creadas.append(id_cara)
    sri_service.esperar_envios(30)
    if Decimal(estado(id_cara)["total"]) > Decimal("200"):
        rechaza("emitir mas de $200 a consumidor final",
                lambda: servicio.reemitir(id_cara, consumidor_final=True),
                "consumidor final")
    else:
        print("  (el plan mas barato por 4 no pasa de $200; se omite)")

    rechaza("reemitir una que no existe",
            lambda: servicio.reemitir(999999999))

    with obtener_cursor(commit=True) as cursor:
        for id_f in creadas:
            # envios_correo referencia a la factura desde que
            # se leen los rebotes: va primero.
            cursor.execute("DELETE FROM envios_correo WHERE id_factura = %s",
                           (id_f,))
            cursor.execute("DELETE FROM detalle_factura WHERE id_factura = %s",
                           (id_f,))
            cursor.execute("DELETE FROM membresias WHERE id_factura = %s",
                           (id_f,))
            cursor.execute("DELETE FROM facturas WHERE id_factura = %s",
                           (id_f,))
        cursor.execute("DELETE FROM sri_secuenciales WHERE punto_emision = %s",
                       (PUNTO,))

P12.unlink(missing_ok=True)
print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
