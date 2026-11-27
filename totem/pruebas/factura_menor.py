"""La factura de un menor va a nombre de su representante.

En el gimnasio los menores se registran con los datos del adulto, asi
que casi ninguno tiene cedula propia cargada. Sin cedula la factura
salia a CONSUMIDOR FINAL, y el SRI la rechaza en cuanto pasa de USD
50 -- que es el caso de la Membresia Junior, de $65:

  69 | ERROR EN LA IDENTIFICACION DEL RECEPTOR
  La factura supera los 50 USD de importe total por cuanto no puede
  ser emitida a nombre del CONSUMIDOR FINAL

Ahora la factura va al representante: es quien paga, quien firmo el
deslinde y quien tiene cedula. La membresia sigue siendo del menor en
el sistema; lo unico que cambia es a nombre de quien sale el
comprobante.

Lo que mas importa probar no es el caso del menor sino **que no se
desvie una factura que no debe desviarse**: un adulto normal tiene
que seguir saliendo a su propio nombre. Facturar a la persona
equivocada es peor que no facturar, porque el comprobante queda
autorizado en el SRI a nombre de alguien que no compro, y desde 2026
no siempre se puede corregir.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pruebas.ayudas_sri import CLAVE_P12, certificado_de_prueba  # noqa: E402

# Antes de importar nada de la aplicacion: config.py lee el entorno al
# importarse, asi que ponerlas mas abajo no sirve de nada.
P12 = Path("/tmp/menor-prueba.p12")
certificado_de_prueba(P12)
os.environ.update({
    # Esta prueba arma el XML que se le manda al SRI, asi que
    # enciende el emisor ella misma en vez de depender del .env de la
    # maquina donde se corra.
    "FACTURACION_ELECTRONICA": "sri",
    "SRI_AMBIENTE": "1", "SRI_RUC": "1790012345001",
    "SRI_RAZON_SOCIAL": "TOTEM CLIMB GYM", "SRI_DIR_MATRIZ": "Av 123",
    "SRI_DIR_ESTABLECIMIENTO": "Av 123", "SRI_ESTABLECIMIENTO": "001",
    "SRI_PUNTO_EMISION": "001", "SRI_P12_RUTA": str(P12),
    "SRI_P12_CLAVE": CLAVE_P12,
})

from xml.etree import ElementTree as ET  # noqa: E402

from app.services.sri_service import ServicioSri  # noqa: E402

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


def datos(**cambios):
    base = {
        "nombre": "Juan", "apellido": "Perez", "cedula": None,
        "correo": None, "id_representante": None,
        "rep_nombre": None, "rep_apellido": None,
        "rep_cedula": None, "rep_correo": None,
    }
    base.update(cambios)
    return base


MENOR = datos(
    id_representante=7, rep_nombre="Ana", rep_apellido="Mora",
    rep_cedula="0950439570", rep_correo="ana@gmail.com",
)

print("\nLA FACTURA DE UN MENOR VA AL REPRESENTANTE")
nombre, cedula, correo = ServicioSri._comprador_de(MENOR)
revisar("sale a nombre del adulto", nombre == "Ana Mora", nombre)
revisar("con la cedula del adulto", cedula == "0950439570", str(cedula))
revisar("y a su correo", correo == "ana@gmail.com", str(correo))

print("\nY NO SE DESVIA LA DE QUIEN NO ES MENOR")
# Lo mas importante. Facturar a la persona equivocada deja un
# comprobante autorizado a nombre de alguien que no compro.
adulto = datos(nombre="Luis", apellido="Mora", cedula="0201585387",
               correo="luis@gmail.com")
nombre, cedula, correo = ServicioSri._comprador_de(adulto)
revisar("un adulto sale a su propio nombre", nombre == "Luis Mora", nombre)
revisar("con su propia cedula", cedula == "0201585387", str(cedula))
revisar("y su propio correo", correo == "luis@gmail.com", str(correo))

print("\nSI EL REPRESENTANTE NO TIENE CEDULA, NO SIRVE DE NADA")
# Desviar la factura a un adulto sin cedula no resuelve nada y ademas
# pierde la del menor, si la tuviera. Se queda con el menor.
sin_cedula = datos(
    cedula="0201585387", correo="juan@gmail.com", id_representante=7,
    rep_nombre="Ana", rep_apellido="Mora", rep_cedula=None,
)
nombre, cedula, correo = ServicioSri._comprador_de(sin_cedula)
revisar("se queda con el menor", nombre == "Juan Perez", nombre)
revisar("y con la cedula del menor", cedula == "0201585387", str(cedula))

ninguno = datos(id_representante=7, rep_nombre="Ana", rep_apellido="Mora")
nombre, cedula, correo = ServicioSri._comprador_de(ninguno)
revisar("sin cedula en ninguno de los dos, queda sin identificacion",
        cedula is None, str(cedula))
revisar("pero con un nombre, no vacio", nombre == "Juan Perez", nombre)

print("\nEL CORREO: EL DEL ADULTO, Y SI NO EL DEL MENOR")
# El comprobante le llega a quien pago.
solo_menor = datos(
    correo="juan@gmail.com", id_representante=7, rep_nombre="Ana",
    rep_apellido="Mora", rep_cedula="0950439570", rep_correo=None,
)
revisar("si el adulto no tiene correo, se usa el del menor",
        ServicioSri._comprador_de(solo_menor)[2] == "juan@gmail.com",
        str(ServicioSri._comprador_de(solo_menor)[2]))

print("\nNO REVIENTA CON DATOS A MEDIAS")
revisar("representante sin apellido",
        ServicioSri._comprador_de(datos(
            id_representante=7, rep_nombre="Ana", rep_cedula="0950439570",
        ))[0] == "Ana")
revisar("cedula con espacios alrededor",
        ServicioSri._comprador_de(datos(
            id_representante=7, rep_nombre="Ana", rep_apellido="Mora",
            rep_cedula="  0950439570  ",
        ))[1] == "0950439570")
revisar("cedula del representante vacia, no nula",
        ServicioSri._comprador_de(datos(
            cedula="0201585387", id_representante=7, rep_nombre="Ana",
            rep_apellido="Mora", rep_cedula="   ",
        ))[1] == "0201585387",
        "una cadena de espacios no es una cedula")

print("\nY ASI LLEGA AL XML QUE SE LE MANDA AL SRI")
# Que la funcion devuelva bien no sirve si el XML sale con otra cosa.
from app import crear_app  # noqa: E402

app = crear_app()
with app.app_context():
    completo = dict(MENOR)
    completo.update({
        "fecha": __import__("datetime").date.today(),
        "metodo_pago": "EFECTIVO", "iva_porcentaje": 15,
        "sri_secuencial": 1,
        "detalle": [{
            "codigo": "P1", "nombre": "Membresia Junior", "cantidad": 1,
            "precio_unitario": 65, "va_al_sri": True, "id_plan": 1,
        }],
    })
    clave = "1" * 49
    xml = ServicioSri()._armar_xml(completo, clave)
    raiz = ET.fromstring(xml.encode("utf-8"))

    def campo(nombre):
        nodo = next(raiz.iter(nombre), None)
        return (nodo.text or "") if nodo is not None else ""

    revisar("el XML lleva la cedula del representante",
            campo("identificacionComprador") == "0950439570",
            campo("identificacionComprador"))
    revisar("y su nombre", campo("razonSocialComprador") == "Ana Mora",
            campo("razonSocialComprador"))
    revisar("con tipo 05 (cedula) y no 07 (consumidor final)",
            campo("tipoIdentificacionComprador") == "05",
            campo("tipoIdentificacionComprador"))
    revisar("y el total sigue siendo el de la venta",
            campo("importeTotal") == "65.00", campo("importeTotal"))

P12.unlink(missing_ok=True)
print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
