"""Arma el RIDE de un comprobante autorizado y lo manda por correo.

Sirve para ver cómo le llega al cliente: el PDF que va a leer y el
XML autorizado, que es la factura ante el SRI. Van los dos adjuntos.

Se corre desde la carpeta totem:

    python -m scripts.sri_ride_correo sri_pruebas/<clave>-autorizacion.xml \\
        correo@ejemplo.com

Sin el correo de destino solo genera el PDF y lo deja al lado del XML,
sin mandar nada:

    python -m scripts.sri_ride_correo sri_pruebas/<clave>-autorizacion.xml

Un comprobante que el SRI NO autorizó no genera RIDE: el script se
niega y dice por qué. Entregarle a un cliente la representación
impresa de algo que el SRI rechazó es peor que no entregarle nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.sri.ride import ErrorRide, generar_desde_respuesta


def cargar_env() -> None:
    import os

    archivo = Path(".env")
    if not archivo.exists():
        print("No encuentro el .env en esta carpeta.")
        sys.exit(1)
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            clave, _, valor = linea.partition("=")
            os.environ.setdefault(clave.strip(), valor.strip())


def cuerpo(autorizacion, numero: str) -> tuple[str, str]:
    aviso_texto = ""
    aviso_html = ""
    if autorizacion.es_prueba:
        aviso_texto = (
            "\nAVISO: este comprobante se emitió en el ambiente de PRUEBAS "
            "del SRI y NO tiene validez tributaria.\n"
        )
        aviso_html = (
            '<p style="background:#fff3cd;border:1px solid #e0c56a;'
            'padding:10px;border-radius:6px">'
            "<b>Aviso:</b> este comprobante se emitió en el ambiente de "
            "<b>PRUEBAS</b> del SRI y <b>no tiene validez tributaria</b>."
            "</p>"
        )

    texto = (
        f"Factura {numero}\n"
        f"Totem Climb Gym\n\n"
        f"Adjuntamos su factura electrónica en dos archivos:\n"
        f"  - El PDF, para leer o imprimir.\n"
        f"  - El XML autorizado por el SRI, que es el comprobante oficial.\n"
        f"{aviso_texto}\n"
        f"Número de autorización:\n{autorizacion.numero}\n\n"
        f"Puede verificarlo en www.sri.gob.ec con esa clave de acceso.\n"
    )

    html = (
        '<div style="font-family:system-ui,sans-serif;max-width:560px">'
        f"<h2 style='margin:0 0 4px'>Factura {numero}</h2>"
        "<p style='margin:0 0 16px;color:#666'>Totem Climb Gym</p>"
        f"{aviso_html}"
        "<p>Adjuntamos su factura electrónica en dos archivos: el "
        "<b>PDF</b>, para leer o imprimir, y el <b>XML</b> autorizado "
        "por el SRI, que es el comprobante oficial.</p>"
        "<p style='font-size:13px;color:#555'>Número de autorización<br>"
        f"<code style='font-size:11px'>{autorizacion.numero}</code></p>"
        "<p style='font-size:13px;color:#555'>Puede verificarlo en "
        "www.sri.gob.ec con esa clave de acceso.</p>"
        "</div>"
    )
    return texto, html


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    ruta = Path(sys.argv[1])
    if not ruta.exists():
        print(f"No encuentro {ruta}")
        sys.exit(1)
    destinatario = sys.argv[2].strip() if len(sys.argv) > 2 else None

    try:
        pdf, autorizacion = generar_desde_respuesta(
            ruta.read_text(encoding="utf-8")
        )
    except ErrorRide as error:
        print(f"\nNo se puede armar el RIDE:\n{error}")
        sys.exit(1)

    clave = autorizacion.numero or ruta.stem
    destino_pdf = ruta.with_name(f"{clave}-ride.pdf")
    destino_pdf.write_bytes(pdf)

    print(f"\nAmbiente: {autorizacion.ambiente}")
    print(f"RIDE generado: {destino_pdf}  ({len(pdf)} bytes)")
    if autorizacion.es_prueba:
        print("Lleva la marca SIN VALIDEZ TRIBUTARIA, porque es de pruebas.")

    if not destinatario:
        print("\nSin correo de destino: no se manda nada. Abra el PDF.")
        return

    # El XML autorizado, que es la factura ante el SRI.
    xml_autorizado = autorizacion.comprobante.encode("utf-8")

    cargar_env()
    from app import crear_app
    from app.services.correo_service import CorreoNoConfigurado, ServicioCorreo

    numero = f"{clave[24:27]}-{clave[27:30]}-{clave[30:39]}" if len(clave) == 49 else clave

    app = crear_app()
    with app.app_context():
        servicio = ServicioCorreo()
        texto, html = cuerpo(autorizacion, numero)
        asunto = f"Factura {numero} — Totem Climb Gym"
        if autorizacion.es_prueba:
            asunto = f"[PRUEBA] {asunto}"
        try:
            servicio.enviar_con_adjuntos(
                destinatario,
                asunto,
                texto,
                [
                    (f"{clave}.pdf", pdf, "application", "pdf"),
                    (f"{clave}.xml", xml_autorizado, "application", "xml"),
                ],
                html=html,
            )
        except CorreoNoConfigurado as error:
            print(f"\n{error}")
            sys.exit(1)
        except Exception as error:  # noqa: BLE001
            print(f"\nNo se pudo enviar: {type(error).__name__}: {error}")
            sys.exit(1)

    print(f"Enviado a {destinatario}, con el PDF y el XML adjuntos.")


if __name__ == "__main__":
    main()
