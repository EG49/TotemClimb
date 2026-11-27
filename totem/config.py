"""Configuración de la aplicación, leída desde variables de entorno."""

import os
from dotenv import load_dotenv

load_dotenv()


# Claves que alguna vez estuvieron escritas acá o en .env.example, y
# cualquiera que las haya visto puede usarlas. Si el sistema arranca
# con una de éstas, quien conozca el repositorio puede fabricarse una
# cookie que diga "empleado 1, rol ADMIN", firmarla correctamente, y
# entrar como administrador sin contraseña.
CLAVES_QUEMADAS = {
    "clave-solo-para-desarrollo",
    "cambia-esto-por-una-clave-larga-y-aleatoria",
    "clave-secreta",
    "secret",
    "changeme",
}

# Una clave de 32 caracteres al azar es imposible de adivinar; una
# corta, o escrita por una persona, no lo es. token_hex(32) da 64.
LARGO_MINIMO = 32


def revisar_secret_key(valor):
    """Devuelve qué tiene de malo la SECRET_KEY, o None si está bien.

    Aparte para poder probarla sin levantar la aplicación; la llama
    crear_app() al arrancar.
    """
    if not valor or not valor.strip():
        return "no está definida"
    valor = valor.strip()
    if valor.lower() in CLAVES_QUEMADAS:
        return ("es una clave de ejemplo, que está escrita en el "
                "repositorio y cualquiera que lo haya visto conoce")
    if len(valor) < LARGO_MINIMO:
        return (f"tiene {len(valor)} caracteres y necesita al menos "
                f"{LARGO_MINIMO}")
    return None


EXPLICACION_SECRET_KEY = """
La SECRET_KEY firma las cookies de sesión. Quien la conoce puede
fabricar una cookie que diga "empleado 1, rol ADMIN" y entrar sin
contraseña, así que el sistema no arranca sin una propia.

Genere una, en ESTA máquina:

    python -c "import secrets; print(secrets.token_hex(32))"

y póngala en el archivo .env, junto a DATABASE_URL:

    SECRET_KEY=el-valor-que-salio

Una por cada lugar donde corre el sistema: una acá y otra distinta en
la computadora del gimnasio, generada allá. No la escriba a mano, no
la copie de otro lado y no la suba al repositorio.

Si alguna vez la cambia, todos tienen que volver a iniciar sesión.
No se pierde ningún dato.
"""


class Config:
    # Firma las cookies de sesión. Sin valor por defecto a propósito:
    # un defecto que funciona es un defecto que termina en producción
    # sin que nadie lo note. Ver revisar_secret_key().
    SECRET_KEY = os.getenv("SECRET_KEY")

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

    # ─── Quién emite los comprobantes electrónicos ────────────────
    #   "sri"     este sistema firma y manda al SRI, como veníamos
    #   "externa" los emite otro sistema (hoy Contífico, a partir del
    #             Excel diario). Este sistema NO manda nada al SRI:
    #             cobra, guarda la venta y entrega el comprobante
    #             interno; la factura con validez la emite el otro.
    #
    # Hay un solo emisor a la vez, y eso no es un detalle: si los dos
    # emiten, el gimnasio termina con dos comprobantes autorizados
    # por la misma venta, que es un problema tributario y no un error
    # de pantalla.
    #
    # El código del SRI queda en su lugar, solo apagado: si algún día
    # se vuelve a emisión directa, es cambiar esta línea.
    FACTURACION_ELECTRONICA = os.getenv("FACTURACION_ELECTRONICA", "sri")

    # ─── Rebotes ──────────────────────────────────────────────────
    # Que el correo salga no quiere decir que haya llegado. Cuando la
    # dirección no existe, el aviso vuelve al buzón del remitente
    # minutos después. Esto es para leer ese buzón y enterarse.
    # Con Gmail: imap.gmail.com / 993 / la misma cuenta y la misma
    # contraseña de aplicación del envío.
    # Si queda vacío, los correos que no llegan no se detectan: todo
    # lo demás sigue funcionando igual.
    IMAP_SERVIDOR = os.getenv("IMAP_SERVIDOR")
    IMAP_PUERTO = int(os.getenv("IMAP_PUERTO", "993"))
    IMAP_USUARIO = os.getenv("IMAP_USUARIO")
    IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")
    IMAP_CARPETA = os.getenv("IMAP_CARPETA", "INBOX")

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
