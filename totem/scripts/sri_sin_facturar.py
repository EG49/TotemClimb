"""Lo vendido que NO se facturo al SRI, para la factura en bloque.

Al SRI van solo las membresias y los pases. Los productos —aguas,
bebidas, magnesio— el gimnasio los factura aparte y en bloque, a
mano. Este script dice cuanto fue, para poder armarla.

Muestra dos cosas:

  1. El resumen por producto en el periodo: cuantos se vendieron y
     por cuanto, con la base imponible y el IVA ya separados, que es
     lo que hay que poner en la factura.
  2. Las ventas que no generaron ningun comprobante electronico,
     porque fueron solo de productos.

No cambia nada. Se puede correr las veces que haga falta.

Desde la carpeta totem:

    python -m scripts.sri_sin_facturar              (lo que va del mes)
    python -m scripts.sri_sin_facturar 2026-11-01 2026-11-15
"""

import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CENTAVO = Decimal("0.01")


def periodo():
    """Las fechas pedidas, o lo que va del mes."""
    if len(sys.argv) == 3:
        try:
            return (date.fromisoformat(sys.argv[1]),
                    date.fromisoformat(sys.argv[2]))
        except ValueError:
            print("\nLas fechas van como 2026-11-01 2026-11-15")
            sys.exit(1)
    if len(sys.argv) != 1:
        print(__doc__)
        sys.exit(1)
    hoy = date.today()
    return hoy.replace(day=1), hoy


def main() -> None:
    desde, hasta = periodo()

    from app import crear_app
    from app.db import obtener_cursor
    from app.services.configuracion_service import ConfiguracionService

    app = crear_app()
    with app.app_context():
        iva = ConfiguracionService().iva_vigente()

        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT p.nombre,
                       SUM(d.cantidad)  AS unidades,
                       SUM(d.subtotal)  AS total
                  FROM detalle_factura d
                  JOIN productos p ON p.id_producto = d.id_producto
                  JOIN facturas f  ON f.id_factura  = d.id_factura
                 WHERE d.id_producto IS NOT NULL
                   AND f.estado <> 'ANULADA'
                   AND f.fecha::date BETWEEN %s AND %s
                 GROUP BY p.nombre
                 ORDER BY SUM(d.subtotal) DESC
                """,
                (desde, hasta),
            )
            productos = cursor.fetchall()

            cursor.execute(
                """
                SELECT f.numero_factura, f.fecha, f.total
                  FROM facturas f
                 WHERE f.estado <> 'ANULADA'
                   AND f.sri_estado IS NULL
                   AND f.fecha::date BETWEEN %s AND %s
                   AND NOT EXISTS (
                         SELECT 1 FROM detalle_factura d
                          WHERE d.id_factura = f.id_factura
                            AND d.id_plan IS NOT NULL
                       )
                 ORDER BY f.fecha
                """,
                (desde, hasta),
            )
            ventas = cursor.fetchall()

        print(f"\nDel {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}")
        print("=" * 62)
        print("  PRODUCTOS VENDIDOS, NO FACTURADOS AL SRI")
        print("=" * 62)

        if not productos:
            print("  (no se vendio ningun producto en el periodo)")
        else:
            print(f"  {'Producto':26} {'Unid.':>6} {'Base':>10} "
                  f"{'IVA':>8} {'Total':>10}")
            print("  " + "-" * 60)
            total_general = Decimal("0")
            base_general = Decimal("0")
            for fila in productos:
                total = Decimal(fila["total"])
                # Los precios incluyen IVA: la base sale dividiendo y
                # el IVA por resta, igual que en el resto del sistema.
                base = (total / (1 + iva / 100)).quantize(
                    CENTAVO, rounding=ROUND_HALF_UP
                )
                print(f"  {fila['nombre'][:26]:26} {fila['unidades']:>6} "
                      f"{base:>10} {total - base:>8} {total:>10}")
                total_general += total
                base_general += base

            print("  " + "-" * 60)
            iva_general = total_general - base_general
            print(f"  {'TOTAL':26} {'':>6} {base_general:>10} "
                  f"{iva_general:>8} {total_general:>10}")
            print(f"\n  Para la factura en bloque: base {base_general}, "
                  f"IVA {iva} % = {iva_general}, total {total_general}")

        print("\n" + "=" * 62)
        print("  VENTAS SIN NINGUN COMPROBANTE ELECTRONICO")
        print("=" * 62)
        print("  (fueron solo de productos, asi que no se emitio nada)")
        print()

        if not ventas:
            print("  (ninguna)")
        else:
            for fila in ventas:
                print(f"  {fila['numero_factura']:11} "
                      f"{fila['fecha']:%d/%m/%Y %H:%M}  ${fila['total']:>9}")
            print(f"\n  {len(ventas)} ventas, "
                  f"${sum(Decimal(f['total']) for f in ventas)}")

        print(
            "\n  Nota: una venta mixta (membresia + productos) SI tiene\n"
            "  comprobante, pero solo por la parte de la membresia. Los\n"
            "  productos de esas ventas estan contados arriba igual.\n"
        )


if __name__ == "__main__":
    main()
