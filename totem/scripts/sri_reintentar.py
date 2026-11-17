"""Retoma los comprobantes que quedaron sin resolver ante el SRI.

Una factura queda pendiente cuando el envio no salio en el momento
del cobro: se cayo el internet, el SRI no contesto, o contesto que
todavia estaba procesando. La venta ya quedo registrada; lo que falta
es el comprobante.

Esto es lo que hay que correr todos los dias. Mientras no se corra,
esas facturas se quedan esperando.

Desde la carpeta totem:

    python -m scripts.sri_reintentar

No toca las que ya estan AUTORIZADAS, ni las DEVUELTAS o
NO_AUTORIZADAS: esas dos ultimas necesitan que alguien lea el mensaje
del SRI y corrija algo, y reintentarlas sin cambiar nada daria el
mismo error.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    from app import crear_app
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

        pendientes = servicio.repo.pendientes()
        if not pendientes:
            print("\nNo hay nada pendiente. Todas las facturas estan al dia.")
            return

        print(f"\n{len(pendientes)} comprobantes sin resolver:\n")
        for factura in pendientes:
            print(f"  {factura['numero_factura']:11} "
                  f"{factura['fecha']:%d/%m/%Y %H:%M}  "
                  f"{factura['sri_estado']:10} "
                  f"intentos: {factura['sri_intentos']}")

        print("\nReintentando...\n")
        resumen = servicio.reintentar_pendientes(limite=len(pendientes))

        print(f"  revisadas:    {resumen['revisadas']}")
        print(f"  autorizadas:  {resumen['autorizadas']}")
        print(f"  sin resolver: {resumen['sin_resolver']}")

        if resumen["sin_resolver"]:
            print(
                "\nLas que siguen sin resolver pueden ser falta de conexion,\n"
                "o algo que el SRI rechaza. Corra  python -m scripts.sri_estado\n"
                "para ver el mensaje de cada una."
            )
        print()


if __name__ == "__main__":
    main()
