"""El correo al cliente: la factura del SRI cuando existe.

El mismo boton hace dos cosas segun el estado del comprobante:

  - factura AUTORIZADA  -> se manda el RIDE en PDF y el XML autorizado
  - todavia no          -> se manda el comprobante interno, que es lo
                           que hay

Quien cobra no tiene por que saber en que estado quedo el comprobante
ante el SRI, ni elegir entre dos envios parecidos.

Se prueba contra un servidor SMTP de mentira que se levanta en esta
misma corrida: no manda correos de verdad ni necesita credenciales.
Todo lo que escribe en la base queda deshecho al terminar.
"""

import os

# ANTES de importar la app: config.py lee las variables de entorno al
# importarse, asi que ponerlas despues no sirve de nada.
os.environ.update({
    "MAIL_SERVIDOR": "127.0.0.1",
    "MAIL_PUERTO": "8027",
    "MAIL_TLS": "False",
    "MAIL_USUARIO": "prueba@totem.test",
    "MAIL_PASSWORD": "sin-uso",
    "MAIL_REMITENTE": "prueba@totem.test",
    "MAIL_NOMBRE_REMITENTE": "Totem Climb Gym",
})

import sys  # noqa: E402
from email import message_from_bytes  # noqa: E402
from pathlib import Path  # noqa: E402
from tempfile import TemporaryDirectory  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


try:
    import reportlab  # noqa: F401
    from aiosmtpd.controller import Controller
    from aiosmtpd.smtp import AuthResult
except ImportError as error:
    print(f"\nFaltan dependencias de la prueba ({error.name}).")
    print("Instalelas con:  pip install -r requirements.txt")
    sys.exit(0)

from app import crear_app  # noqa: E402
from app.db import obtener_cursor  # noqa: E402
from app.services import sri_service  # noqa: E402
from app.services.cobro_service import CobroService  # noqa: E402
from app.services.correo_service import ServicioCorreo, esperar_envios  # noqa: E402

# Las piezas compartidas con pruebas/sri_cobro.py.
from pruebas.ayudas_sri import (  # noqa: E402
    CLAVE_P12, SriDeMentira, certificado_de_prueba,
)

PUNTO = "007"

recibidos = []


class Buzon:
    async def handle_DATA(self, server, session, envelope):
        recibidos.append(envelope.content)
        return "250 OK"


def acepta_cualquier_clave(server, session, envelope, mecanismo, datos):
    return AuthResult(success=True)


def adjuntos_de(crudo):
    mensaje = message_from_bytes(crudo)
    archivos = {
        parte.get_filename(): parte.get_payload(decode=True)
        for parte in mensaje.walk()
        if parte.get_filename()
    }
    return mensaje, archivos


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
        SRI_AMBIENTE="1", SRI_RUC="1790012345001",
        SRI_RAZON_SOCIAL="TOTEM CLIMB GYM", SRI_NOMBRE_COMERCIAL="Totem",
        SRI_DIR_MATRIZ="Av. Principal 123",
        SRI_DIR_ESTABLECIMIENTO="Av. Principal 123",
        SRI_ESTABLECIMIENTO="001", SRI_PUNTO_EMISION=PUNTO,
        SRI_P12_RUTA=str(ruta_p12), SRI_P12_CLAVE=CLAVE_P12,
    )

    with obtener_cursor(commit=True) as cursor:
        cursor.execute(
            "DELETE FROM sri_secuenciales WHERE punto_emision = %s", (PUNTO,)
        )
        cursor.execute(
            "INSERT INTO sri_secuenciales (establecimiento, punto_emision,"
            " tipo_comprobante, ultimo_secuencial) VALUES ('001', %s, '01', 0)",
            (PUNTO,),
        )
        cursor.execute(
            "SELECT id_cliente FROM clientes WHERE cedula IS NOT NULL "
            "AND correo IS NOT NULL ORDER BY id_cliente LIMIT 1"
        )
        fila = cursor.fetchone()
        # Una membresia, no un producto: al SRI van solo membresias y
        # pases, asi que una venta de productos no generaria factura
        # electronica y esta prueba no probaria nada.
        cursor.execute(
            "SELECT id_plan FROM planes_membresia WHERE activo "
            "ORDER BY id_plan LIMIT 1"
        )
        id_plan = cursor.fetchone()["id_plan"]
        cursor.execute("SELECT id_empleado FROM empleados LIMIT 1")
        id_empleado = cursor.fetchone()["id_empleado"]

    if fila is None:
        print("\nHace falta un cliente con cedula y correo. Se omite.")
        sys.exit(0)
    id_cliente = fila["id_cliente"]

    servicio = CobroService()
    falso = SriDeMentira()
    sri_service.ServicioSri._soap = staticmethod(falso)

    def cobrar():
        id_factura, _ = servicio.cobrar(
            {"id_cliente": str(id_cliente), "metodo_pago": "EFECTIVO"},
            [{"tipo": "plan", "id_item": id_plan, "cantidad": 1}],
            id_empleado,
        )
        creadas.append(id_factura)
        sri_service.esperar_envios(30)
        return id_factura

    control = Controller(
        Buzon(), hostname="127.0.0.1", port=8027,
        authenticator=acepta_cualquier_clave, auth_require_tls=False,
    )
    control.start()
    try:
        correo = ServicioCorreo()

        print("\nCON LA FACTURA AUTORIZADA, SE MANDA LA DEL SRI")
        falso.modo = "bien"
        id_factura = cobrar()
        factura = servicio.facturas.obtener(id_factura)

        recibidos.clear()
        destino, electronica, motivo = correo.enviar_factura(factura, id_empleado)
        esperar_envios(30)

        revisar("sale la factura electronica, no el recibo interno",
                electronica is True)
        revisar("llego un correo", len(recibidos) == 1, str(len(recibidos)))

        if recibidos:
            mensaje, archivos = adjuntos_de(recibidos[0])
            nombres = list(archivos)
            revisar("con dos adjuntos", len(archivos) == 2, str(nombres))
            revisar("uno es el RIDE en PDF",
                    any(n.endswith(".pdf") for n in nombres), str(nombres))
            revisar("y el otro el XML", any(n.endswith(".xml") for n in nombres),
                    str(nombres))

            pdf = next((c for n, c in archivos.items() if n.endswith(".pdf")), b"")
            revisar("el PDF es un PDF de verdad", pdf[:5] == b"%PDF-", str(pdf[:8]))

            xml = next((c for n, c in archivos.items() if n.endswith(".xml")), b"")
            revisar("el XML adjunto es el autorizado, con su firma",
                    b"ds:SignatureValue" in xml)
            revisar("y es el comprobante, no la respuesta del SRI",
                    b"<factura" in xml and b"RespuestaAutorizacion" not in xml)

            asunto = mensaje["Subject"] or ""
            revisar("el asunto dice Factura", "Factura" in asunto, asunto)
            revisar("y avisa que es de pruebas", "[PRUEBA]" in asunto, asunto)
            revisar("el correo va al cliente", destino and "@" in destino,
                    str(destino))

            cuerpo = recibidos[0].decode("utf-8", "replace")
            revisar("el cuerpo NO repite el detalle de la compra",
                    "Subtotal" not in cuerpo,
                    "repetirlo abre la puerta a que diga otra cosa que el PDF")

        print("\nSIN AUTORIZAR, SE MANDA EL COMPROBANTE INTERNO")
        # Es lo que hay: no se le puede entregar al cliente una factura
        # que el SRI todavia no autorizo.
        falso.modo = "sin internet"
        id_pendiente = cobrar()
        pendiente = servicio.facturas.obtener(id_pendiente)

        recibidos.clear()
        destino, electronica, motivo = correo.enviar_factura(pendiente, id_empleado)
        esperar_envios(30)

        revisar("sale el comprobante interno", electronica is False)
        revisar("y dice que el comprobante sigue autorizandose",
                motivo == "autorizandose", str(motivo))
        revisar("llego un correo", len(recibidos) == 1, str(len(recibidos)))
        if recibidos:
            mensaje, archivos = adjuntos_de(recibidos[0])
            revisar("sin adjuntos", not archivos, str(list(archivos)))
            revisar("y el cuerpo avisa que no es comprobante del SRI",
                    "No constituye comprobante" in
                    recibidos[0].decode("utf-8", "replace"))
        print("\nSI LA AUTORIZACION LLEGA MIENTRAS SE ESPERA, SALE LA FACTURA")
        # El caso real: se cobra y se pulsa Enviar un segundo despues,
        # cuando el SRI todavia no resolvio. Sin la espera, el correo
        # caia siempre en el comprobante interno justo cuando mas se
        # queria la factura.
        import threading as _hilos

        falso.modo = "sin internet"
        id_tarde = cobrar()
        tarde = servicio.facturas.obtener(id_tarde)

        def autorizar_en_3_segundos():
            import time
            time.sleep(3)
            falso.modo = "bien"
            with app.app_context():
                sri_service.ServicioSri().reintentar_pendientes()

        _hilos.Thread(target=autorizar_en_3_segundos, daemon=True).start()

        recibidos.clear()
        destino, electronica, motivo = correo.enviar_factura(tarde, id_empleado)
        esperar_envios(30)

        revisar("el correo espero y salio la factura electronica",
                electronica is True, f"motivo: {motivo}")
        if recibidos:
            _, archivos = adjuntos_de(recibidos[0])
            revisar("con sus dos adjuntos", len(archivos) == 2,
                    str(list(archivos)))
    finally:
        control.stop()

    with obtener_cursor(commit=True) as cursor:
        for id_factura in creadas:
            # envios_correo referencia a la factura desde que
            # se leen los rebotes: va primero.
            cursor.execute("DELETE FROM envios_correo WHERE id_factura = %s",
                           (id_factura,))
            cursor.execute("DELETE FROM detalle_factura WHERE id_factura = %s",
                           (id_factura,))
            cursor.execute("DELETE FROM membresias WHERE id_factura = %s",
                           (id_factura,))
            cursor.execute("DELETE FROM facturas WHERE id_factura = %s",
                           (id_factura,))
        cursor.execute("DELETE FROM sri_secuenciales WHERE punto_emision = %s",
                       (PUNTO,))

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
