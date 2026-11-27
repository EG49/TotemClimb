"""Respaldo de la base de datos, con verificación de que sirve.

Un archivo que nadie probó restaurar no es un respaldo: es un archivo.
Por eso este script, además de generar el volcado, lo restaura en una
base aparte y compara los conteos contra la base real. Si no coinciden,
el respaldo se marca como fallido aunque pg_dump haya terminado bien.

Lo que guarda este volcado son datos de personas: nombres, cédulas,
correos y los datos de los menores. Un volcado filtrado no se arregla
después como se cambia una contraseña, así que:

  - La carpeta de respaldos va FUERA del repositorio. El script se
    niega a escribir dentro de él.
  - Los archivos nunca se suben a ningún lado ni se mandan por correo.
  - Si se copia a un disco externo o a la nube, que sea uno que solo
    maneje el gimnasio.

Uso:

    python -m scripts.respaldo                 # respalda y verifica
    python -m scripts.respaldo --sin-verificar # solo el volcado
    python -m scripts.respaldo --estado        # cuándo fue el último

En Windows, programarlo en el Programador de tareas una vez al día.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app                     # noqa: E402
from app.db import obtener_cursor             # noqa: E402
from app.repositories.factura_repo import (   # noqa: E402
    ConfiguracionRepositorio,
)

# Tablas que un respaldo tiene que traer sí o sí. Si falta una, el
# volcado salió mal por más que pg_dump haya devuelto 0.
TABLAS_ESPERADAS = [
    "empleados", "clientes", "productos", "planes_membresia",
    "configuracion", "facturas", "detalle_factura", "membresias",
    "categorias_evento", "eventos", "evento_inscritos", "pagos_fiado",
    "bitacora",
]

# Cuántos respaldos diarios se conservan. El primero de cada mes no se
# borra nunca: si un dato se dañó hace meses y nadie lo notó, los
# diarios recientes ya tienen el daño adentro.
DIARIOS_A_CONSERVAR = 30

CLAVE_ULTIMO_RESPALDO = "ultimo_respaldo"

# Base temporal donde se prueba la restauración.
BASE_DE_PRUEBA = "totem_verificacion_respaldo"


def _carpeta_de_respaldos() -> Path:
    """Dónde se guardan. Fuera del repositorio, siempre."""
    crudo = os.getenv("RESPALDOS_DIR")
    if crudo:
        carpeta = Path(crudo).expanduser().resolve()
    else:
        # Por defecto, al lado del proyecto y no adentro.
        carpeta = (Path(__file__).resolve().parent.parent.parent
                   / "respaldos-totem").resolve()

    repo = Path(__file__).resolve().parent.parent.parent
    if carpeta == repo or repo in carpeta.parents:
        raise SystemExit(
            f"La carpeta de respaldos ({carpeta}) está dentro del "
            f"repositorio ({repo}).\n"
            "Un volcado tiene cédulas y datos de menores; ahí termina "
            "subido a GitHub sin que nadie lo note.\n"
            "Ponga otra ruta en RESPALDOS_DIR, idealmente en otro disco."
        )
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def _datos_de_conexion() -> dict:
    """Parte el DATABASE_URL en lo que necesitan pg_dump y pg_restore."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("Falta DATABASE_URL en el .env.")
    partes = urlparse(url)
    if not partes.path or partes.path == "/":
        raise SystemExit(f"El DATABASE_URL no dice qué base usar: {url}")
    return {
        "host": partes.hostname or "localhost",
        "puerto": str(partes.port or 5432),
        "usuario": unquote(partes.username or ""),
        "clave": unquote(partes.password or ""),
        "base": partes.path.lstrip("/"),
    }


def _buscar_herramienta(nombre: str) -> str:
    """Encuentra pg_dump y compañía, también en Windows.

    En Windows el instalador de PostgreSQL no agrega su carpeta al PATH,
    así que el nombre pelado no funciona desde el Programador de tareas
    aunque funcione en la consola del que lo instaló.
    """
    directo = os.getenv("PG_BIN")
    if directo:
        ruta = Path(directo) / nombre
        for candidata in (ruta, ruta.with_suffix(".exe")):
            if candidata.exists():
                return str(candidata)

    from shutil import which
    hallado = which(nombre)
    if hallado:
        return hallado

    for base in (Path(r"C:\Program Files\PostgreSQL"),
                 Path(r"C:\Program Files (x86)\PostgreSQL")):
        if base.exists():
            # La versión más nueva primero.
            for version in sorted(base.iterdir(), reverse=True):
                candidata = version / "bin" / f"{nombre}.exe"
                if candidata.exists():
                    return str(candidata)

    raise SystemExit(
        f"No se encontró {nombre}. Es parte de PostgreSQL.\n"
        "Si PostgreSQL está instalado, ponga su carpeta bin en la "
        r"variable PG_BIN del .env (por ejemplo "
        r"PG_BIN=C:\Program Files\PostgreSQL\16\bin)."
    )


def _entorno(conexion: dict) -> dict:
    """La clave va por variable de entorno, nunca en la línea de comando.

    En la línea de comando la vería cualquiera que liste los procesos.
    """
    entorno = os.environ.copy()
    if conexion["clave"]:
        entorno["PGPASSWORD"] = conexion["clave"]
    return entorno


def _correr(orden: list[str], conexion: dict, que_hace: str) -> str:
    resultado = subprocess.run(
        orden, env=_entorno(conexion), capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        salida = (resultado.stderr or resultado.stdout or "").strip()
        raise RuntimeError(f"Falló {que_hace}:\n{salida}")
    return resultado.stdout


def generar(carpeta: Path, conexion: dict) -> Path:
    """Genera el volcado. Formato propio de PostgreSQL, comprimido."""
    marca = datetime.now().strftime("%Y-%m-%d-%H%M")
    destino = carpeta / f"totem-{marca}.dump"
    parcial = destino.with_suffix(".dump.parcial")

    # Se escribe con otro nombre y se renombra al final: si el respaldo
    # se corta a la mitad (se apaga el PC), no queda un archivo que
    # parece bueno esperando el día que haga falta.
    _correr([
        _buscar_herramienta("pg_dump"),
        "-h", conexion["host"], "-p", conexion["puerto"],
        "-U", conexion["usuario"], "-d", conexion["base"],
        "--format=custom", "--compress=9", "--no-owner", "--no-privileges",
        "--file", str(parcial),
    ], conexion, "pg_dump")

    parcial.replace(destino)
    return destino


def conteos_reales() -> dict:
    """Cuántas filas hay ahora mismo en cada tabla esperada."""
    conteos = {}
    with obtener_cursor() as cursor:
        for tabla in TABLAS_ESPERADAS:
            cursor.execute(f"SELECT COUNT(*) AS n FROM {tabla}")
            conteos[tabla] = cursor.fetchone()["n"]
    return conteos


def verificar(archivo: Path, conexion: dict, esperados: dict) -> list[str]:
    """Restaura el volcado en otra base y compara los conteos.

    Devuelve la lista de problemas. Vacía quiere decir que el respaldo
    se puede restaurar y trae lo mismo que la base real.
    """
    problemas = []

    # Primero lo barato: que el archivo traiga las tablas.
    indice = _correr([
        _buscar_herramienta("pg_restore"), "--list", str(archivo),
    ], conexion, "leer el índice del respaldo")
    for tabla in TABLAS_ESPERADAS:
        if not re.search(rf"TABLE DATA public {tabla}\b", indice):
            problemas.append(f"el respaldo no trae la tabla {tabla}")
    if problemas:
        return problemas

    psql = _buscar_herramienta("psql")
    comunes = ["-h", conexion["host"], "-p", conexion["puerto"],
               "-U", conexion["usuario"], "-d", "postgres",
               "-v", "ON_ERROR_STOP=1", "-q"]

    def sql_en_postgres(sentencia: str, que_hace: str) -> None:
        _correr([psql, *comunes, "-c", sentencia], conexion, que_hace)

    try:
        sql_en_postgres(f'DROP DATABASE IF EXISTS "{BASE_DE_PRUEBA}"',
                        "limpiar la base de verificación")
        sql_en_postgres(f'CREATE DATABASE "{BASE_DE_PRUEBA}"',
                        "crear la base de verificación")

        _correr([
            _buscar_herramienta("pg_restore"),
            "-h", conexion["host"], "-p", conexion["puerto"],
            "-U", conexion["usuario"], "-d", BASE_DE_PRUEBA,
            "--no-owner", "--no-privileges", str(archivo),
        ], conexion, "restaurar el respaldo de prueba")

        for tabla, esperado in esperados.items():
            salida = _correr([
                psql, "-h", conexion["host"], "-p", conexion["puerto"],
                "-U", conexion["usuario"], "-d", BASE_DE_PRUEBA,
                "-t", "-A", "-c", f"SELECT COUNT(*) FROM {tabla}",
            ], conexion, f"contar {tabla} en el respaldo")
            restaurado = int(salida.strip() or -1)
            if restaurado != esperado:
                problemas.append(
                    f"{tabla}: la base tiene {esperado} filas y el "
                    f"respaldo {restaurado}"
                )
    finally:
        try:
            sql_en_postgres(f'DROP DATABASE IF EXISTS "{BASE_DE_PRUEBA}"',
                            "borrar la base de verificación")
        except RuntimeError:
            # Que quede la base de prueba es molesto, no grave; y no
            # puede tapar el resultado de la verificación.
            pass

    return problemas


def rotar(carpeta: Path) -> list[Path]:
    """Borra los diarios viejos y conserva el primero de cada mes.

    Si un dato se dañó hace meses y nadie lo notó, los respaldos
    recientes ya traen el daño: por eso se guarda uno por mes.
    """
    respaldos = sorted(carpeta.glob("totem-*.dump"))
    if len(respaldos) <= DIARIOS_A_CONSERVAR:
        return []

    primeros_del_mes = set()
    for archivo in respaldos:
        mes = archivo.name[6:13]          # totem-YYYY-MM
        if mes not in primeros_del_mes:
            primeros_del_mes.add(mes)

    mensuales, vistos = set(), set()
    for archivo in respaldos:
        mes = archivo.name[6:13]
        if mes not in vistos:
            vistos.add(mes)
            mensuales.add(archivo)

    recientes = set(respaldos[-DIARIOS_A_CONSERVAR:])
    borrados = []
    for archivo in respaldos:
        if archivo not in recientes and archivo not in mensuales:
            archivo.unlink()
            borrados.append(archivo)
    return borrados


def anotar(archivo: Path, verificado: bool) -> None:
    """Deja en la base cuándo fue el último respaldo bueno.

    Va en la tabla de configuración, que es donde el sistema ya guarda
    este tipo de cosas, para que el panel pueda avisar cuando lleve
    días sin correr. Si se pierde la base se pierde esta marca, pero
    entonces la marca es lo de menos.
    """
    ConfiguracionRepositorio().guardar(
        CLAVE_ULTIMO_RESPALDO,
        f"{datetime.now().isoformat(timespec='seconds')}|"
        f"{'verificado' if verificado else 'sin verificar'}|"
        f"{archivo.name}",
    )


def estado() -> str:
    crudo = ConfiguracionRepositorio().obtener(CLAVE_ULTIMO_RESPALDO)
    if not crudo:
        return "Nunca se ha hecho un respaldo desde este script."
    cuando, como, nombre = (crudo.split("|") + ["", ""])[:3]
    try:
        fecha = datetime.fromisoformat(cuando)
    except ValueError:
        return f"Último respaldo: {crudo}"
    dias = (datetime.now() - fecha).days
    return (f"Último respaldo: {fecha.strftime('%d/%m/%Y %H:%M')} "
            f"({'hoy' if dias == 0 else f'hace {dias} día(s)'}), "
            f"{como}, {nombre}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sin-verificar", action="store_true",
                        help="genera el volcado sin probar la restauración")
    parser.add_argument("--estado", action="store_true",
                        help="dice cuándo fue el último respaldo y sale")
    opciones = parser.parse_args()

    app = crear_app()
    with app.app_context():
        if opciones.estado:
            print(estado())
            return 0

        carpeta = _carpeta_de_respaldos()
        conexion = _datos_de_conexion()

        # Los conteos se toman ANTES del volcado: si alguien cobra
        # mientras corre, el respaldo puede traer una fila de más, y
        # eso no es un error. Al revés sí lo sería.
        esperados = conteos_reales()

        print(f"Respaldando {conexion['base']} en {carpeta}...")
        archivo = generar(carpeta, conexion)
        tamano = archivo.stat().st_size / 1024
        print(f"  {archivo.name} ({tamano:,.0f} KB)")

        problemas = []
        if opciones.sin_verificar:
            print("  (no se verificó la restauración)")
        else:
            print("  Probando la restauración...")
            problemas = verificar(archivo, conexion, esperados)
            if problemas:
                print("\nEL RESPALDO NO SIRVE:")
                for p in problemas:
                    print(f"  - {p}")
                print(f"\nEl archivo queda en {archivo} para revisarlo,")
                print("pero NO cuente con él. Revise el error de arriba.")
                return 1
            print(f"  Se restauró completo: "
                  f"{sum(esperados.values()):,} filas en "
                  f"{len(esperados)} tablas.")

        for borrado in rotar(carpeta):
            print(f"  Se borró el respaldo viejo {borrado.name}")

        anotar(archivo, verificado=not opciones.sin_verificar)
        print("\nListo.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
