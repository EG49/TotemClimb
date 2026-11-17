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

    # ─── Facturación electrónica (SRI) ────────────────────────────
    # Mientras falte cualquiera de los obligatorios, el sistema cobra
    # igual y no emite comprobante electrónico. Es el estado del
    # gimnasio hasta terminar de habilitarse, y no puede impedir
    # vender. Ver .env.example para el detalle de cada uno.
    #
    # SRI_AMBIENTE: "1" certificación (pruebas), "2" producción. Los
    # comprobantes de certificación NO tienen validez tributaria.
    SRI_AMBIENTE = os.getenv("SRI_AMBIENTE", "1")
    SRI_RUC = os.getenv("SRI_RUC")
    SRI_RAZON_SOCIAL = os.getenv("SRI_RAZON_SOCIAL")
    SRI_NOMBRE_COMERCIAL = os.getenv("SRI_NOMBRE_COMERCIAL")
    SRI_DIR_MATRIZ = os.getenv("SRI_DIR_MATRIZ")
    SRI_DIR_ESTABLECIMIENTO = os.getenv("SRI_DIR_ESTABLECIMIENTO")
    SRI_ESTABLECIMIENTO = os.getenv("SRI_ESTABLECIMIENTO", "001")
    SRI_PUNTO_EMISION = os.getenv("SRI_PUNTO_EMISION", "002")
    SRI_OBLIGADO_CONTABILIDAD = os.getenv("SRI_OBLIGADO_CONTABILIDAD", "NO")
    SRI_CONTRIBUYENTE_RIMPE = os.getenv("SRI_CONTRIBUYENTE_RIMPE", "NO")
    SRI_RUC_PROVEEDOR = os.getenv("SRI_RUC_PROVEEDOR")
    # El certificado NO va dentro del repositorio.
    SRI_P12_RUTA = os.getenv("SRI_P12_RUTA")
    SRI_P12_CLAVE = os.getenv("SRI_P12_CLAVE")

    # ─── Registro técnico (logging) ───────────────────────────────
    # Carpeta del archivo totem.log. Vacío = carpeta "logs" junto al
    # proyecto. El archivo rota al llegar al tamaño máximo.
    LOG_DIR = os.getenv("LOG_DIR")
    LOG_NIVEL = os.getenv("LOG_NIVEL", "INFO")
    LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", "2000000"))
    LOG_COPIAS = int(os.getenv("LOG_COPIAS", "5"))

    # Intentos fallidos de login permitidos antes de frenar al usuario
    MAX_INTENTOS_LOGIN = int(os.getenv("MAX_INTENTOS_LOGIN", "5"))
    BLOQUEO_LOGIN_SEGUNDOS = int(os.getenv("BLOQUEO_LOGIN_SEGUNDOS", "300"))
