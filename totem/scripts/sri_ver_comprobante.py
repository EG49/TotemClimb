"""Muestra que se le envio al SRI para una factura, y que contesto.

Cuando el SRI rechaza un comprobante, el mensaje dice el tipo de
problema pero no que dato lo causo. Esto muestra el comprobante tal
como se envio, para poder comparar.

    python -m scripts.sri_ver_comprobante F-000021
    python -m scripts.sri_ver_comprobante F-000021 --xml

Sin --xml muestra un resumen legible: el emisor, el receptor, el
detalle y los mensajes del SRI. Con --xml escupe el XML completo, por
si hay que mirarlo entero o mandarlo a alguien.

No cambia nada.
"""

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ETIQUETA_IDENTIFICACION = {
    "04": "RUC",
    "05": "cedula",
    "06": "pasaporte",
    "07": "consumidor final",
}

# Lo que suele estar detras de cada codigo de rechazo, en palabras.
PISTAS = {
    "69": (
        "El SRI no acepto la identificacion del receptor.\n"
        "    Las causas habituales, en orden:\n"
        "      - La cedula tiene digito verificador valido pero NO existe\n"
        "        en el registro civil. Pasa con datos inventados o de\n"
        "        prueba: nuestra validacion solo puede revisar la cuenta,\n"
        "        no si la persona existe.\n"
        "      - El tipo de identificacion no corresponde al numero\n"
        "        (una cedula marcada como RUC, o al reves).\n"
        "      - Se emitio a consumidor final por mas de USD 200, que es\n"
        "        el limite para no identificar al comprador."
    ),
    "65": "El codigo de la forma de pago no es uno de los que admite el SRI.",
    "43": "Esa clave de acceso ya estaba registrada: el comprobante ya se envio.",
    "45": "El comprobante ya fue autorizado antes.",
    "70": "El comprobante llego fuera del plazo permitido para emitirlo.",
}


def main() -> None:
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(argumentos) != 1:
        print(__doc__)
        sys.exit(1)
    numero = argumentos[0].strip()
    crudo = "--xml" in sys.argv

    from app import crear_app
    from app.db import obtener_cursor

    app = crear_app()
    with app.app_context():
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT f.numero_factura, f.fecha, f.total, f.sri_estado,
                       f.sri_clave_acceso, f.sri_mensaje, f.sri_xml,
                       f.sri_intentos, c.nombre, c.apellido, c.cedula,
                       c.correo
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                 WHERE f.numero_factura = %s
                """,
                (numero,),
            )
            factura = cursor.fetchone()

    if factura is None:
        print(f"\nNo encuentro la factura {numero}.")
        sys.exit(1)

    if not factura["sri_xml"]:
        print(f"\n{numero} no tiene comprobante guardado.")
        print(f"Estado: {factura['sri_estado'] or 'sin comprobante'}")
        sys.exit(0)

    # Lo guardado puede ser el XML firmado, o la respuesta del SRI con
    # el comprobante adentro. Se saca el comprobante en los dos casos.
    guardado = factura["sri_xml"]
    try:
        raiz = ET.fromstring(guardado.encode("utf-8"))
    except ET.ParseError as error:
        print(f"\nLo guardado no es XML valido: {error}")
        sys.exit(1)

    nodo = next(raiz.iter("comprobante"), None)
    comprobante = nodo.text if nodo is not None and nodo.text else guardado

    if crudo:
        print(comprobante)
        return

    try:
        xml = ET.fromstring(comprobante.encode("utf-8"))
    except ET.ParseError:
        print("\nNo se pudo leer el comprobante. Pruebe con --xml")
        sys.exit(1)

    def t(ruta, por_omision="—"):
        return (xml.findtext(ruta) or por_omision).strip()

    print(f"\n{factura['numero_factura']}  "
          f"{factura['fecha']:%d/%m/%Y %H:%M}  ${factura['total']}")
    print(f"Estado ante el SRI: {factura['sri_estado']}  "
          f"(intentos: {factura['sri_intentos']})")

    print("\n" + "=" * 58)
    print("  LO QUE SE ENVIO")
    print("=" * 58)
    print(f"  Ambiente        {t('infoTributaria/ambiente')}"
          f"  {'(pruebas)' if t('infoTributaria/ambiente') == '1' else '(produccion)'}")
    print(f"  RUC emisor      {t('infoTributaria/ruc')}")
    print(f"  Razon social    {t('infoTributaria/razonSocial')}")
    print(f"  Comprobante     {t('infoTributaria/estab')}-"
          f"{t('infoTributaria/ptoEmi')}-{t('infoTributaria/secuencial')}")
    print(f"  Fecha emision   {t('infoFactura/fechaEmision')}")

    tipo = t("infoFactura/tipoIdentificacionComprador")
    print(f"\n  RECEPTOR")
    print(f"    tipo          {tipo} ({ETIQUETA_IDENTIFICACION.get(tipo, '?')})")
    print(f"    identificacion {t('infoFactura/identificacionComprador')}")
    print(f"    nombre        {t('infoFactura/razonSocialComprador')}")
    print(f"    en la ficha   {factura['nombre']} {factura['apellido']}"
          f"  cedula: {factura['cedula'] or '(sin cedula)'}")

    print(f"\n  DETALLE")
    for detalle in xml.findall("detalles/detalle"):
        print(f"    {detalle.findtext('descripcion'):32} "
              f"x{detalle.findtext('cantidad')}  "
              f"${detalle.findtext('precioTotalSinImpuesto')}")
    print(f"\n    base imponible  ${t('infoFactura/totalSinImpuestos')}")
    print(f"    IVA             $"
          f"{t('infoFactura/totalConImpuestos/totalImpuesto/valor')}")
    print(f"    TOTAL           ${t('infoFactura/importeTotal')}")
    if t("infoFactura/importeTotal") != str(factura["total"]):
        print(f"\n    (la venta fue de ${factura['total']}: la diferencia son")
        print("     los productos, que no van al SRI)")

    if factura["sri_mensaje"]:
        print("\n" + "=" * 58)
        print("  LO QUE CONTESTO EL SRI")
        print("=" * 58)
        for linea in factura["sri_mensaje"].strip().splitlines():
            print(f"  {linea}")

        for codigo, pista in PISTAS.items():
            if f"identificador: {codigo}" in factura["sri_mensaje"]:
                print(f"\n  QUE SIGNIFICA\n    {pista}")
                break
    print()


if __name__ == "__main__":
    main()
