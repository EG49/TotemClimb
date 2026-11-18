"""Emite el comprobante electronico de una factura ya cobrada.

Para que sirve
--------------
El comprobante se reserva en el momento del cobro. Una factura
cobrada cuando el sistema todavia no estaba configurado para emitir
queda sin comprobante para siempre, porque ese momento ya paso.

Este script le da numero y clave de acceso, y la envia. Sirve para
probar sin tener que cobrar de nuevo, y para ponerse al dia con las
ventas que quedaron sin factura mientras se terminaba de configurar.

    python -m scripts.sri_emitir_factura F-000018

OJO CON LA FECHA
----------------
La clave de acceso lleva la fecha de EMISION, y este script usa la
fecha original de la factura, no la de hoy. Si la factura es de hace
varios dias, el SRI puede rechazarla por fuera de plazo. En el
ambiente de pruebas no importa; en produccion, consultelo con el
contador antes de ponerse al dia con facturas viejas.

No toca las facturas que ya tienen comprobante: para esas use
scripts/sri_reintentar.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    numero = sys.argv[1].strip()

    from app import crear_app
    from app.db import obtener_cursor
    from app.services.sri_service import ServicioSri

    app = crear_app()
    with app.app_context():
        servicio = ServicioSri()

        if not servicio.configurado():
            print(
                "\nEl sistema no esta configurado para emitir.\n"
                "Corra  python -m scripts.sri_estado  para ver que falta."
            )
            sys.exit(1)

        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT id_factura, numero_factura, fecha, total,
                       estado, sri_estado, sri_clave_acceso
                  FROM facturas
                 WHERE numero_factura = %s
                """,
                (numero,),
            )
            factura = cursor.fetchone()

        if factura is None:
            print(f"\nNo encuentro la factura {numero}.")
            sys.exit(1)

        print(f"\n{factura['numero_factura']}  "
              f"{factura['fecha']:%d/%m/%Y %H:%M}  ${factura['total']}")

        if factura["estado"] == "ANULADA":
            print("\nEsta factura esta ANULADA. No se emite.")
            sys.exit(1)

        if factura["sri_clave_acceso"]:
            print(
                f"\nEsta factura YA tiene comprobante "
                f"({factura['sri_estado']}).\n"
                "Para reintentar el envio use:  python -m scripts.sri_reintentar"
            )
            sys.exit(1)

        from datetime import date

        dias = (date.today() - factura["fecha"].date()).days
        if dias > 0:
            print(
                f"\nAVISO: la factura es de hace {dias} dia(s). La clave de\n"
                "acceso llevara su fecha original. En produccion el SRI puede\n"
                "rechazar comprobantes emitidos fuera de plazo."
            )
            if servicio.ambiente() == "2":
                respuesta = input("\nAmbiente de PRODUCCION. Continuar? (si/no): ")
                if respuesta.strip().lower() not in ("si", "s", "sí"):
                    print("Cancelado.")
                    return

        print("\nReservando numero...")
        with obtener_cursor(commit=True) as cursor:
            clave = servicio.reservar(cursor, factura["id_factura"])
        if clave is None:
            print("No se pudo reservar. Corra  python -m scripts.sri_estado")
            sys.exit(1)
        print(f"  clave de acceso: {clave}")

        print("\nFirmando y enviando al SRI...")
        try:
            estado = servicio.emitir(factura["id_factura"])
        except Exception as error:  # noqa: BLE001
            print(f"\nNo salio: {type(error).__name__}: {error}")
            print(
                "\nLa factura quedo con su numero reservado. Cuando se "
                "resuelva\nel problema, use:  python -m scripts.sri_reintentar"
            )
            sys.exit(1)

        print(f"\nEstado: {estado}")

        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT sri_autorizacion, sri_mensaje FROM facturas "
                "WHERE id_factura = %s",
                (factura["id_factura"],),
            )
            final = cursor.fetchone()

        if estado == "AUTORIZADA":
            print(f"Autorizacion: {final['sri_autorizacion']}")
            print(
                "\nListo. Desde la pantalla de la factura, el boton de correo\n"
                "ahora manda el RIDE en PDF y el XML autorizado."
            )
        elif final["sri_mensaje"]:
            print(f"\nEl SRI dice:\n{final['sri_mensaje']}")


if __name__ == "__main__":
    main()
