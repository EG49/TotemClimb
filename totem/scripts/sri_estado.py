"""Dice por que el sistema emite o no emite comprobantes electronicos.

Cuando se cobra y "no pasa nada" con el SRI, casi siempre es que
falta un dato y el sistema esta haciendo lo que se le pidio: cobrar
igual y no emitir. Este script dice cual falta, en lugar de dejarlo
adivinando.

Revisa, en este orden:

  1. La configuracion: que esten los datos del emisor y el certificado
  2. El certificado: que se pueda abrir con la clave y que no este
     vencido
  3. La base: que exista la numeracion del punto de emision
  4. Las ultimas facturas y en que estado quedaron ante el SRI

No emite nada ni cambia nada. Se puede correr las veces que haga
falta.

Desde la carpeta totem:

    python -m scripts.sri_estado
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OBLIGATORIOS = (
    ("SRI_RUC", "el RUC del gimnasio, 13 digitos"),
    ("SRI_RAZON_SOCIAL", "la razon social como consta en el RUC"),
    ("SRI_DIR_MATRIZ", "la direccion de la matriz"),
    ("SRI_ESTABLECIMIENTO", "el establecimiento, 3 digitos"),
    ("SRI_PUNTO_EMISION", "el punto de emision, 3 digitos"),
    ("SRI_P12_RUTA", "la ruta del certificado .p12"),
    ("SRI_P12_CLAVE", "la clave del certificado"),
)

OPCIONALES = (
    ("SRI_AMBIENTE", "1 pruebas, 2 produccion (por omision 1)"),
    ("SRI_NOMBRE_COMERCIAL", "el nombre comercial"),
    ("SRI_DIR_ESTABLECIMIENTO", "si falta, se usa la de la matriz"),
    ("SRI_OBLIGADO_CONTABILIDAD", "SI o NO (por omision NO)"),
    ("SRI_CONTRIBUYENTE_RIMPE", "SI o NO (por omision NO)"),
    ("SRI_RUC_PROVEEDOR", "RUC de quien desarrolla el sistema"),
)

# Lo que no se muestra nunca, ni siquiera a medias.
SECRETOS = {"SRI_P12_CLAVE"}


def main() -> None:
    from app import crear_app
    from app.services.sri_service import ServicioSri

    app = crear_app()
    with app.app_context():
        servicio = ServicioSri()

        print("\n" + "=" * 58)
        print("  1. CONFIGURACION  (sale del archivo .env)")
        print("=" * 58)

        faltan = []
        for nombre, para_que in OBLIGATORIOS:
            valor = (app.config.get(nombre) or "").strip()
            if not valor:
                faltan.append(nombre)
                print(f"  FALTA  {nombre:26} {para_que}")
            elif nombre in SECRETOS:
                print(f"  ok     {nombre:26} (definida)")
            else:
                print(f"  ok     {nombre:26} {valor}")

        print()
        for nombre, para_que in OPCIONALES:
            valor = (app.config.get(nombre) or "").strip()
            estado = valor if valor else f"(sin definir: {para_que})"
            print(f"         {nombre:26} {estado}")

        if faltan:
            print(
                f"\n  >> El sistema NO emite comprobantes electronicos.\n"
                f"     Faltan {len(faltan)} datos en el .env: "
                + ", ".join(faltan)
                + "\n     Mientras tanto cobra normalmente, sin factura "
                "electronica.\n"
                "     Compare su .env contra .env.example."
            )
            return

        ambiente = servicio.ambiente()
        print(
            f"\n  >> Configurado. Ambiente: "
            f"{'PRUEBAS (sin validez tributaria)' if ambiente == '1' else 'PRODUCCION'}"
        )

        print("\n" + "=" * 58)
        print("  2. CERTIFICADO")
        print("=" * 58)

        ruta = Path(app.config["SRI_P12_RUTA"])
        if not ruta.exists():
            print(f"  FALTA  no existe el archivo:\n         {ruta}")
            print("\n  >> Sin el certificado no se puede firmar.")
            return
        print(f"  ok     esta en {ruta}")

        try:
            from cryptography.hazmat.primitives.serialization import pkcs12

            privada, certificado, _ = pkcs12.load_key_and_certificates(
                ruta.read_bytes(),
                (app.config["SRI_P12_CLAVE"] or "").encode("utf-8"),
            )
        except Exception as error:  # noqa: BLE001
            print(f"  FALLA  no se pudo abrir: {type(error).__name__}")
            print("         Lo mas probable es que SRI_P12_CLAVE este mal.")
            return

        if privada is None or certificado is None:
            print("  FALLA  el archivo no trae la clave privada y el "
                  "certificado juntos")
            return

        from datetime import datetime, timezone

        vence = certificado.not_valid_after_utc
        dias = (vence - datetime.now(timezone.utc)).days
        titular = next(
            (a.value for a in certificado.subject
             if a.oid.dotted_string == "2.5.4.3"), "(sin nombre)"
        )
        print(f"  ok     se abre con la clave configurada")
        print(f"  ok     titular: {titular}")
        if dias < 0:
            print(f"  FALLA  VENCIO hace {-dias} dias ({vence:%d/%m/%Y})")
            print("\n  >> Un certificado vencido no sirve para firmar.")
            return
        if dias < 30:
            print(f"  AVISO  vence en {dias} dias ({vence:%d/%m/%Y})")
        else:
            print(f"  ok     vence el {vence:%d/%m/%Y} (en {dias} dias)")

        print("\n" + "=" * 58)
        print("  3. NUMERACION EN LA BASE")
        print("=" * 58)

        establecimiento = app.config["SRI_ESTABLECIMIENTO"]
        punto = app.config["SRI_PUNTO_EMISION"]
        try:
            ultimo = servicio.repo.ultimo_secuencial(establecimiento, punto)
        except Exception as error:  # noqa: BLE001
            print(f"  FALLA  no se pudo consultar: {error}")
            print("\n  >> Corra Sql/alter-sri-secuenciales.sql")
            return

        if ultimo is None:
            print(f"  FALTA  no hay numeracion para {establecimiento}-{punto}")
            print("\n  >> Corra Sql/alter-sri-secuenciales.sql, o agregue la")
            print("     fila si su punto de emision es otro. Sin esto, cada")
            print("     cobro intenta reservar numero y no puede.")
            return
        print(f"  ok     punto {establecimiento}-{punto}, ultimo emitido: {ultimo}")
        print(f"         el proximo comprobante sera el {ultimo + 1}")

        print("\n" + "=" * 58)
        print("  4. ULTIMAS FACTURAS")
        print("=" * 58)

        from app.db import obtener_cursor

        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT numero_factura, fecha, total, sri_estado,
                       sri_secuencial, sri_intentos, sri_mensaje
                  FROM facturas
                 ORDER BY id_factura DESC
                 LIMIT 10
                """
            )
            filas = cursor.fetchall()

        if not filas:
            print("  (todavia no hay facturas)")
        for fila in filas:
            estado = fila["sri_estado"] or "— sin comprobante —"
            numero = (
                f"{fila['sri_secuencial']:09d}" if fila["sri_secuencial"]
                else "—"
            )
            print(f"  {fila['numero_factura']:11} {fila['fecha']:%d/%m %H:%M}"
                  f"  ${fila['total']:>8}  {numero}  {estado}")
            if fila["sri_mensaje"]:
                primera = fila["sri_mensaje"].strip().splitlines()[0]
                print(f"              {primera[:70]}")

        sin_comprobante = [f for f in filas if f["sri_estado"] is None]
        if sin_comprobante:
            print(
                f"\n  AVISO  {len(sin_comprobante)} de las ultimas "
                f"{len(filas)} no tienen comprobante electronico.\n"
                "         Si son anteriores a configurar el SRI, es normal.\n"
                "         Si son de ahora, mire el registro en logs/totem.log."
            )

        pendientes = servicio.repo.pendientes()
        if pendientes:
            print(f"\n  {len(pendientes)} esperando resolverse ante el SRI.")
            print("  Para retomarlas:  python -m scripts.sri_reintentar")

        print()


if __name__ == "__main__":
    main()
