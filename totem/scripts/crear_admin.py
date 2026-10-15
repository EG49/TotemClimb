"""Establece la contraseña del usuario administrador.

El script SQL deja el admin con un hash marcador que no permite entrar.
Este script lo reemplaza por un hash bcrypt real, o crea el usuario si no
existe todavía.

Uso:
    python -m scripts.crear_admin
    python -m scripts.crear_admin --usuario camila --rol VENDEDOR
"""

import argparse
import getpass
import sys

from app.db import cerrar_pool, init_pool, obtener_cursor
from app.services.auth_service import generar_hash
from config import Config


def pedir_password() -> str:
    while True:
        password = getpass.getpass("Contraseña nueva: ")
        if len(password) < 8:
            print("  Debe tener al menos 8 caracteres.")
            continue
        if password != getpass.getpass("Repite la contraseña: "):
            print("  No coinciden, intenta de nuevo.")
            continue
        return password


def main() -> int:
    parser = argparse.ArgumentParser(description="Define la contraseña de un empleado.")
    parser.add_argument("--usuario", default="admin")
    parser.add_argument("--rol", default="ADMIN", choices=["ADMIN", "VENDEDOR"])
    parser.add_argument("--nombre", default="Administrador")
    parser.add_argument("--apellido", default="Totem")
    args = parser.parse_args()

    init_pool(Config.DATABASE_URL)
    try:
        password_hash = generar_hash(pedir_password())

        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "SELECT id_empleado FROM empleados WHERE usuario = %s",
                (args.usuario,),
            )
            existente = cursor.fetchone()

            if existente:
                cursor.execute(
                    """
                    UPDATE empleados
                       SET password_hash = %s, activo = TRUE
                     WHERE usuario = %s
                    """,
                    (password_hash, args.usuario),
                )
                print(f"Contraseña actualizada para '{args.usuario}'.")
            else:
                cursor.execute(
                    """
                    INSERT INTO empleados (nombre, apellido, usuario, password_hash, rol)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (args.nombre, args.apellido, args.usuario, password_hash, args.rol),
                )
                print(f"Empleado '{args.usuario}' creado con rol {args.rol}.")
        return 0
    finally:
        cerrar_pool()


if __name__ == "__main__":
    sys.exit(main())
