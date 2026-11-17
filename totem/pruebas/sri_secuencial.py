"""Pruebas de la numeracion de comprobantes del SRI.

Lo que se comprueba no es que el numero suba de a uno: eso es facil
y no es donde falla. Se comprueba lo que de verdad importa y solo se
ve bajo carga:

  1. Que dos cobros simultaneos NUNCA reciban el mismo numero. Dos
     comprobantes con el mismo numero en el mismo punto de emision no
     se deshacen: lo emitido, emitido esta.

  2. Que un cobro que falla DEVUELVA su numero. Un hueco en la
     numeracion hay que explicarselo al SRI.

  3. Que la base rechace por su cuenta una factura que repita numero
     o clave de acceso, por si algun dia alguien escribe el secuencial
     sin pasar por la reserva.

Hace falta la base de pruebas con Sql/alter-sri-secuenciales.sql ya
corrido.
"""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app  # noqa: E402
from app.db import obtener_cursor  # noqa: E402
from app.repositories.sri_repo import (  # noqa: E402
    ErrorSecuencial, FACTURA, SriRepositorio,
)

ESTAB = "001"
PUNTO = "009"  # un punto de emision solo para esta prueba
HILOS = 12
POR_HILO = 25

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


def preparar():
    with obtener_cursor(commit=True) as cursor:
        cursor.execute(
            "DELETE FROM sri_secuenciales WHERE punto_emision = %s", (PUNTO,)
        )
        cursor.execute(
            """
            INSERT INTO sri_secuenciales
                (establecimiento, punto_emision, tipo_comprobante,
                 ultimo_secuencial)
            VALUES (%s, %s, %s, 0)
            """,
            (ESTAB, PUNTO, FACTURA),
        )


def limpiar():
    with obtener_cursor(commit=True) as cursor:
        cursor.execute(
            "DELETE FROM sri_secuenciales WHERE punto_emision = %s", (PUNTO,)
        )


app = crear_app()
repo = SriRepositorio()

with app.app_context():
    preparar()

    print("\nLO BASICO")
    with obtener_cursor(commit=True) as cursor:
        primero = repo.reservar_secuencial(cursor, ESTAB, PUNTO)
        segundo = repo.reservar_secuencial(cursor, ESTAB, PUNTO)
    revisar("el primer comprobante es el 1", primero == 1, str(primero))
    revisar("el siguiente es el 2", segundo == 2, str(segundo))
    revisar("queda anotado como ultimo entregado",
            repo.ultimo_secuencial(ESTAB, PUNTO) == 2,
            str(repo.ultimo_secuencial(ESTAB, PUNTO)))

    print("\nUN COBRO QUE FALLA DEVUELVE SU NUMERO")
    # Sin esto la numeracion quedaria con huecos cada vez que un
    # cobro se cae a la mitad, y cada hueco hay que explicarlo.
    antes = repo.ultimo_secuencial(ESTAB, PUNTO)
    try:
        with obtener_cursor(commit=True) as cursor:
            repo.reservar_secuencial(cursor, ESTAB, PUNTO)
            raise RuntimeError("se cayo el cobro a la mitad")
    except RuntimeError:
        pass
    despues = repo.ultimo_secuencial(ESTAB, PUNTO)
    revisar("el numero vuelve a estar libre", antes == despues,
            f"antes {antes}, despues {despues}")

    with obtener_cursor(commit=True) as cursor:
        siguiente = repo.reservar_secuencial(cursor, ESTAB, PUNTO)
    revisar("y lo toma el cobro siguiente, sin saltarse ninguno",
            siguiente == antes + 1, f"dio {siguiente}, se esperaba {antes + 1}")

    print(f"\n{HILOS} CAJAS COBRANDO A LA VEZ, {POR_HILO} COBROS CADA UNA")
    preparar()
    entregados = []
    candado = threading.Lock()
    errores = []
    arrancar = threading.Event()

    def caja():
        mios = []
        # Todos esperan acá para largar juntos: si cada hilo arranca
        # cuando termina de crearse, no se pisan y la prueba no
        # prueba nada.
        arrancar.wait()
        try:
            for _ in range(POR_HILO):
                with app.app_context():
                    with obtener_cursor(commit=True) as cursor:
                        mios.append(
                            repo.reservar_secuencial(cursor, ESTAB, PUNTO)
                        )
        except Exception as error:  # noqa: BLE001
            errores.append(f"{type(error).__name__}: {error}")
        with candado:
            entregados.extend(mios)

    hilos = [threading.Thread(target=caja) for _ in range(HILOS)]
    for hilo in hilos:
        hilo.start()
    arrancar.set()
    for hilo in hilos:
        hilo.join(timeout=120)

    revisar("ninguna caja fallo", not errores, "; ".join(errores[:2]))

    esperados = HILOS * POR_HILO
    revisar(f"se entregaron los {esperados} numeros",
            len(entregados) == esperados, str(len(entregados)))

    repetidos = len(entregados) - len(set(entregados))
    revisar("NINGUN numero salio dos veces", repetidos == 0,
            f"{repetidos} repetidos")

    revisar("y no quedo ningun hueco",
            sorted(entregados) == list(range(1, esperados + 1)),
            f"del {min(entregados)} al {max(entregados)}")

    revisar("la base coincide con lo entregado",
            repo.ultimo_secuencial(ESTAB, PUNTO) == esperados,
            str(repo.ultimo_secuencial(ESTAB, PUNTO)))

    print("\nSI FALTA LA NUMERACION, SE DICE CLARO")
    try:
        with obtener_cursor() as cursor:
            repo.reservar_secuencial(cursor, ESTAB, "777")
        revisar("un punto de emision inexistente levanta error", False,
                "no levanto")
    except ErrorSecuencial as error:
        revisar("un punto de emision inexistente levanta error", True)
        revisar("y el mensaje dice que archivo correr",
                "alter-sri-secuenciales" in str(error), str(error)[:60])

    print("\nLA BASE NO DEJA REPETIR NUMERO NI CLAVE")
    # La red de seguridad, por si algun dia alguien escribe el
    # secuencial sin pasar por la reserva.
    import psycopg

    with obtener_cursor() as cursor:
        cursor.execute(
            "SELECT id_factura FROM facturas ORDER BY id_factura LIMIT 2"
        )
        facturas = [f["id_factura"] for f in cursor.fetchall()]

    if len(facturas) < 2:
        print("  (hacen falta 2 facturas en la base; se omite)")
    else:
        clave = "9" * 49
        try:
            with obtener_cursor(commit=True) as cursor:
                for id_factura in facturas:
                    cursor.execute(
                        """
                        UPDATE facturas
                           SET sri_establecimiento = %s,
                               sri_punto_emision = %s,
                               sri_secuencial = 4242
                         WHERE id_factura = %s
                        """,
                        (ESTAB, PUNTO, id_factura),
                    )
            revisar("rechaza dos facturas con el mismo numero", False,
                    "las acepto")
        except psycopg.errors.UniqueViolation:
            revisar("rechaza dos facturas con el mismo numero", True)

        try:
            with obtener_cursor(commit=True) as cursor:
                for id_factura in facturas:
                    cursor.execute(
                        "UPDATE facturas SET sri_clave_acceso = %s "
                        "WHERE id_factura = %s",
                        (clave, id_factura),
                    )
            revisar("rechaza dos facturas con la misma clave de acceso",
                    False, "las acepto")
        except psycopg.errors.UniqueViolation:
            revisar("rechaza dos facturas con la misma clave de acceso", True)

        # Se deshace lo que haya quedado.
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE facturas
                   SET sri_establecimiento = NULL, sri_punto_emision = NULL,
                       sri_secuencial = NULL, sri_clave_acceso = NULL
                 WHERE id_factura = ANY(%s)
                """,
                (facturas,),
            )

    limpiar()

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
