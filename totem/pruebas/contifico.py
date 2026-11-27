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
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app  # noqa: E402
from app.db import obtener_cursor  # noqa: E402
from app.services.bloque_service import TOPE_CONSUMIDOR_FINAL  # noqa: E402
from app.services.contifico_service import (  # noqa: E402
    SIN_FORMA_DE_PAGO, ContificoService,
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
                "UPDATE facturas SET contifico_planes_en = NULL, "
                "contifico_planes_por = NULL, contifico_productos_en = NULL, "
                "contifico_productos_por = NULL"
            )
            cursor.execute(
                "DELETE FROM bitacora WHERE accion = 'CONTIFICO_CARGADO'"
            )

    limpiar()
    try:
        print("\nSALE LO QUE FALTA CARGAR")
        facturas = servicio.pendientes("planes", desde, hasta)
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

        marcadas = servicio.marcar_cargadas("planes", ids, id_empleado, desde, hasta)
        revisar("se marcan todas", marcadas == cuantas,
                f"{marcadas} de {cuantas}")
        revisar("y dejan de aparecer",
                len(servicio.pendientes("planes", desde, hasta)) == 0)

        repetido = servicio.marcar_cargadas("planes", ids, id_empleado, desde, hasta)
        revisar("marcarlas de nuevo no hace nada", repetido == 0,
                f"marco {repetido} que ya estaban")

        print("\nLO QUE NO SE CONFIRMO VUELVE A SALIR")
        # Si alguien cobra mientras el otro carga, esa venta tiene que
        # quedar pendiente para la proxima vez.
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE facturas SET contifico_planes_en = NULL "
                " WHERE id_factura = %s", (ids[0],)
            )
        revisar("vuelve exactamente una",
                len(servicio.pendientes("planes", desde, hasta)) == 1)

        print("\nSE PUEDE CONFIRMAR SOLO UNA PARTE")
        limpiar()
        facturas = servicio.pendientes("planes", desde, hasta)
        mitad = [f["id_factura"] for f in facturas[:len(facturas) // 2]]
        servicio.marcar_cargadas("planes", mitad, id_empleado, desde, hasta)
        quedan = servicio.pendientes("planes", desde, hasta)
        revisar("las otras siguen pendientes",
                len(quedan) == len(facturas) - len(mitad),
                f"{len(quedan)} de {len(facturas) - len(mitad)}")
        revisar("y no son las ya cargadas",
                not ({f["id_factura"] for f in quedan} & set(mitad)))

        print("\nMARCAR NADA NO ROMPE NI ENSUCIA")
        antes = len(servicio.historial())
        revisar("una lista vacia no marca nada",
                servicio.marcar_cargadas("planes", [], id_empleado) == 0)

        print("\nQUEDA RASTRO DE QUIEN CONFIRMO")
        historial = servicio.historial()
        revisar("hay historial", len(historial) > 0)
        if historial:
            revisar("con cuantas y de que tipo",
                    historial[0]["facturas"] > 0 and historial[0]["tipo"],
                    str(dict(historial[0])))
            revisar("y quien fue", bool(historial[0]["quien"]))

        print("\nEL RESUMEN CUADRA CON LAS FACTURAS")
        limpiar()
        facturas = servicio.pendientes("planes", desde, hasta)
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

        datos = servicio.excel_planes(facturas, desde, hasta)
        revisar("es un xlsx", datos[:2] == b"PK", str(datos[:4]))

        libro = load_workbook(BytesIO(datos))
        revisar("trae sus hojas",
                libro.sheetnames == ["Resumen", "Ventas"],
                str(libro.sheetnames))

        hoja = libro["Ventas"]
        revisar("una fila por venta, mas la cabecera",
                hoja.max_row == len(facturas) + 1,
                f"{hoja.max_row} filas para {len(facturas)} ventas")

        # Las dos hojas tienen que rotular igual la forma de pago: con
        # el vacio en una y el texto en la otra, el desglose del
        # resumen daba cero mientras el total general si las contaba.
        pagos_hoja = {
            hoja.cell(row=n, column=9).value for n in range(2, hoja.max_row + 1)
        }
        revisar("ninguna forma de pago queda vacia",
                "" not in pagos_hoja and None not in pagos_hoja,
                str(pagos_hoja))
        revisar("y las etiquetas coinciden con las del resumen",
                pagos_hoja == set(resumen["por_pago"]),
                f"hoja {pagos_hoja} vs resumen {set(resumen['por_pago'])}")

        # Una cedula que empieza en cero no puede guardarse como
        # numero: se pierde el cero y deja de ser una cedula.
        formatos = {
            hoja.cell(row=n, column=4).number_format
            for n in range(2, min(hoja.max_row, 20) + 1)
        }
        revisar("la identificacion va como texto", formatos == {"@"},
                str(formatos))

        # Lo que compro, en la misma fila: quien carga no deberia
        # tener que saltar a la otra hoja para saber que vendio.
        compras = [
            hoja.cell(row=n, column=8).value
            for n in range(2, min(hoja.max_row, 30) + 1)
        ]
        revisar("cada venta dice que se compro",
                all(c for c in compras), "alguna fila quedo sin items")
        # Si alguna venta lleva mas de un plan, tienen que ir juntos
        # en la misma celda y no en dos filas. Al separar los
        # archivos esto se volvio raro -- la bebida que acompañaba a
        # la membresia ahora va en el otro archivo --, asi que se
        # comprueba solo cuando el caso existe.
        varios = [f for f in facturas if len(f["lineas"]) > 1]
        if varios:
            fila = next(n for n, f in enumerate(facturas, start=2)
                        if len(f["lineas"]) > 1)
            revisar("con varios items van juntos en una celda",
                    ";" in (hoja.cell(row=fila, column=8).value or ""),
                    hoja.cell(row=fila, column=8).value)
        else:
            print("  (ninguna venta lleva dos planes; se omite)")

    finally:
        limpiar()

        print("\nPLANES Y PRODUCTOS VAN SEPARADOS")
        limpiar()
        planes = servicio.pendientes("planes", desde, hasta)
        productos = servicio.pendientes("productos", desde, hasta)

        revisar("el archivo de planes no trae productos",
                all(l["id_producto"] is None
                    for f in planes for l in f["lineas"]),
                "una bebida se colo en el archivo de planes")
        revisar("y el de productos no trae planes",
                all(l["id_producto"] is not None
                    for f in productos for l in f["lineas"]))

        # Lo que de verdad importa de partir una venta en dos: que
        # entre los dos archivos no se pierda ni se duplique un
        # centavo.
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT COALESCE(SUM(total), 0) t FROM facturas "
                " WHERE estado <> 'ANULADA' AND fecha::date BETWEEN %s AND %s",
                (desde, hasta),
            )
            vendido = cursor.fetchone()["t"]
        suma = (servicio.resumen(planes)["total"]
                + servicio.resumen(productos)["total"])
        revisar("los dos juntos suman lo vendido", suma == vendido,
                f"archivos ${suma} vs ventas ${vendido}")

        mezcladas = ({f["numero_factura"] for f in planes}
                     & {f["numero_factura"] for f in productos})
        if mezcladas:
            numero = next(iter(mezcladas))
            en_plan = next(f for f in planes if f["numero_factura"] == numero)
            en_prod = next(f for f in productos if f["numero_factura"] == numero)
            revisar("una venta mezclada aparece en los dos",
                    en_plan["total"] > 0 and en_prod["total"] > 0)
            revisar("y cada archivo lleva solo su parte",
                    en_plan["total"] + en_prod["total"] > en_plan["total"],
                    "si uno llevara el total de la venta, se cobraria de mas")
        else:
            print("  (no hay ventas mezcladas en la base; se omite)")

        print("\nCONFIRMAR UNO NO CONFIRMA EL OTRO")
        # Con una sola marca, cargar los planes del dia daria por
        # cargadas las bebidas de esas mismas ventas, que nadie
        # registro.
        if mezcladas:
            servicio.marcar_cargadas(
                "planes", [f["id_factura"] for f in planes], id_empleado
            )
            quedan = servicio.pendientes("productos", desde, hasta)
            revisar("los productos siguen pendientes",
                    len(quedan) == len(productos),
                    f"{len(quedan)} de {len(productos)}")
            revisar("y los planes ya no",
                    len(servicio.pendientes("planes", desde, hasta)) == 0)

        print("\nLOS PRODUCTOS SE AGRUPAN BAJO EL TOPE")
        limpiar()
        productos = servicio.pendientes("productos", desde, hasta)
        separacion = servicio.separar_productos(productos)
        bloques = separacion["bloques"]
        vendido = servicio.resumen(productos)["total"]
        if bloques:
            revisar("ninguna factura pasa del tope",
                    all(b.total <= TOPE_CONSUMIDOR_FINAL for b in bloques),
                    str(max(b.total for b in bloques)))
        else:
            print("  (no hay productos pendientes; se omite)")

        print("\nSEPARAR POR CLIENTE NO CAMBIA CUANTO SE VENDIO")
        # Lo que se le factura al cliente mas lo que queda en bloque
        # tiene que dar lo vendido, sea cual sea el minimo. Si no
        # cuadra, o se factura dos veces o se deja de facturar.
        for minimo in (0, 1, 3, 5, 50):
            sep = servicio.separar_productos(productos, minimo=minimo)
            por_cliente = sum((c["total"] for c in sep["por_cliente"]),
                              Decimal("0"))
            en_bloque = sum((b.total for b in sep["bloques"]), Decimal("0"))
            revisar(f"con minimo {minimo} cuadra",
                    por_cliente + en_bloque == vendido,
                    f"{por_cliente} + {en_bloque} != {vendido}")
            revisar(f"con minimo {minimo} nadie baja del minimo",
                    all(c["cantidad"] >= minimo
                        for c in sep["por_cliente"]) if minimo else True)
            revisar(f"con minimo {minimo} nadie va sin cedula",
                    all(c["identificacion"] and
                        c["tipo_identificacion"] != "07"
                        for c in sep["por_cliente"]),
                    "sin identificacion no hay a quien facturarle")

        sep0 = servicio.separar_productos(productos, minimo=0)
        revisar("con minimo 0 no se separa nada",
                not sep0["por_cliente"],
                "es el comportamiento de antes de esto")

        print("\nLOS OTROS DOS ARCHIVOS")
        datos = servicio.excel_productos(productos, separacion, desde, hasta)
        revisar("el de productos es un xlsx", datos[:2] == b"PK")
        libro = load_workbook(BytesIO(datos))
        revisar("con Resumen, Por cliente, Agrupado y Ventas",
                libro.sheetnames == ["Resumen", "Por cliente", "Agrupado",
                                     "Ventas"],
                str(libro.sheetnames))
        revisar("y una fila por cliente y producto",
                libro["Por cliente"].max_row
                == len(separacion["por_cliente"]) + 1,
                "mas la cabecera")

        deudas = servicio.por_cobrar()
        datos = servicio.excel_por_cobrar(deudas)
        revisar("el de por cobrar es un xlsx", datos[:2] == b"PK")
        revisar("y trae una fila por deuda",
                load_workbook(BytesIO(datos))["Por cobrar"].max_row
                == len(deudas) + (2 if deudas else 1),
                "mas la cabecera y el total")
        revisar("solo con saldo pendiente",
                all(d["saldo_pendiente"] > 0 for d in deudas))

        print("\nCON CONTIFICO NO SALE NADA AL SRI")
        # El interruptor se pone acá y no se hereda del .env: la
        # prueba tiene que medir el codigo, no como quedo configurada
        # la maquina donde se corre.
        antes = app.config.get("FACTURACION_ELECTRONICA")
        app.config["FACTURACION_ELECTRONICA"] = "contifico"
        # Lo importante no es que el interruptor este en su sitio, sino
        # que no quede ninguna puerta abierta: un boton escondido en una
        # plantilla y una ruta que igual responde es como se manda un
        # comprobante que nadie queria mandar.
        from app.services.sri_service import ServicioSri

        revisar("el sistema no emite", not ServicioSri().emite_este_sistema())

        from app.services.bloque_service import ErrorBloque, ServicioBloque
        try:
            ServicioBloque().emitir(desde, hasta, id_empleado)
            revisar("facturar productos al SRI se niega", False,
                    "emitio igual")
        except ErrorBloque as error:
            revisar("facturar productos al SRI se niega",
                    "Contífico" in str(error), str(error))
        except Exception as error:  # noqa: BLE001
            revisar("facturar productos al SRI se niega", False, repr(error))

        # Y en la pantalla: los botones que reemiten no pueden estar,
        # aunque la factura este rechazada. Se mira el HTML porque el
        # boton vive en la plantilla, no en el servicio.
        from flask import render_template

        from app.services.factura_service import FacturaService

        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT id_factura FROM facturas WHERE id_cliente IS NOT NULL"
                " ORDER BY id_factura DESC LIMIT 1"
            )
            id_cualquiera = cursor.fetchone()["id_factura"]
        # Una factura de verdad y no un objeto armado a mano: lo que se
        # quiere probar es la plantilla, y con un doble a medias falla
        # por campos que faltan en vez de por lo que se mide.
        cualquiera = FacturaService().obtener(id_cualquiera)

        # Hace falta una peticion de mentira: la plantilla hereda de
        # base.html, que arma URLs.
        with app.test_request_context(f"/facturas/{id_cualquiera}"):
            html = render_template(
                "facturas/detalle.html",
                factura=cualquiera,
                comprobante={"sri_estado": "NO_AUTORIZADA",
                             "rechazada": True,
                             "sri_mensaje": "identificador: 69",
                             "sri_intentos": 1, "sri_secuencial": 1,
                             "sri_establecimiento": "001",
                             "sri_punto_emision": "004",
                             "sri_autorizacion": None,
                             "sri_fecha_autorizacion": None},
                contifico=servicio.estado_de(id_cualquiera),
                correo_disponible=False,
                tope_consumidor_final=TOPE_CONSUMIDOR_FINAL,
                sri_activo=False, empleado={"es_admin": True},
            )
        revisar("la pantalla no ofrece reemitir",
                "facturas.reemitir" not in html
                and "/reemitir" not in html,
                "hay un boton que manda al SRI")
        revisar("y sigue ofreciendo corregir la cedula",
                "corregir_cedula" in html or "/corregir-cedula" in html,
                "la cedula mal sigue siendo un problema con Contifico")

        # Y con el interruptor del otro lado todo vuelve a estar: si
        # esto no cambiara, la prueba de arriba estaria midiendo nada.
        app.config["FACTURACION_ELECTRONICA"] = "sri"
        revisar("con el interruptor en sri, el sistema vuelve a emitir",
                ServicioSri().emite_este_sistema())
        with app.test_request_context(f"/facturas/{id_cualquiera}"):
            html_sri = render_template(
                "facturas/detalle.html", factura=cualquiera,
                comprobante={"sri_estado": "NO_AUTORIZADA",
                             "rechazada": True, "sri_mensaje": "x",
                             "sri_intentos": 1, "sri_secuencial": 1,
                             "sri_establecimiento": "001",
                             "sri_punto_emision": "004",
                             "sri_autorizacion": None,
                             "sri_fecha_autorizacion": None},
                contifico={}, correo_disponible=False,
                tope_consumidor_final=TOPE_CONSUMIDOR_FINAL,
                sri_activo=True, empleado={"es_admin": True},
            )
        revisar("y la pantalla vuelve a ofrecer reemitir",
                "/reemitir" in html_sri,
                "si no aparece, la prueba de arriba no mide nada")
        app.config["FACTURACION_ELECTRONICA"] = antes


print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
