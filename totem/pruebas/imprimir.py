"""Lo que sale al pulsar Imprimir.

Dos documentos, un solo dibujo:

  - si el SRI autorizo la factura, sale el RIDE, que es el que vale
  - si no, sale el comprobante interno: el mismo formato, sin numero
    de autorizacion y diciendo en la cara que no es un comprobante de
    venta autorizado

Que los dibuje el mismo codigo es a proposito: si el interno se
dibujara aparte, con el tiempo dejaria de parecerse al RIDE.

Lo que mas importa comprobar es lo segundo: que el interno NO pueda
confundirse con una factura. Un papel que parece factura y no lo es
termina en la contabilidad de alguien.
"""

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app  # noqa: E402
from app.db import obtener_cursor  # noqa: E402
from app.services.configuracion_service import ConfiguracionService  # noqa: E402
from app.services.factura_service import FacturaService  # noqa: E402
from app.services.sri.ride import (  # noqa: E402
    comprobante_interno, generar, generar_desde_respuesta,
)

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


def leer(pdf: bytes) -> str:
    with TemporaryDirectory() as carpeta:
        ruta = Path(carpeta) / "d.pdf"
        ruta.write_bytes(pdf)
        try:
            return subprocess.run(
                ["pdftotext", "-layout", str(ruta), "-"],
                capture_output=True, text=True, check=True,
            ).stdout
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ""


EMISOR = {
    "razon_social": "GAIBOR ENCALADA EVANS ALEJANDRO",
    "nombre_comercial": "Totem Climb Gym",
    "ruc": "0950439570001",
    "direccion": "Av. Principal 123",
}

app = crear_app()
with app.app_context():
    with obtener_cursor() as cursor:
        cursor.execute(
            "SELECT id_factura FROM facturas WHERE estado <> 'ANULADA' "
            "ORDER BY id_factura DESC LIMIT 1"
        )
        fila = cursor.fetchone()
    if fila is None:
        print("\nHace falta al menos una factura. Se omite.")
        sys.exit(0)

    factura = FacturaService().obtener(fila["id_factura"])
    iva = ConfiguracionService().iva_vigente()
    pdf = generar(comprobante_interno(factura, EMISOR, iva))
    texto = leer(pdf)

    print("\nEL COMPROBANTE INTERNO SE PUEDE LEER")
    revisar("es un PDF", pdf[:5] == b"%PDF-", str(pdf[:8]))
    if not texto:
        print("  (sin pdftotext: no se revisa el contenido)")
        sys.exit(1 if fallas else 0)

    revisar("trae el numero de la venta", factura.numero_factura in texto)
    revisar("el nombre del cliente",
            factura.cliente_nombre.split()[0] in texto)
    revisar("y el total", f"{factura.total:.2f}" in texto)

    print("\nNO SE PUEDE CONFUNDIR CON UNA FACTURA")
    # Esto es lo que importa de verdad.
    revisar("se titula COMPROBANTE INTERNO", "COMPROBANTE INTERNO" in texto)
    revisar("NO se titula FACTURA",
            "FACTURA" not in texto.replace("COMPROBANTE INTERNO", ""),
            [l for l in texto.splitlines() if "FACTURA" in l][:1])
    revisar("dice que no es comprobante autorizado",
            "NO ES UN COMPROBANTE DE VENTA" in texto)
    revisar("lo repite al pie",
            "DOCUMENTO INTERNO DE CONTROL" in texto)
    # La marca de agua va rotada 45 grados y pdftotext no extrae texto
    # rotado, asi que no se la puede buscar en el texto. Se comprueba
    # la decision que la dibuja, que es lo que se puede romper al
    # tocar el codigo; que efectivamente se vea se mira a ojo.
    interno = comprobante_interno(factura, EMISOR, iva)
    revisar("decide llevar marca de agua", interno.sin_validez)
    revisar("y dice SIN VALIDEZ TRIBUTARIA",
            interno.marca_de_agua == "SIN VALIDEZ TRIBUTARIA",
            interno.marca_de_agua)

    print("\nY NO INVENTA DATOS QUE NO TIENE")
    revisar("sin numero de autorizacion",
            "NÚMERO DE AUTORIZACIÓN" not in texto
            and "NUMERO DE AUTORIZACION" not in texto)
    revisar("sin clave de acceso", "CLAVE DE ACCESO" not in texto)
    revisar("sin rotulo de ambiente", "AMBIENTE" not in texto)
    revisar("el numero no queda con guiones sueltos",
            "--" not in texto and "No. -" not in texto,
            [l for l in texto.splitlines() if "No." in l][:1])
    revisar("no deja la identificacion vacia",
            "Identificación:" not in texto or
            texto.split("Identificación:")[1].strip()[:1] not in ("", "F"),
            "sale el rotulo sin nada al lado")

    print("\nEL RIDE DEL SRI SIGUE SIENDO EL RIDE")
    # El mismo dibujo tiene que seguir produciendo el otro documento.
    caso = Path(__file__).parent / "datos" / "autorizacion-sri.xml"
    if caso.exists():
        pdf_sri, autorizacion = generar_desde_respuesta(
            caso.read_text(encoding="utf-8")
        )
        texto_sri = leer(pdf_sri)
        revisar("se titula FACTURA", "FACTURA" in texto_sri)
        revisar("con su numero de autorizacion",
                autorizacion.numero in texto_sri.replace(" ", "")
                or autorizacion.numero in texto_sri)
        revisar("y su clave de acceso", "CLAVE DE ACCESO" in texto_sri)
        revisar("NO dice comprobante interno",
                "COMPROBANTE INTERNO" not in texto_sri)
    else:
        print(f"  (falta {caso}; se omite)")

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
