"""Configuración de la aplicación, leída desde variables de entorno."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Clave para firmar las cookies de sesión. En producción SIEMPRE
    # debe venir del entorno; el valor por defecto es solo para
    # desarrollo local.
    SECRET_KEY = os.getenv("SECRET_KEY", "clave-solo-para-desarrollo")

    # Conexión a PostgreSQL
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres@localhost:5432/totem",
    )

    # Tamaño del pool de conexiones
    DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
    DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "5"))

    # La sesión expira tras este tiempo de inactividad
    PERMANENT_SESSION_LIFETIME = int(os.getenv("SESSION_LIFETIME", "28800"))  # 8 h

    # Cookies de sesión
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Ponlo en True cuando la app corra detrás de HTTPS
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False") == "True"

    # Correo saliente. Si falta cualquiera de los cuatro primeros, el
    # sistema simplemente no ofrece el envío: no se rompe nada.
    #   Gmail:  smtp.gmail.com / 587 / tu-cuenta@gmail.com / contraseña
    #           de aplicación (NO la del correo; ver el README).
    #   Brevo:  smtp-relay.brevo.com / 587 / el login que te dan.
    MAIL_SERVIDOR = os.getenv("MAIL_SERVIDOR")
    MAIL_PUERTO = int(os.getenv("MAIL_PUERTO", "587"))
    MAIL_USUARIO = os.getenv("MAIL_USUARIO")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_TLS = os.getenv("MAIL_TLS", "True") == "True"
    # Dirección que ve el cliente. Con Gmail tiene que ser la misma
    # cuenta del usuario: Gmail no deja enviar a nombre de otra.
    MAIL_REMITENTE = os.getenv("MAIL_REMITENTE")
    MAIL_NOMBRE_REMITENTE = os.getenv("MAIL_NOMBRE_REMITENTE", "Totem Climb Gym")

    # Intentos fallidos de login permitidos antes de frenar al usuario
    MAX_INTENTOS_LOGIN = int(os.getenv("MAX_INTENTOS_LOGIN", "5"))
    BLOQUEO_LOGIN_SEGUNDOS = int(os.getenv("BLOQUEO_LOGIN_SEGUNDOS", "300"))
