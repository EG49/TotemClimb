"""Corregir la cedula del cliente desde una factura rechazada.

El SRI rechaza una factura por la identificacion del comprador. La
pantalla decia "hay que corregir la cedula" y no daba con que: habia
que irse a Clientes, buscar a la persona, editarla, volver a
encontrar la factura y acordarse de reemitir.

Ahora se corrige ahi mismo. Lo que hay que cuidar es que ese atajo no
sea una puerta de atras: valida igual que el formulario completo, deja
rastro igual, y sobre todo NO pisa el resto de la ficha del cliente.
Eso ultimo es lo que mas se prueba aca, porque es lo que se romperia
sin que nadie lo note -- el telefono o la fecha de nacimiento de un
cliente borrados al corregirle la cedula no dan ningun error.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app  # noqa: E402
from app.db import obtener_cursor  # noqa: E402
from app.services.cliente_service import ClienteService  # noqa: E402
from app.services.validaciones import ErrorValidacion  # noqa: E402

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


def rechaza(etiqueta, funcion, parte_del_mensaje=""):
    try:
        funcion()
    except ErrorValidacion as error:
        texto = " ".join(error.errores.values()).lower()
        revisar(etiqueta, parte_del_mensaje.lower() in texto, texto[:70])
    except ValueError as error:
        revisar(etiqueta, parte_del_mensaje.lower() in str(error).lower(),
                str(error)[:70])
    else:
        revisar(etiqueta, False, "no la rechazo")


app = crear_app()
with app.app_context():
    servicio = ClienteService()

    # Cedulas validas que no usa nadie en la base. Se buscan en vez de
    # escribirlas: una escrita a mano puede coincidir con un cliente
    # real o de demostracion, y entonces la prueba falla por un choque
    # que no tiene nada que ver con lo que mide.
    from app.services.validaciones import validar_cedula

    with obtener_cursor() as cursor:
        cursor.execute("SELECT cedula FROM clientes WHERE cedula IS NOT NULL")
        ocupadas = {f["cedula"] for f in cursor.fetchall()}

    def _libres(cuantas):
        halladas = []
        for base in range(201000000, 201099999):
            for digito in range(10):
                posible = f"{base}{digito}"
                if (len(posible) == 10 and validar_cedula(posible)
                        and posible not in ocupadas):
                    halladas.append(posible)
                    break
            if len(halladas) == cuantas:
                return halladas
        raise RuntimeError("no se encontraron cedulas libres")

    PROPIA, OTRA, AJENA = _libres(3)

    with obtener_cursor() as cursor:
        cursor.execute("SELECT id_empleado FROM empleados LIMIT 1")
        id_empleado = cursor.fetchone()["id_empleado"]

    # Un cliente propio, con la ficha llena, para ver que no se pise.
    with obtener_cursor(commit=True) as cursor:
        cursor.execute(
            "INSERT INTO clientes (nombre, apellido, cedula, correo, "
            "  telefono, fecha_nacimiento) "
            "VALUES ('Prueba', 'Corregir', NULL, 'prueba@gmail.com', "
            "  '0999999999', '1990-05-20') RETURNING id_cliente"
        )
        id_cliente = cursor.fetchone()["id_cliente"]

    def ficha():
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT cedula, correo, telefono, fecha_nacimiento, nombre, "
                "       apellido FROM clientes WHERE id_cliente = %s",
                (id_cliente,),
            )
            return dict(cursor.fetchone())

    antes = ficha()

    try:
        print("\nSE RECHAZA LO QUE NO ES UNA CEDULA")
        # Las mismas validaciones del formulario completo: este atajo
        # no puede ser una puerta de atras.
        rechaza("vacia",
                lambda: servicio.corregir_identificacion(id_cliente, "", id_empleado),
                "escriba")
        rechaza("solo espacios",
                lambda: servicio.corregir_identificacion(id_cliente, "   ", id_empleado),
                "escriba")
        rechaza("menos de 10 digitos",
                lambda: servicio.corregir_identificacion(id_cliente, "12345", id_empleado),
                "no es válida")
        rechaza("con digito verificador malo",
                lambda: servicio.corregir_identificacion(id_cliente, "1234567890", id_empleado),
                "no es válida")
        rechaza("provincia inexistente",
                lambda: servicio.corregir_identificacion(id_cliente, "9901585387", id_empleado),
                "no es válida")

        revisar("y la ficha quedo intacta tras los rechazos",
                ficha() == antes, "algo cambio con una cedula invalida")

        print("\nSE GUARDA UNA CEDULA BUENA")
        servicio.corregir_identificacion(id_cliente, PROPIA, id_empleado)
        ahora = ficha()
        revisar("queda guardada", ahora["cedula"] == PROPIA,
                str(ahora["cedula"]))

        print("\nY NO SE PISA EL RESTO DE LA FICHA")
        # Esto es lo importante. corregir_identificacion no usa
        # actualizar() justamente porque aquel espera el formulario
        # entero: pasarle solo la cedula habria borrado lo demas, sin
        # dar ningun error.
        for campo in ("correo", "telefono", "fecha_nacimiento", "nombre",
                      "apellido"):
            revisar(f"{campo} sigue igual", ahora[campo] == antes[campo],
                    f"{antes[campo]!r} -> {ahora[campo]!r}")

        print("\nSE ACEPTA CON ESPACIOS Y GUIONES")
        servicio.corregir_identificacion(id_cliente, f"  {OTRA}  ", id_empleado)
        revisar("se limpia antes de guardar",
                ficha()["cedula"] == OTRA, str(ficha()["cedula"]))

        print("\nNO SE PUEDE DUPLICAR LA DE OTRO CLIENTE")
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "INSERT INTO clientes (nombre, apellido, cedula) "
                "VALUES ('Otro', 'Cliente', %s) RETURNING id_cliente",
                (AJENA,),
            )
            id_otro = cursor.fetchone()["id_cliente"]
        try:
            rechaza("la cedula de otro se rechaza",
                    lambda: servicio.corregir_identificacion(
                        id_cliente, AJENA, id_empleado),
                    "ya existe")
        finally:
            with obtener_cursor(commit=True) as cursor:
                cursor.execute("DELETE FROM clientes WHERE id_cliente = %s",
                               (id_otro,))

        print("\nGUARDAR LA MISMA NO ROMPE NADA")
        servicio.corregir_identificacion(id_cliente, OTRA, id_empleado)
        revisar("sigue siendo la misma", ficha()["cedula"] == OTRA)

        print("\nQUEDA RASTRO DE QUIEN LA CAMBIO")
        # Un dato que define a quien se le factura no puede cambiarse
        # sin dejar constancia.
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT accion, detalle FROM bitacora "
                " WHERE entidad = 'CLIENTE' AND id_entidad = %s "
                " ORDER BY id_bitacora DESC LIMIT 1",
                (id_cliente,),
            )
            fila = cursor.fetchone()
        revisar("anotado en la bitacora", fila is not None)
        if fila:
            revisar("como edicion del cliente",
                    fila["accion"] == "CLIENTE_EDITADO", str(fila["accion"]))
            revisar("con la cedula anterior y la nueva",
                    "antes" in str(fila["detalle"])
                    and "ahora" in str(fila["detalle"]),
                    str(fila["detalle"])[:60])

        print("\nUN CLIENTE QUE NO EXISTE")
        rechaza("avisa en vez de reventar",
                lambda: servicio.corregir_identificacion(-1, PROPIA, id_empleado),
                "no existe")

    finally:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute("DELETE FROM bitacora WHERE entidad = 'CLIENTE' "
                           "  AND id_entidad = %s", (id_cliente,))
            cursor.execute("DELETE FROM clientes WHERE id_cliente = %s",
                           (id_cliente,))

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
