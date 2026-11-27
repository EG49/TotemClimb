"""El Excel diario de ventas para cargar en Contifico.

Los comprobantes los emite Contifico. Este sistema cobra, entrega el
comprobante interno y al cerrar el dia exporta lo vendido; alguien lo
registra alla. Es una tarea semimanual, y las tareas semimanuales
fallan de dos formas:

  * una venta cargada dos veces deja DOS comprobantes autorizados de
    la misma venta
  * una venta que no se carga nunca es una venta sin factura

Ninguna de las dos se nota al dia siguiente. Por eso lo que mas se
prueba aca no es que el Excel se genere -- eso se ve abriendolo --
sino el ciclo de marcado, que es lo unico que separa el proceso de
esas dos fallas.

Tambien se comprueba que la regla de a quien se le factura siga
siendo la misma que usaba el SRI: si el cliente es un menor, la
factura va a su representante. Son dos caminos distintos hacia el
mismo dato, y es justo asi como dos sistemas terminan discrepando.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app  # noqa: E402
from app.db import obtener_cursor  # noqa: E402
from app.services.contifico_service import (  # noqa: E402
    CONSUMIDOR_FINAL, SIN_FORMA_DE_PAGO, ContificoService,
)

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


print("\nQUE TIPO DE IDENTIFICACION ES")
casos = [
    (None, "07", "sin cedula, consumidor final"),
    ("", "07", "vacia, consumidor final"),
    ("0950439570", "05", "diez digitos, cedula"),
    ("0950439570001", "04", "trece digitos, RUC"),
    ("AB123456", "06", "con letras, pasaporte"),
]
for valor, esperado, por_que in casos:
    revisar(por_que, ContificoService._tipo(valor) == esperado,
            ContificoService._tipo(valor))

app = crear_app()
with app.app_context():
    servicio = ContificoService()

    with obtener_cursor() as cursor:
        cursor.execute("SELECT id_empleado FROM empleados LIMIT 1")
        id_empleado = cursor.fetchone()["id_empleado"]
        cursor.execute(
            "SELECT MIN(fecha::date) a, MAX(fecha::date) b FROM facturas "
            " WHERE estado <> 'ANULADA'"
        )
        fila = cursor.fetchone()

    if fila["a"] is None:
        print("\nHace falta al menos una factura. Se omite.")
        sys.exit(1 if fallas else 0)

    desde, hasta = fila["a"], fila["b"]

    def limpiar():
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE facturas SET contifico_cargada_en = NULL, "
                "contifico_cargada_por = NULL"
            )
            cursor.execute(
                "DELETE FROM bitacora WHERE accion = 'CONTIFICO_CARGADO'"
            )

    limpiar()
    try:
        print("\nSALE LO QUE FALTA CARGAR")
        facturas = servicio.pendientes(desde, hasta)
        revisar("hay ventas pendientes", len(facturas) > 0, str(len(facturas)))
        revisar("cada una trae sus lineas",
                all(f["lineas"] for f in facturas),
                "alguna vino sin detalle")
        revisar("y a quien se le factura",
                all(f["comprador"] and f["identificacion"] for f in facturas))

        print("\nNO SALE LO QUE NO CORRESPONDE")
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) n FROM facturas WHERE estado = 'ANULADA'"
            )
            anuladas = cursor.fetchone()["n"]
        if anuladas:
            with obtener_cursor() as cursor:
                cursor.execute(
                    "SELECT numero_factura FROM facturas "
                    " WHERE estado = 'ANULADA' LIMIT 5"
                )
                numeros = {f["numero_factura"] for f in cursor.fetchall()}
            salieron = {f["numero_factura"] for f in facturas}
            revisar("las anuladas quedan afuera",
                    not (numeros & salieron),
                    "una venta deshecha no se factura")
        else:
            print("  (no hay anuladas en la base; se omite)")

        print("\nEL MENOR SE FACTURA A SU REPRESENTANTE")
        # La misma regla que usaba el SRI, y por el mismo camino.
        menores = [f for f in facturas if f["id_representante"]]
        if menores:
            f = menores[0]
            revisar("el comprador es el adulto",
                    f["comprador"] != f"{f['nombre']} {f['apellido']}",
                    f"{f['comprador']} vs {f['nombre']} {f['apellido']}")
            revisar("con la cedula del adulto",
                    f["identificacion"] == (f["rep_cedula"] or "").strip(),
                    str(f["identificacion"]))
        else:
            print("  (no hay facturas de menores en la base; se omite)")

        print("\nEL CICLO DE MARCADO")
        # Lo unico que separa esto de facturar dos veces o ninguna.
        ids = [f["id_factura"] for f in facturas]
        cuantas = len(ids)

        marcadas = servicio.marcar_cargadas(ids, id_empleado, desde, hasta)
        revisar("se marcan todas", marcadas == cuantas,
                f"{marcadas} de {cuantas}")
        revisar("y dejan de aparecer",
                len(servicio.pendientes(desde, hasta)) == 0)

        repetido = servicio.marcar_cargadas(ids, id_empleado, desde, hasta)
        revisar("marcarlas de nuevo no hace nada", repetido == 0,
                f"marco {repetido} que ya estaban")

        print("\nLO QUE NO SE CONFIRMO VUELVE A SALIR")
        # Si alguien cobra mientras el otro carga, esa venta tiene que
        # quedar pendiente para la proxima vez.
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE facturas SET contifico_cargada_en = NULL "
                " WHERE id_factura = %s", (ids[0],)
            )
        revisar("vuelve exactamente una",
                len(servicio.pendientes(desde, hasta)) == 1)

        print("\nSE PUEDE CONFIRMAR SOLO UNA PARTE")
        limpiar()
        facturas = servicio.pendientes(desde, hasta)
        mitad = [f["id_factura"] for f in facturas[:len(facturas) // 2]]
        servicio.marcar_cargadas(mitad, id_empleado, desde, hasta)
        quedan = servicio.pendientes(desde, hasta)
        revisar("las otras siguen pendientes",
                len(quedan) == len(facturas) - len(mitad),
                f"{len(quedan)} de {len(facturas) - len(mitad)}")
        revisar("y no son las ya cargadas",
                not ({f["id_factura"] for f in quedan} & set(mitad)))

        print("\nMARCAR NADA NO ROMPE NI ENSUCIA")
        antes = len(servicio.historial())
        revisar("una lista vacia no marca nada",
                servicio.marcar_cargadas([], id_empleado) == 0)

        print("\nQUEDA RASTRO DE QUIEN CONFIRMO")
        historial = servicio.historial()
        revisar("hay historial", len(historial) > 0)
        if historial:
            revisar("con cuantas y cuanto",
                    historial[0]["facturas"] > 0 and historial[0]["total"] > 0,
                    str(dict(historial[0])))
            revisar("y quien fue", bool(historial[0]["quien"]))

        print("\nEL RESUMEN CUADRA CON LAS FACTURAS")
        limpiar()
        facturas = servicio.pendientes(desde, hasta)
        resumen = servicio.resumen(facturas)
        revisar("la cuenta de facturas",
                resumen["facturas"] == len(facturas))
        revisar("el total es la suma de los totales",
                resumen["total"] == sum(f["total"] for f in facturas),
                f"{resumen['total']}")
        revisar("y el desglose por pago suma lo mismo",
                sum(resumen["por_pago"].values()) == resumen["total"],
                "si no, el que cuadra caja ve un numero y le falta plata")

        print("\nEL ARCHIVO SE GENERA Y SE PUEDE LEER")
        from openpyxl import load_workbook  # noqa: E402
        from io import BytesIO  # noqa: E402

        datos = servicio.construir_excel(facturas, desde, hasta)
        revisar("es un xlsx", datos[:2] == b"PK", str(datos[:4]))

        libro = load_workbook(BytesIO(datos))
        revisar("trae las tres hojas",
                libro.sheetnames == ["Resumen", "Facturas", "Detalle"],
                str(libro.sheetnames))

        hoja = libro["Facturas"]
        revisar("una fila por venta, mas la cabecera",
                hoja.max_row == len(facturas) + 1,
                f"{hoja.max_row} filas para {len(facturas)} ventas")

        # Las dos hojas tienen que rotular igual la forma de pago: con
        # el vacio en una y el texto en la otra, el desglose del
        # resumen daba cero mientras el total general si las contaba.
        pagos_hoja = {
            hoja.cell(row=n, column=8).value for n in range(2, hoja.max_row + 1)
        }
        revisar("ninguna forma de pago queda vacia",
                "" not in pagos_hoja and None not in pagos_hoja,
                str(pagos_hoja))
        revisar("y las etiquetas coinciden con las del resumen",
                pagos_hoja == set(resumen["por_pago"]),
                f"hoja {pagos_hoja} vs resumen {set(resumen['por_pago'])}")

        detalle = libro["Detalle"]
        lineas = sum(len(f["lineas"]) for f in facturas)
        revisar("el detalle trae todas las lineas",
                detalle.max_row == lineas + 1,
                f"{detalle.max_row - 1} de {lineas}")

        # Una cedula que empieza en cero no puede guardarse como
        # numero: se pierde el cero y deja de ser una cedula.
        formatos = {
            hoja.cell(row=n, column=4).number_format
            for n in range(2, min(hoja.max_row, 20) + 1)
        }
        revisar("la identificacion va como texto", formatos == {"@"},
                str(formatos))

    finally:
        limpiar()

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
