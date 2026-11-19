"""Revisa si algun correo de los que mando el gimnasio no llego.

Cuando una direccion no existe, el servidor del destinatario devuelve
un aviso al buzon del gimnasio. Ese aviso llega minutos despues del
envio, cuando ya nadie esta mirando, y si nadie lo lee se pierde: la
factura queda como enviada y el cliente nunca la recibio.

Esto lee ese buzon y marca lo que corresponde: la factura queda
señalada en su pantalla y el cliente queda con un aviso en su ficha,
para que la proxima vez que venga alguien le pregunte el correo bueno.

Desde la carpeta totem:

    python -m scripts.revisar_rebotes

Conviene correrlo una vez al dia, junto con sri_reintentar.

Solo lee el buzon: no borra nada ni marca los correos como leidos, asi
que se puede correr aunque alguien este mirando ese buzon desde el
telefono.

Hace falta configurar IMAP_SERVIDOR, IMAP_USUARIO e IMAP_PASSWORD en
el .env. Sin eso avisa y no hace nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    from app import crear_app
    from app.services.rebote_service import ReboteService

    app = crear_app()
    with app.app_context():
        servicio = ReboteService()

        if not servicio.configurado():
            print("\nEl buzon de rebotes no esta configurado.")
            print("Hacen falta IMAP_SERVIDOR, IMAP_USUARIO e IMAP_PASSWORD")
            print("en el archivo .env. Mientras tanto, los correos que no")
            print("llegan no se detectan.\n")
            return

        print("\nLeyendo el buzon...")
        try:
            resumen = servicio.revisar()
        except Exception as error:  # noqa: BLE001
            print(f"\nNo se pudo leer el buzon: {error}")
            print("Revise IMAP_SERVIDOR, IMAP_USUARIO e IMAP_PASSWORD.\n")
            sys.exit(1)

        print(f"\n  Rebotes leidos:        {resumen['leidos']}")
        print(f"  Casados con un envio:  {resumen['casados']}")
        print(f"  Clientes señalados:    {resumen['clientes']}")
        print(f"  Sin envio conocido:    {resumen['sueltos']}")

        if resumen["sueltos"]:
            print("\n  Los 'sin envio conocido' son rebotes de correos que")
            print("  no salieron de este sistema, o de hace mas de una")
            print("  semana. No se marco nada por ellos.")

        marcados = ReboteService.clientes_con_correo_rebotado()
        if marcados:
            print(f"\n  CLIENTES A LOS QUE HAY QUE PREGUNTARLES EL CORREO ({len(marcados)}):")
            for cliente in marcados[:20]:
                fecha = cliente["correo_rebotado_en"].strftime("%d/%m/%Y")
                print(f"    {cliente['nombre']} {cliente['apellido']}"
                      f"  {cliente['correo']}  ({fecha})")
            if len(marcados) > 20:
                print(f"    ... y {len(marcados) - 20} mas")
            print("\n  La marca se quita sola cuando alguien le corrige el")
            print("  correo desde la ficha del cliente.")
        print()


if __name__ == "__main__":
    main()
