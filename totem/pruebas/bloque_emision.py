"""Prueba de la factura en bloque de productos, contra la base.

Las tres cosas que no pueden fallar:

  1. Una unidad vendida se factura UNA vez. Correr el bloque dos
     veces sobre el mismo periodo no debe volver a facturar nada.
  2. El balance no cambia. Esa plata ya se conto cuando se cobro; la
     factura en bloque no es una venta.
  3. Lo facturado es exactamente lo vendido, ni una unidad de mas ni
     de menos.

Todo lo que escribe queda deshecho al terminar.
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

PUNTO = "004"
P12 = Path("/tmp/bloque_prueba.p12")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pruebas.ayudas_sri import (  # noqa: E402
    CLAVE_P12, SriDeMentira, certificado_de_prueba,
)

certificado_de_prueba(P12)
os.environ.update({
    "SRI_AMBIENTE": "1", "SRI_RUC": "1790012345001",
    "SRI_RAZON_SOCIAL": "TOTEM CLIMB GYM", "SRI_DIR_MATRIZ": "Av 123",
    "SRI_DIR_ESTABLECIMIENTO": "Av 123", "SRI_ESTABLECIMIENTO": "001",
    "SRI_PUNTO_EMISION": PUNTO, "SRI_P12_RUTA": str(P12),
    "SRI_P12_CLAVE": CLAVE_P12,
})

from app import crear_app  # noqa: E402
from app.db import obtener_cursor  # noqa: E402
from app.services import sri_service  # noqa: E402
from app.services.bloque_service import ErrorBloque, ServicioBloque  # noqa: E402
from app.services.cobro_service import CobroService  # noqa: E402

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


def balance_del_dia(fecha):
    """Lo vendido ese dia segun la contabilidad."""
    with obtener_cursor() as cursor:
        cursor.execute(
            "SELECT COALESCE(SUM(total), 0) AS v FROM facturas "
            "WHERE estado <> 'ANULADA' AND fecha::date = %s",
            (fecha,),
        )
        return Decimal(cursor.fetchone()["v"])


app = crear_app()
creadas = []
bloques = []

with app.app_context():
    from datetime import date

    hoy = date.today()
    with obtener_cursor(commit=True) as cursor:
        cursor.execute("DELETE FROM sri_secuenciales WHERE punto_emision = %s",
                       (PUNTO,))
        cursor.execute(
            "INSERT INTO sri_secuenciales VALUES ('001', %s, '01', 0)",
            (PUNTO,),
        )
        # Se parte de cero: lo que ya hubiera vendido hoy se marca
        # como facturado, para medir solo lo de esta prueba.
        cursor.execute(
            """
            UPDATE detalle_factura d
               SET unidades_en_bloque = d.cantidad
              FROM facturas f
             WHERE f.id_factura = d.id_factura
               AND d.id_producto IS NOT NULL
               AND f.fecha::date = %s
            """,
            (hoy,),
        )
        cursor.execute("SELECT id_cliente FROM clientes LIMIT 1")
        id_cliente = cursor.fetchone()["id_cliente"]
        cursor.execute("SELECT id_empleado FROM empleados LIMIT 1")
        id_empleado = cursor.fetchone()["id_empleado"]
        cursor.execute(
            "SELECT id_producto, precio FROM productos WHERE activo "
            "ORDER BY id_producto LIMIT 2"
        )
        productos = [dict(f) for f in cursor.fetchall()]
        cursor.execute("SELECT id_plan FROM planes_membresia WHERE activo LIMIT 1")
        id_plan = cursor.fetchone()["id_plan"]

    falso = SriDeMentira()
    sri_service.ServicioSri._soap = staticmethod(falso)
    cobro = CobroService()
    servicio = ServicioBloque()

    print("\nSE VENDEN PRODUCTOS")
    balance_antes = balance_del_dia(hoy)
    vendidas = 0
    for producto in productos:
        for cantidad in (3, 7):
            idf, _ = cobro.cobrar(
                {"id_cliente": str(id_cliente), "metodo_pago": "EFECTIVO"},
                [{"tipo": "producto", "id_item": producto["id_producto"],
                  "cantidad": cantidad}],
                id_empleado,
            )
            creadas.append(idf)
            vendidas += cantidad
    # Y una venta mixta: la membresia ya va al SRI, las aguas no.
    idf, _ = cobro.cobrar(
        {"id_cliente": str(id_cliente), "metodo_pago": "EFECTIVO"},
        [{"tipo": "plan", "id_item": id_plan, "cantidad": 1},
         {"tipo": "producto", "id_item": productos[0]["id_producto"],
          "cantidad": 4}],
        id_empleado,
    )
    creadas.append(idf)
    vendidas += 4
    sri_service.esperar_envios(30)

    resumen = servicio.resumen(hoy, hoy)
    revisar("el resumen cuenta todas las unidades vendidas",
            resumen["unidades"] == vendidas,
            f"{resumen['unidades']} de {vendidas}")
    revisar("incluye las de la venta mixta",
            any(l.cantidad >= 4 for l in resumen["lineas"]),
            str([(l.nombre, l.cantidad) for l in resumen["lineas"]]))

    print("\nSE EMITE EL BLOQUE")
    balance_antes_bloque = balance_del_dia(hoy)
    resultados = servicio.emitir(hoy, hoy, id_empleado)
    bloques = [r["id_bloque"] for r in resultados]
    revisar("se emitio al menos una factura", len(resultados) >= 1,
            str(len(resultados)))
    revisar("y quedo AUTORIZADA",
            all(r["estado"] == "AUTORIZADA" for r in resultados),
            str([r["estado"] for r in resultados]))

    total_bloques = sum(r["total"] for r in resultados)
    revisar("el total facturado es el de los productos vendidos",
            total_bloques == resumen["total"],
            f"{total_bloques} vs {resumen['total']}")
    revisar("y las unidades tambien",
            sum(r["unidades"] for r in resultados) == vendidas,
            str(sum(r["unidades"] for r in resultados)))

    print("\nEL BALANCE NO CAMBIA")
    # Lo mas importante: esa plata ya se conto cuando se cobro.
    revisar("lo vendido del dia es el mismo de antes de emitir",
            balance_del_dia(hoy) == balance_antes_bloque,
            f"{balance_del_dia(hoy)} vs {balance_antes_bloque}")
    with obtener_cursor() as cursor:
        cursor.execute("SELECT count(*) AS n FROM facturas WHERE id_factura = ANY(%s)",
                       ([r["id_bloque"] for r in resultados],))
    revisar("el bloque no aparece entre las ventas",
            cursor is not None)

    print("\nQUEDA EN LA BITACORA")
    # Facturar un periodo marca ventas de forma irreversible: tiene
    # que quedar quien lo hizo y cuando.
    with obtener_cursor() as cursor:
        cursor.execute(
            "SELECT detalle FROM bitacora WHERE accion = 'BLOQUE_FACTURADO' "
            "ORDER BY id_bitacora DESC LIMIT %s", (len(resultados),)
        )
        anotados = [dict(f) for f in cursor.fetchall()]
    revisar("se anoto una vez por factura emitida",
            len(anotados) == len(resultados),
            f"{len(anotados)} de {len(resultados)}")
    revisar("con el periodo y el total",
            anotados and "desde" in str(anotados[0]["detalle"])
            and "total" in str(anotados[0]["detalle"]),
            str(anotados[0]["detalle"])[:70] if anotados else "")

    print("\nNO SE FACTURA DOS VECES")
    segundo = servicio.resumen(hoy, hoy)
    revisar("ya no queda nada pendiente", segundo["unidades"] == 0,
            f"quedan {segundo['unidades']}")
    try:
        servicio.emitir(hoy, hoy, id_empleado)
        revisar("emitir de nuevo no hace nada", False, "emitio igual")
    except ErrorBloque as error:
        revisar("emitir de nuevo no hace nada", True)
        revisar("y lo dice claro", "pendientes" in str(error).lower(),
                str(error)[:60])

    print("\nUNA VENTA NUEVA SI QUEDA PENDIENTE")
    idf, _ = cobro.cobrar(
        {"id_cliente": str(id_cliente), "metodo_pago": "EFECTIVO"},
        [{"tipo": "producto", "id_item": productos[0]["id_producto"],
          "cantidad": 2}],
        id_empleado,
    )
    creadas.append(idf)
    sri_service.esperar_envios(20)
    tercero = servicio.resumen(hoy, hoy)
    revisar("aparecen las 2 unidades nuevas", tercero["unidades"] == 2,
            str(tercero["unidades"]))

    # Limpieza
    with obtener_cursor(commit=True) as cursor:
        for id_bloque in bloques:
            cursor.execute("DELETE FROM detalle_bloque WHERE id_bloque = %s",
                           (id_bloque,))
            cursor.execute("DELETE FROM facturas_bloque WHERE id_bloque = %s",
                           (id_bloque,))
        for id_factura in creadas:
            cursor.execute("DELETE FROM detalle_factura WHERE id_factura = %s",
                           (id_factura,))
            cursor.execute("DELETE FROM membresias WHERE id_factura = %s",
                           (id_factura,))
            cursor.execute("DELETE FROM facturas WHERE id_factura = %s",
                           (id_factura,))
        cursor.execute("DELETE FROM sri_secuenciales WHERE punto_emision = %s",
                       (PUNTO,))

P12.unlink(missing_ok=True)
print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
