"""El cobro con facturacion electronica encima.

Lo que se comprueba es una sola cosa, dicha de varias maneras:

    EL COBRO NUNCA SE CAE POR CULPA DEL SRI.

Si el gimnasio se queda sin internet, si el certificado no esta, si
el SRI devuelve un error o si tarda, la venta igual tiene que
registrarse y el cliente irse con su pase. El comprobante se
resuelve despues. Un sistema de caja que deja de cobrar porque un
servicio externo no contesta es peor que no tener facturacion
electronica.

Se prueba contra la base de verdad, pero sin salir a la red: el
envio al SRI se reemplaza por uno de mentira que se puede hacer
fallar a voluntad. Asi se puede probar lo que en la realidad pasa
una vez cada tanto y nunca cuando uno mira.

Todo lo que escribe queda deshecho al terminar.
"""

import json
import sys
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app  # noqa: E402
from app.db import obtener_cursor  # noqa: E402
from app.services import sri_service  # noqa: E402
from app.services.cobro_service import CobroService  # noqa: E402
from app.services.sri_service import ServicioSri  # noqa: E402
from pruebas.ayudas_sri import (  # noqa: E402
    CLAVE_P12, SriDeMentira, certificado_de_prueba,
)

PUNTO = "008"  # un punto de emision solo para esta prueba

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)

def estado_de(id_factura: int) -> dict:
    with obtener_cursor() as cursor:
        cursor.execute(
            """
            SELECT numero_factura, total, estado, sri_estado, sri_secuencial,
                   sri_clave_acceso, sri_autorizacion, sri_intentos,
                   sri_mensaje, sri_xml IS NOT NULL AS tiene_xml
              FROM facturas WHERE id_factura = %s
            """,
            (id_factura,),
        )
        return dict(cursor.fetchone())


def limpiar(ids):
    with obtener_cursor(commit=True) as cursor:
        for id_factura in ids:
            cursor.execute(
                "DELETE FROM envios_correo WHERE id_factura = %s",
                (id_factura,),
            )
            cursor.execute(
                "DELETE FROM detalle_factura WHERE id_factura = %s",
                (id_factura,),
            )
            # Se borran, no se desvinculan: id_factura no admite nulo.
            cursor.execute(
                "DELETE FROM membresias WHERE id_factura = %s", (id_factura,)
            )
            cursor.execute(
                "DELETE FROM facturas WHERE id_factura = %s", (id_factura,)
            )
        cursor.execute(
            "DELETE FROM sri_secuenciales WHERE punto_emision = %s", (PUNTO,)
        )


def limpiar_corridas_anteriores():
    """Borra lo que haya quedado de una corrida que se cayo.

    Sin esto, una corrida interrumpida deja facturas ocupando los
    numeros de este punto de emision, y la siguiente choca contra el
    indice unico sin que quede claro por que.
    """
    with obtener_cursor(commit=True) as cursor:
        cursor.execute(
            "SELECT id_factura FROM facturas WHERE sri_punto_emision = %s",
            (PUNTO,),
        )
        viejas = [f["id_factura"] for f in cursor.fetchall()]
        for id_factura in viejas:
            cursor.execute("DELETE FROM envios_correo WHERE id_factura = %s",
                           (id_factura,))
            cursor.execute("DELETE FROM detalle_factura WHERE id_factura = %s",
                           (id_factura,))
            cursor.execute("DELETE FROM membresias WHERE id_factura = %s",
                           (id_factura,))
            cursor.execute("DELETE FROM facturas WHERE id_factura = %s",
                           (id_factura,))
    if viejas:
        print(f"  (se limpiaron {len(viejas)} facturas de una corrida "
              "anterior)")


# Estas pruebas son del emisor del SRI, asi que lo encienden ellas
# mismas. Depender de como este el .env de la maquina donde se corren
# hace que pasen o fallen por algo que no tiene que ver con el codigo.
app = crear_app()
app.config["FACTURACION_ELECTRONICA"] = "sri"
creadas = []

with TemporaryDirectory() as carpeta, app.app_context():
    ruta_p12 = Path(carpeta) / "prueba.p12"
    certificado_de_prueba(ruta_p12)

    app.config.update(
        SRI_AMBIENTE="1",
        SRI_RUC="1790012345001",
        SRI_RAZON_SOCIAL="TOTEM CLIMB GYM",
        SRI_NOMBRE_COMERCIAL="Totem",
        SRI_DIR_MATRIZ="Av. Principal 123",
        SRI_DIR_ESTABLECIMIENTO="Av. Principal 123",
        SRI_ESTABLECIMIENTO="001",
        SRI_PUNTO_EMISION=PUNTO,
        SRI_P12_RUTA=str(ruta_p12),
        SRI_P12_CLAVE=CLAVE_P12,
    )

    limpiar_corridas_anteriores()

    with obtener_cursor(commit=True) as cursor:
        cursor.execute(
            "DELETE FROM sri_secuenciales WHERE punto_emision = %s", (PUNTO,)
        )
        cursor.execute(
            """
            INSERT INTO sri_secuenciales
                (establecimiento, punto_emision, tipo_comprobante,
                 ultimo_secuencial)
            VALUES ('001', %s, '01', 0)
            """,
            (PUNTO,),
        )
        cursor.execute(
            "SELECT id_cliente FROM clientes WHERE cedula IS NOT NULL "
            "ORDER BY id_cliente LIMIT 1"
        )
        fila = cursor.fetchone()
        id_cliente = fila["id_cliente"] if fila else None
        cursor.execute(
            "SELECT id_producto FROM productos WHERE activo ORDER BY id_producto LIMIT 1"
        )
        id_producto = cursor.fetchone()["id_producto"]
        cursor.execute(
            "SELECT id_plan, precio FROM planes_membresia WHERE activo "
            "ORDER BY id_plan LIMIT 1"
        )
        plan = cursor.fetchone()
        id_plan, precio_plan = plan["id_plan"], plan["precio"]
        cursor.execute("SELECT id_empleado FROM empleados LIMIT 1")
        id_empleado = cursor.fetchone()["id_empleado"]

    if id_cliente is None:
        print("\nHace falta al menos un cliente con cedula. Se omite.")
        sys.exit(0)

    servicio = CobroService()
    falso = SriDeMentira()
    sri_service.ServicioSri._soap = staticmethod(falso)

    def cobrar(items=None):
        formulario = {"id_cliente": str(id_cliente), "metodo_pago": "EFECTIVO"}
        if items is None:
            items = [{"tipo": "plan", "id_item": id_plan, "cantidad": 1}]
        id_factura, _ = servicio.cobrar(formulario, items, id_empleado)
        creadas.append(id_factura)
        sri_service.esperar_envios(30)
        return id_factura

    print("\nCON TODO BIEN")
    falso.modo = "bien"
    id_factura = cobrar()
    f = estado_de(id_factura)
    revisar("la venta queda registrada", f["estado"] in ("EMITIDA", "PAGADA"),
            f["estado"])
    revisar("se le asigno secuencial", f["sri_secuencial"] == 1,
            str(f["sri_secuencial"]))
    revisar("y clave de acceso de 49 digitos",
            f["sri_clave_acceso"] and len(f["sri_clave_acceso"].strip()) == 49)
    revisar("queda AUTORIZADA", f["sri_estado"] == "AUTORIZADA",
            f"{f['sri_estado']} · {f['sri_mensaje']}")
    revisar("guarda el numero de autorizacion", bool(f["sri_autorizacion"]))
    revisar("y guarda el XML firmado", f["tiene_xml"])

    print("\nSIN INTERNET: LA VENTA IGUAL SE REGISTRA")
    # Lo que de verdad importa. Si esto falla, el gimnasio no puede
    # cobrar cuando se le cae la conexion.
    falso.modo = "sin internet"
    id_sin_red = cobrar()
    f = estado_de(id_sin_red)
    revisar("la venta queda registrada igual",
            f["estado"] in ("EMITIDA", "PAGADA"), f["estado"])
    revisar("con su numero de factura", bool(f["numero_factura"]))
    revisar("el secuencial no se perdio", f["sri_secuencial"] == 2,
            str(f["sri_secuencial"]))
    revisar("el comprobante queda para reintentar",
            f["sri_estado"] in ("PENDIENTE", "FIRMADA"), f["sri_estado"])
    revisar("el XML ya esta firmado, listo para reenviar", f["tiene_xml"])

    print("\nY CUANDO VUELVE EL INTERNET, SE RESUELVE SOLO")
    falso.modo = "bien"
    resumen = ServicioSri().reintentar_pendientes()
    f = estado_de(id_sin_red)
    revisar("el reintento la autoriza", f["sri_estado"] == "AUTORIZADA",
            f"{f['sri_estado']} · {f['sri_mensaje']}")
    revisar("y lo cuenta en el resumen", resumen["autorizadas"] >= 1,
            str(resumen))

    print("\nSI EL SRI TARDA EN CONTESTAR")
    falso.modo = "lento"
    id_lento = cobrar()
    f = estado_de(id_lento)
    revisar("la venta queda registrada igual",
            f["estado"] in ("EMITIDA", "PAGADA"), f["estado"])
    revisar("y el comprobante queda para reintentar",
            f["sri_estado"] in ("PENDIENTE", "FIRMADA"), f["sri_estado"])

    print("\nSI EL SRI RECHAZA EL COMPROBANTE")
    falso.modo = "devuelta"
    id_devuelta = cobrar()
    f = estado_de(id_devuelta)
    revisar("la venta queda registrada igual",
            f["estado"] in ("EMITIDA", "PAGADA"), f["estado"])
    revisar("el comprobante queda DEVUELTA", f["sri_estado"] == "DEVUELTA",
            f["sri_estado"])
    revisar("y se guarda el motivo que dio el SRI",
            f["sri_mensaje"] and "43" in f["sri_mensaje"],
            str(f["sri_mensaje"])[:60])
    revisar("una DEVUELTA no se reintenta sola",
            all(p["id_factura"] != id_devuelta
                for p in ServicioSri().repo.pendientes()),
            "la tomo el reintento")

    print("\nSIN CERTIFICADO NI DATOS DEL EMISOR, EL GIMNASIO SIGUE COBRANDO")
    # Es el estado del gimnasio hasta terminar de habilitarse.
    guardado = app.config["SRI_RUC"]
    app.config["SRI_RUC"] = None
    falso.modo = "bien"
    antes = falso.llamadas
    id_sin_sri = cobrar()
    f = estado_de(id_sin_sri)
    revisar("la venta se registra", f["estado"] in ("EMITIDA", "PAGADA"),
            f["estado"])
    revisar("sin comprobante electronico", f["sri_estado"] is None,
            str(f["sri_estado"]))
    revisar("y ni siquiera se intenta hablar con el SRI",
            falso.llamadas == antes, f"{falso.llamadas - antes} llamadas")
    app.config["SRI_RUC"] = guardado

    print("\nAL SRI VAN SOLO MEMBRESIAS Y PASES")
    # Los productos se facturan aparte y en bloque, a mano. En una
    # venta mixta la factura electronica lleva solo la membresia, y
    # su total es MENOR que el de la venta. Es lo correcto.
    falso.modo = "bien"
    antes_numero = ServicioSri().repo.ultimo_secuencial("001", PUNTO)

    id_solo_productos = cobrar(
        [{"tipo": "producto", "id_item": id_producto, "cantidad": 2}]
    )
    f = estado_de(id_solo_productos)
    revisar("una venta de puros productos se registra igual",
            f["estado"] in ("EMITIDA", "PAGADA"), f["estado"])
    revisar("y NO genera comprobante electronico", f["sri_estado"] is None,
            str(f["sri_estado"]))
    revisar("ni gasta un numero de la numeracion",
            ServicioSri().repo.ultimo_secuencial("001", PUNTO) == antes_numero,
            f"paso de {antes_numero} a "
            f"{ServicioSri().repo.ultimo_secuencial('001', PUNTO)}")

    id_mixta = cobrar([
        {"tipo": "plan", "id_item": id_plan, "cantidad": 1},
        {"tipo": "producto", "id_item": id_producto, "cantidad": 2},
    ])
    f = estado_de(id_mixta)
    revisar("una venta mixta SI genera comprobante",
            f["sri_estado"] == "AUTORIZADA",
            f"{f['sri_estado']} · {f['sri_mensaje']}")

    # Lo que importa: el comprobante cubre solo la membresia.
    from xml.etree import ElementTree as ET

    with obtener_cursor() as cursor:
        cursor.execute("SELECT sri_xml FROM facturas WHERE id_factura = %s",
                       (id_mixta,))
        guardado = cursor.fetchone()["sri_xml"]
    comprobante = ET.fromstring(guardado.encode("utf-8"))
    texto = next(comprobante.iter("comprobante")).text
    xml = ET.fromstring(texto.encode("utf-8"))

    detalles = xml.findall("detalles/detalle")
    revisar("el comprobante lleva una sola linea", len(detalles) == 1,
            f"{len(detalles)} lineas: "
            + ", ".join(d.findtext('descripcion') for d in detalles))
    revisar("y es la membresia, no el producto",
            "agua" not in (detalles[0].findtext("descripcion") or "").lower()
            if detalles else False,
            detalles[0].findtext("descripcion") if detalles else "")

    total_comprobante = Decimal(xml.findtext("infoFactura/importeTotal"))
    revisar("el total del comprobante es el de la membresia sola",
            total_comprobante == Decimal(precio_plan).quantize(Decimal("0.01")),
            f"comprobante {total_comprobante}, plan {precio_plan}")
    revisar("y es MENOR que el total de la venta",
            total_comprobante < Decimal(f["total"]),
            f"comprobante {total_comprobante}, venta {f['total']}")

    print("\nCADA FACTURA SE LLEVA UN NUMERO DISTINTO")
    with obtener_cursor() as cursor:
        cursor.execute(
            "SELECT sri_secuencial FROM facturas WHERE id_factura = ANY(%s) "
            "AND sri_secuencial IS NOT NULL",
            (creadas,),
        )
        numeros = [f["sri_secuencial"] for f in cursor.fetchall()]
    revisar("ninguno se repite", len(numeros) == len(set(numeros)),
            str(sorted(numeros)))

    limpiar(creadas)

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
