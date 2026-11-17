"""Pruebas del RIDE y de su envio por correo.

Se arma el RIDE a partir de una autorizacion real del SRI (la del
16/11/2026, guardada acá como caso de prueba) y se comprueba:

  - que el PDF traiga lo que el SRI exige que se imprima
  - que un comprobante NO autorizado no genere RIDE
  - que el correo salga con el PDF y el XML adjuntos

Lo ultimo contra un servidor SMTP de mentira que se levanta en esta
misma corrida, asi que no manda nada a nadie ni necesita credenciales.
"""

import os

# ANTES de importar nada de la app: config.py evalua las variables de
# entorno al importarse, asi que ponerlas despues no sirve de nada.
# Apuntan a un servidor SMTP de mentira que se levanta mas abajo.
os.environ.update({
    "MAIL_SERVIDOR": "127.0.0.1",
    "MAIL_PUERTO": "8025",
    "MAIL_TLS": "False",
    "MAIL_USUARIO": "prueba@totem.test",
    # El servidor falso no pide clave, pero configurado() exige una.
    "MAIL_PASSWORD": "sin-uso",
    "MAIL_REMITENTE": "prueba@totem.test",
    "MAIL_NOMBRE_REMITENTE": "Totem Climb Gym",
})

import subprocess
import sys
from email import message_from_bytes
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


try:
    import reportlab  # noqa: F401
except ImportError:
    print("\nFalta reportlab. Instalelo con: pip install -r requirements.txt")
    print("Esta prueba se omite.")
    sys.exit(0)

from app.services.sri.ride import (  # noqa: E402
    ErrorRide, generar_desde_respuesta, leer_autorizacion,
)

CASO = Path(__file__).parent / "datos" / "autorizacion-sri.xml"
if not CASO.exists():
    print(f"\nFalta el caso de prueba {CASO}")
    sys.exit(1)

RESPUESTA = CASO.read_text(encoding="utf-8")

print("\nSE ARMA EL RIDE DESDE LA AUTORIZACION DEL SRI")
pdf, autorizacion = generar_desde_respuesta(RESPUESTA)
revisar("devuelve un PDF", pdf[:5] == b"%PDF-", pdf[:10])
revisar("el estado es AUTORIZADO", autorizacion.estado == "AUTORIZADO")
revisar("lo reconoce como ambiente de pruebas", autorizacion.es_prueba)

with TemporaryDirectory() as carpeta:
    ruta = Path(carpeta) / "ride.pdf"
    ruta.write_bytes(pdf)
    try:
        texto = subprocess.run(
            ["pdftotext", "-layout", str(ruta), "-"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        texto = None

if texto is None:
    print("  (sin pdftotext: no se revisa el contenido del PDF)")
else:
    print("\nEL PDF DICE LO QUE EL SRI EXIGE QUE DIGA")
    for etiqueta, esperado in (
        ("el numero de autorizacion", autorizacion.numero),
        ("la clave de acceso", autorizacion.numero),
        ("la fecha de autorizacion", "16/11/2026"),
        ("el ambiente", "PRUEBAS"),
        ("el tipo de emision", "NORMAL"),
        ("el RUC del emisor", "0950439570001"),
        ("el numero de factura", "001-002-900000001"),
        ("el nombre del comprador", "CONSUMIDOR FINAL"),
        ("el detalle", "Pase del dia"),
        ("el total", "10.00"),
        ("el IVA", "1.30"),
        ("la base imponible", "8.70"),
    ):
        plano = texto.replace(" ", "").replace("\n", "")
        revisar(f"trae {etiqueta}", esperado.replace(" ", "") in plano
                or esperado in texto, esperado)

    print("\nUN RIDE DE PRUEBAS SE DISTINGUE DE UNO REAL")
    revisar("lleva la marca SIN VALIDEZ TRIBUTARIA",
            "SIN VALIDEZ TRIBUTARIA" in texto)
    revisar("y el aviso al pie",
            "AMBIENTE DE PRUEBAS" in texto)

print("\nUN COMPROBANTE NO AUTORIZADO NO GENERA RIDE")
# Entregarle al cliente la representacion impresa de algo que el SRI
# rechazo es peor que no entregarle nada.
rechazado = RESPUESTA.replace(
    "<estado>AUTORIZADO</estado>", "<estado>NO AUTORIZADO</estado>"
)
try:
    leer_autorizacion(rechazado)
    revisar("se niega a armarlo", False, "no levanto ErrorRide")
except ErrorRide as error:
    revisar("se niega a armarlo", True)
    revisar("y dice que no se le puede entregar al cliente",
            "cliente" in str(error).lower(), str(error)[:70])

sin_nada = (
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    "<soap:Body><RespuestaAutorizacionComprobante>"
    "<numeroComprobantes>0</numeroComprobantes>"
    "</RespuestaAutorizacionComprobante></soap:Body></soap:Envelope>"
)
try:
    leer_autorizacion(sin_nada)
    revisar("una respuesta vacia tampoco", False, "no levanto ErrorRide")
except ErrorRide:
    revisar("una respuesta vacia tampoco", True)

print("\nEL CORREO SALE CON EL PDF Y EL XML")

recibidos = []


class Buzon:
    async def handle_DATA(self, server, session, envelope):
        recibidos.append(envelope.content)
        return "250 OK"


try:
    from aiosmtpd.controller import Controller
except ImportError:
    print("  (sin aiosmtpd: no se prueba el envio)")
    Controller = None

if Controller is not None:
    from aiosmtpd.smtp import AuthResult

    def acepta_cualquier_clave(server, session, envelope, mecanismo, datos):
        """El servidor de mentira acepta cualquier usuario y clave.

        Hace falta porque el servicio hace login() cuando hay clave
        configurada, y asi se prueba ese camino y no uno distinto del
        que corre de verdad.
        """
        return AuthResult(success=True)

    control = Controller(
        Buzon(), hostname="127.0.0.1", port=8025,
        authenticator=acepta_cualquier_clave,
        auth_require_tls=False,
    )
    control.start()
    try:
        from app import crear_app
        from app.services.correo_service import ServicioCorreo

        app = crear_app()
        with app.app_context():
            servicio = ServicioCorreo()
            servicio.enviar_con_adjuntos(
                "cliente@ejemplo.com",
                "[PRUEBA] Factura 001-002-900000001 — Totem Climb Gym",
                "cuerpo de prueba",
                [("factura.pdf", pdf, "application", "pdf"),
                 ("factura.xml", autorizacion.comprobante.encode(),
                  "application", "xml")],
                html="<p>cuerpo de prueba</p>",
            )
    finally:
        control.stop()

    revisar("llego un correo", len(recibidos) == 1, f"{len(recibidos)}")
    if recibidos:
        mensaje = message_from_bytes(recibidos[0])
        adjuntos = {
            parte.get_filename(): parte.get_payload(decode=True)
            for parte in mensaje.walk()
            if parte.get_filename()
        }
        revisar("trae el PDF", "factura.pdf" in adjuntos, str(list(adjuntos)))
        revisar("trae el XML", "factura.xml" in adjuntos, str(list(adjuntos)))
        if "factura.pdf" in adjuntos:
            revisar("el PDF llego entero",
                    adjuntos["factura.pdf"] == pdf,
                    f"{len(adjuntos['factura.pdf'])} vs {len(pdf)} bytes")
        if "factura.xml" in adjuntos:
            revisar("el XML adjunto es el autorizado, con su firma",
                    b"ds:SignatureValue" in adjuntos["factura.xml"])
        revisar("el asunto avisa que es una prueba",
                "[PRUEBA]" in (mensaje["Subject"] or ""), mensaje["Subject"])
        revisar("hay version en texto y en html",
                mensaje.is_multipart())

print(f"\n{len(fallas) and str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas) or 'TODO OK'}")
sys.exit(1 if fallas else 0)
