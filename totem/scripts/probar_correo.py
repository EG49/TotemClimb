"""Comprueba que el envío de correos está bien configurado.

El botón de la aplicación no sirve para diagnosticar: el envío sale en
segundo plano, así que la pantalla dice "Enviando..." aunque el correo
nunca llegue. Este script hace lo contrario: se conecta de frente,
espera, y dice exactamente qué falló.

Uso:
    python -m scripts.probar_correo                  # solo conecta y autentica
    python -m scripts.probar_correo --a tu@correo.com  # además manda una prueba
"""

import argparse
import smtplib
import ssl
import sys
from email.message import EmailMessage

from config import Config

TIEMPO_LIMITE = 20


def _diagnostico(error: Exception) -> str:
    """Traduce el error de SMTP a algo accionable.

    Los mensajes crudos de smtplib son crípticos y casi siempre apuntan
    a una de cuatro causas conocidas.
    """
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return (
            "El servidor rechazó el usuario o la contraseña.\n"
            "    Con Gmail, la causa casi siempre es una de estas:\n"
            "      · Estás usando la contraseña normal de la cuenta.\n"
            "        Tiene que ser una CONTRASEÑA DE APLICACIÓN de 16 letras.\n"
            "      · La cuenta no tiene activada la verificación en dos pasos,\n"
            "        y sin eso Google no permite generar esa contraseña.\n"
            "      · Copiaste la contraseña con espacios. Google la muestra\n"
            "        en cuatro bloques, pero va junta y sin espacios."
        )
    if isinstance(error, smtplib.SMTPNotSupportedError):
        return (
            "El servidor no admite autenticación por este puerto.\n"
            "    Revisa MAIL_PUERTO (587 con MAIL_TLS=True) y MAIL_TLS."
        )
    if isinstance(error, smtplib.SMTPServerDisconnected):
        return (
            "El servidor cortó la conexión sin explicar por qué.\n"
            "    Suele significar una de dos cosas:\n"
            "      · Rechazó las credenciales y cerró en vez de responder.\n"
            "      · La combinación de puerto y cifrado no es la que espera\n"
            "        (587 va con MAIL_TLS=True; 465 no sirve aquí)."
        )
    if isinstance(error, (TimeoutError, OSError)):
        return (
            "No se pudo llegar al servidor.\n"
            "    Revisa MAIL_SERVIDOR y MAIL_PUERTO, y si la red del gimnasio\n"
            "    o el antivirus están bloqueando la salida por ese puerto."
        )
    if isinstance(error, ssl.SSLError):
        return (
            "Falló el cifrado.\n"
            "    Con el puerto 587 debe ser MAIL_TLS=True; con el 465, el\n"
            "    servidor espera SSL directo, que este sistema no usa."
        )
    return "Error no previsto. El detalle de arriba es lo que devolvió el servidor."


def revisar_factura(numero: str) -> int:
    """Muestra qué ve el sistema en el cliente de una factura.

    Sirve cuando el comprobante dice "Sin correo registrado" pero el
    cliente parece tener correo: casi siempre la factura está a nombre
    de otra ficha, o el campo quedó vacío en vez de nulo.
    """
    from app.db import cerrar_pool, init_pool, obtener_cursor

    init_pool(Config.DATABASE_URL, Config.DB_POOL_MIN, Config.DB_POOL_MAX)
    try:
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT f.numero_factura, f.id_cliente,
                       c.nombre, c.apellido, c.correo,
                       c.id_representante,
                       r.nombre || ' ' || r.apellido AS representante
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
             LEFT JOIN clientes r ON r.id_cliente = c.id_representante
                 WHERE f.numero_factura = %s
                """,
                (numero,),
            )
            fila = cursor.fetchone()

        if fila is None:
            print(f"No existe ninguna factura con el número {numero}.")
            return 1

        print(f"Factura {fila['numero_factura']}")
        print(f"  Está a nombre de: {fila['nombre']} {fila['apellido']}"
              f"  (id_cliente {fila['id_cliente']})")
        if fila["id_representante"]:
            print(f"  Es un menor, representado por {fila['representante']}.")

        correo = fila["correo"]
        if correo is None:
            print("  Correo: no tiene (NULL)")
            print()
            print("El botón no aparece porque ESTA ficha no tiene correo.")
            print("Si vos registraste el correo en otra ficha (por ejemplo la")
            print("del representante, o un cliente con nombre parecido), la")
            print("factura sigue apuntando a esta. Edita este cliente y")
            print("guárdale el correo.")
            return 1
        if not correo.strip():
            print(f"  Correo: vacío (guardado como {correo!r})")
            print()
            print("El campo existe pero está en blanco, así que el sistema lo")
            print("trata como si no hubiera. Vuelve a editarlo y guárdalo.")
            return 1

        print(f"  Correo: {correo}")
        print()
        print("Esta ficha sí tiene correo, así que el botón debería salir.")
        print("Si no sale, es que la aplicación no se reinició después de")
        print("tocar el .env.")
        return 0
    finally:
        cerrar_pool()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba la configuración de correo.")
    parser.add_argument(
        "--a", dest="destino", metavar="CORREO",
        help="Manda además un correo de prueba a esta dirección.",
    )
    parser.add_argument(
        "--factura", metavar="NUMERO",
        help="En vez de probar el servidor, muestra qué correo tiene "
             "registrado el cliente de esa factura (ej. F-000015).",
    )
    args = parser.parse_args()

    if args.factura:
        return revisar_factura(args.factura)

    servidor = Config.MAIL_SERVIDOR
    puerto = Config.MAIL_PUERTO
    usuario = Config.MAIL_USUARIO
    password = Config.MAIL_PASSWORD
    remitente = Config.MAIL_REMITENTE or usuario

    print("Configuración leída del .env")
    print(f"  Servidor:  {servidor}:{puerto}  (TLS: {Config.MAIL_TLS})")
    print(f"  Usuario:   {usuario}")
    print(f"  Remitente: {remitente}")
    # La contraseña no se imprime nunca; solo si está y cuánto mide, que
    # es lo único que hace falta para detectar el error más común.
    if password:
        print(f"  Contraseña: {len(password)} caracteres", end="")
        if " " in password:
            print("  ← OJO: tiene espacios. Google la muestra en bloques,")
            print("              pero se copia junta, sin espacios.")
        else:
            print()
    print()

    faltan = [n for n, v in [
        ("MAIL_SERVIDOR", servidor), ("MAIL_PUERTO", puerto),
        ("MAIL_USUARIO", usuario), ("MAIL_PASSWORD", password),
    ] if not v]
    if faltan:
        print("FALTA CONFIGURAR: " + ", ".join(faltan))
        print()
        print("Por eso el botón 'Enviar por correo' no aparece en el")
        print("comprobante: el sistema lo esconde hasta que las CUATRO")
        print("variables estén puestas, no solo el usuario y la contraseña.")
        print("Agrégalas al .env y reinicia la aplicación.")
        return 1

    try:
        print(f"Conectando a {servidor}:{puerto} ...")
        with smtplib.SMTP(servidor, puerto, timeout=TIEMPO_LIMITE) as smtp:
            print("  Conexión establecida.")
            if Config.MAIL_TLS:
                smtp.starttls()
                print("  Cifrado TLS activo.")
            smtp.login(usuario, password)
            print("  Autenticación correcta.")

            if args.destino:
                mensaje = EmailMessage()
                mensaje["Subject"] = "Prueba de configuración — Totem Climb Gym"
                mensaje["From"] = remitente
                mensaje["To"] = args.destino
                mensaje.set_content(
                    "Si estás leyendo esto, el envío de comprobantes ya funciona.\n"
                    "Este mensaje lo generó scripts/probar_correo.py."
                )
                smtp.send_message(mensaje)
                print(f"  Correo de prueba enviado a {args.destino}.")
    except Exception as error:  # noqa: BLE001
        print()
        print("FALLÓ.")
        print(f"  {type(error).__name__}: {error}")
        print()
        print("  " + _diagnostico(error))
        return 1

    print()
    if args.destino:
        print("TODO BIEN. Revisa la bandeja de " + args.destino + ".")
        print("Si no aparece, mira también en spam: es normal la primera vez")
        print("que una cuenta manda correos automáticos.")
    else:
        print("TODO BIEN. El servidor acepta la conexión y las credenciales.")
        print("Para comprobar que además llega, repite con:")
        print("    python -m scripts.probar_correo --a tu@correo.com")
    print()
    print("El botón 'Enviar por correo' aparecerá en el comprobante, siempre")
    print("que la aplicación se haya reiniciado después de tocar el .env y")
    print("que el cliente de esa factura tenga un correo registrado. Si no")
    print("lo tiene, en su lugar dice 'Sin correo registrado'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
