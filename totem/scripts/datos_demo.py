"""Llena la base con datos inventados para ver el sistema funcionando.

Sirve para mirar las pantallas con contenido de verdad -contabilidad
con meses de ventas, el balance con gastos, el calendario con
clases- en lugar de con tablas vacias.

    python -m scripts.datos_demo --confirmar

Opciones:

    --confirmar     Obligatorio. Sin esto no hace nada.
    --meses N       Cuantos meses de historia generar. Por defecto 3.
    --borrar        Borra los datos de demostracion y termina.

SOBRE LOS DATOS
---------------
Todo es inventado. Los nombres son comunes en Ecuador pero las
personas no existen, y los correos van a @example.com, un dominio
reservado que nunca entrega nada: si por error se disparara un
envio, no le llega a nadie.

Las cedulas empiezan en 30, que es el codigo de "ecuatorianos en el
exterior". Son validas para el sistema pero poco probables en la
practica. Aun asi: esto es para una base de prueba local, NO para
la del gimnasio ni para una demostracion publica.

El script se niega a correr si la base ya tiene facturas que no
genero el, para no mezclar invenciones con ventas reales.

COMO SE GENERA
--------------
Pasa por los servicios, no por INSERT sueltos. Asi las membresias,
el IVA, los estados y la bitacora quedan igual que si lo hubiera
hecho una persona desde las pantallas, y de paso se ejercita el
codigo de verdad.
"""

import argparse
import random
import sys
from datetime import date, datetime, time, timedelta

from app import crear_app
from app.db import obtener_cursor
from app.services.cliente_service import ClienteService
from app.services.cobro_service import CobroService
from app.services.gasto_service import GastoService
from app.services.posible_cliente_service import PosibleClienteService

# Marca que identifica lo generado por este script, para poder
# borrarlo despues sin tocar nada mas.
MARCA = "@example.com"

NOMBRES_M = ["Mateo", "Santiago", "Sebastian", "Nicolas", "Diego", "Andres",
             "Joel", "Kevin", "Bryan", "Jorge", "Luis", "Carlos", "David",
             "Esteban", "Paul", "Fernando", "Daniel", "Marco"]
NOMBRES_F = ["Valentina", "Camila", "Doménica", "Emilia", "Martina", "Sofia",
             "Antonella", "Daniela", "Gabriela", "Paula", "Andrea", "Nicole",
             "Micaela", "Rafaela", "Shirley", "Johanna", "Pamela", "Erika"]
APELLIDOS = ["Guaman", "Quizhpe", "Morocho", "Vasquez", "Jaramillo", "Cabrera",
             "Ordonez", "Pesantez", "Zambrano", "Narvaez", "Idrovo", "Crespo",
             "Astudillo", "Bermeo", "Ulloa", "Vintimilla", "Carrasco",
             "Moscoso", "Sigcha", "Chimbo", "Loayza", "Peralta"]

COACHES = [("Lucia", "Vega"), ("Martin", "Salas"), ("Renata", "Ocampo")]

# Gastos fijos: mismo concepto todos los meses, que es lo que hace
# util la sugerencia de recurrentes.
GASTOS_FIJOS = [
    ("Arriendo", 720, "GENERAL", True),
    ("Sueldos", 1050, "GENERAL", True),
    ("Luz", 95, "GENERAL", True),
    ("Agua", 28, "GENERAL", True),
    ("Internet", 35, "GENERAL", True),
]
# Gastos sueltos: aparecen a veces, y no todos con factura.
GASTOS_SUELTOS = [
    ("Magnesio", 60, "GENERAL", True),
    ("Mantenimiento de presas", 140, "SENIOR", False),
    ("Colchonetas", 320, "JUNIOR", True),
    ("Cuerdas y equipo", 210, "SENIOR", True),
    ("Limpieza", 45, "GENERAL", False),
    ("Publicidad", 80, "GENERAL", False),
    ("Refrigerios escuelita", 55, "JUNIOR", False),
    ("Contador", 70, "GENERAL", True),
]


def cedula_valida(semilla: int) -> str:
    """Arma una cedula con digito verificador correcto, provincia 30.

    El tercer digito tiene que ser menor que 6: es lo que distingue a
    una persona natural, y el validador del sistema lo exige.
    """
    cuerpo = f"30{semilla % 6}{semilla // 6 % 1000000:06d}"
    coef = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    suma = 0
    for digito, k in zip(cuerpo, coef):
        producto = int(digito) * k
        suma += producto - 9 if producto > 9 else producto
    return cuerpo + str((10 - suma % 10) % 10)


def _hay_datos_reales() -> int:
    """Facturas de clientes que este script no invento.

    Un menor a cargo no tiene correo propio -no se le inventa uno-,
    asi que se lo reconoce por el de su representante. Sin esto, las
    facturas de los menores parecian reales y el guardia bloqueaba
    una segunda corrida legitima.
    """
    with obtener_cursor() as c:
        c.execute(
            """
            SELECT count(*) AS n
              FROM facturas f
              JOIN clientes cl ON cl.id_cliente = f.id_cliente
         LEFT JOIN clientes rep ON rep.id_cliente = cl.id_representante
             WHERE COALESCE(cl.correo, rep.correo, '') NOT LIKE %s
            """,
            (f"%{MARCA}",),
        )
        return c.fetchone()["n"]


def borrar(verboso=True) -> None:
    """Quita lo inventado y deja el resto intacto."""
    with obtener_cursor(commit=True) as c:
        c.execute(
            "SELECT id_cliente FROM clientes WHERE correo LIKE %s", (f"%{MARCA}",))
        ids = [f["id_cliente"] for f in c.fetchall()]
        # Los menores no tienen correo propio: se los ubica por su
        # representante.
        if ids:
            c.execute(
                "SELECT id_cliente FROM clientes WHERE id_representante = ANY(%s)",
                (ids,))
            ids += [f["id_cliente"] for f in c.fetchall()]

        # Los posibles clientes convertidos apuntan a un cliente, asi
        # que se sueltan ANTES de borrar clientes. Al reves, la clave
        # foranea rechaza el borrado.
        if ids:
            c.execute(
                "UPDATE posibles_clientes "
                "   SET id_cliente = NULL, fecha_conversion = NULL "
                " WHERE id_cliente = ANY(%s)", (ids,))

        if ids:
            c.execute("SELECT id_factura FROM facturas WHERE id_cliente = ANY(%s)",
                      (ids,))
            facturas = [f["id_factura"] for f in c.fetchall()]
            if facturas:
                c.execute("DELETE FROM pagos_fiado WHERE id_factura = ANY(%s)",
                          (facturas,))
                c.execute("DELETE FROM detalle_factura WHERE id_factura = ANY(%s)",
                          (facturas,))
                c.execute("DELETE FROM bitacora WHERE entidad='FACTURA' "
                          "AND id_entidad = ANY(%s)", (facturas,))
            c.execute("DELETE FROM membresias WHERE id_cliente = ANY(%s)", (ids,))
            c.execute("DELETE FROM facturas WHERE id_cliente = ANY(%s)", (ids,))
            c.execute("DELETE FROM evento_inscritos WHERE id_cliente = ANY(%s)", (ids,))
            c.execute("DELETE FROM bitacora WHERE entidad='CLIENTE' "
                      "AND id_entidad = ANY(%s)", (ids,))
            # El representante se borra al final de la lista, pero la
            # FK exige que los menores se vayan primero.
            c.execute("DELETE FROM clientes WHERE id_representante = ANY(%s)", (ids,))
            c.execute("DELETE FROM clientes WHERE id_cliente = ANY(%s)", (ids,))

        c.execute("SELECT id_posible FROM posibles_clientes WHERE correo LIKE %s",
                  (f"%{MARCA}",))
        posibles = [f["id_posible"] for f in c.fetchall()]
        if posibles:
            c.execute("DELETE FROM evento_inscritos WHERE id_posible = ANY(%s)",
                      (posibles,))
            c.execute("DELETE FROM bitacora WHERE entidad='POSIBLE_CLIENTE' "
                      "AND id_entidad = ANY(%s)", (posibles,))
            c.execute("DELETE FROM posibles_clientes WHERE id_posible = ANY(%s)",
                      (posibles,))

        # Eventos que quedaron sin un solo inscrito.
        c.execute(
            """
            DELETE FROM eventos e
             WHERE e.titulo IN ('Clase de prueba', 'Clase demo')
               AND NOT EXISTS (SELECT 1 FROM evento_inscritos i
                                WHERE i.id_evento = e.id_evento)
            """)

        c.execute("DELETE FROM bitacora WHERE entidad='GASTO' AND id_entidad IN "
                  "(SELECT id_gasto FROM gastos WHERE descripcion LIKE %s)",
                  ("%[demo]%",))
        c.execute("DELETE FROM gastos WHERE descripcion LIKE %s", ("%[demo]%",))

        # Los coaches inventados, solo si no quedaron apuntados a nada
        # real. Se comparan con una lista de pares, que psycopg traduce
        # a VALUES; un "IN %s" con tuplas anidadas no es SQL valido.
        c.execute(
            """
            DELETE FROM empleados e
             WHERE e.usuario IS NULL AND e.es_coach
               AND (e.nombre, e.apellido) IN (
                     SELECT v.nombre, v.apellido
                       FROM (VALUES %s) AS v(nombre, apellido))
               AND NOT EXISTS (SELECT 1 FROM posibles_clientes p
                                WHERE p.id_coach = e.id_empleado
                                   OR p.id_empleado = e.id_empleado)
               AND NOT EXISTS (SELECT 1 FROM evento_inscritos i
                                WHERE i.id_empleado = e.id_empleado)
               AND NOT EXISTS (SELECT 1 FROM facturas f
                                WHERE f.id_empleado = e.id_empleado)
               AND NOT EXISTS (SELECT 1 FROM bitacora b
                                WHERE b.id_empleado = e.id_empleado)
            """.replace("%s", ", ".join(["(%s, %s)"] * len(COACHES))),
            [dato for par in COACHES for dato in par],
        )

    if verboso:
        print("Datos de demostracion borrados.")


def _coaches(cursor) -> list[int]:
    ids = []
    for nombre, apellido in COACHES:
        cursor.execute(
            "SELECT id_empleado FROM empleados WHERE nombre=%s AND apellido=%s",
            (nombre, apellido))
        fila = cursor.fetchone()
        if fila:
            ids.append(fila["id_empleado"])
            continue
        cursor.execute(
            "INSERT INTO empleados (nombre, apellido, es_coach) "
            "VALUES (%s,%s,TRUE) RETURNING id_empleado", (nombre, apellido))
        ids.append(cursor.fetchone()["id_empleado"])
    return ids


def generar(meses: int, id_empleado: int, azar: random.Random) -> dict:
    hoy = date.today()
    desde = hoy - timedelta(days=30 * meses)

    with obtener_cursor(commit=True) as c:
        ids_coach = _coaches(c)
        c.execute("SELECT id_plan, nombre, tipo, precio, dias_incluidos "
                  "FROM planes_membresia WHERE activo")
        planes = c.fetchall()
        c.execute("SELECT id_producto, nombre, precio FROM productos WHERE activo")
        productos = c.fetchall()

    if not planes:
        raise SystemExit(
            "La base no tiene planes activos. Corre primero totem-schema-v4.sql.")

    por_nombre = {p["nombre"]: p for p in planes}
    junior = next((p for p in planes if p["tipo"] == "JUNIOR"), None)
    mensual = por_nombre.get("Membresía Senior") or planes[0]
    pases = [p for p in planes if p["dias_incluidos"]]

    clientes = ClienteService()
    cobros = CobroService()
    gastos = GastoService()
    posibles = PosibleClienteService()

    hechos = {"clientes": 0, "menores": 0, "facturas": 0, "gastos": 0,
              "posibles": 0, "convertidos": 0}

    # ---------- Clientes ----------
    ids_clientes = []
    ids_menores = []
    for i in range(38):
        femenino = azar.random() < 0.45
        nombre = azar.choice(NOMBRES_F if femenino else NOMBRES_M)
        apellido = f"{azar.choice(APELLIDOS)} {azar.choice(APELLIDOS)}"
        nacimiento = date(azar.randint(1975, 2006), azar.randint(1, 12),
                          azar.randint(1, 28))

        # Dos cumpleaños esta semana, para que el panel tenga avisos.
        if i < 2:
            cumple = hoy + timedelta(days=i + 1)
            nacimiento = date(azar.randint(1985, 2000), cumple.month, cumple.day)

        datos = {
            "nombre": nombre,
            "apellido": apellido,
            "cedula": cedula_valida(1000000 + i * 37),
            "fecha_nacimiento": nacimiento.isoformat(),
            "correo": f"{nombre.lower()}.{apellido.split()[0].lower()}{i}{MARCA}",
            "telefono": f"09{azar.randint(10000000, 99999999)}",
            "genero": "FEMENINO" if femenino else "MASCULINO",
            "contacto_emergencia": f"09{azar.randint(10000000, 99999999)}",
            "referencia": azar.choice(
                ["Instagram", "Un amigo", "Pasaba por ahí", "Google", ""]),
        }

        # Uno de cada cinco trae un menor a cargo: es lo que llena la
        # escuelita y le da sentido al segmento Junior.
        menores = []
        if azar.random() < 0.22:
            menores.append({
                "nombre": azar.choice(NOMBRES_F + NOMBRES_M),
                "apellido": apellido,
                "fecha_nacimiento": date(
                    azar.randint(2012, 2018), azar.randint(1, 12),
                    azar.randint(1, 28)).isoformat(),
            })

        id_cliente = clientes.crear(datos, menores, id_empleado)
        ids_clientes.append(id_cliente)
        hechos["clientes"] += 1
        hechos["menores"] += len(menores)

        if menores:
            with obtener_cursor() as c:
                c.execute("SELECT id_cliente FROM clientes WHERE id_representante=%s",
                          (id_cliente,))
                ids_menores += [f["id_cliente"] for f in c.fetchall()]

    # ---------- Ventas repartidas en el tiempo ----------
    dia = desde
    while dia <= hoy:
        # Menos movimiento los domingos; el gimnasio tambien respira.
        ventas = azar.randint(0, 2) if dia.weekday() == 6 else azar.randint(2, 7)

        for _ in range(ventas):
            quien = azar.choice(ids_clientes)
            items = []

            tirada = azar.random()
            if tirada < 0.42:
                items.append({"tipo": "plan", "id_item": str(mensual["id_plan"]),
                              "cantidad": "1"})
            elif tirada < 0.58 and junior and ids_menores:
                quien = azar.choice(ids_menores)
                items.append({"tipo": "plan", "id_item": str(junior["id_plan"]),
                              "cantidad": "1"})
            elif tirada < 0.85 and pases:
                items.append({"tipo": "plan",
                              "id_item": str(azar.choice(pases)["id_plan"]),
                              "cantidad": "1"})

            # Productos: a veces solos, a veces de acompañamiento.
            if productos and (not items or azar.random() < 0.3):
                items.append({"tipo": "producto",
                              "id_item": str(azar.choice(productos)["id_producto"]),
                              "cantidad": str(azar.randint(1, 2))})

            if not items:
                continue

            formulario = {
                "id_cliente": str(quien),
                "metodo_pago": azar.choice(
                    ["EFECTIVO", "EFECTIVO", "TRANSFERENCIA"]),
            }
            # Uno de cada veinticinco queda fiado, para que la pantalla
            # de fiados no este vacia.
            if azar.random() < 0.02:
                formulario["forma_cobro"] = "fiar"
                formulario["monto_recibido"] = "0"

            # Y a algun Junior se le aplica descuento, que es para lo
            # que ese plan lo permite.
            if junior and items[0].get("id_item") == str(junior["id_plan"]):
                if azar.random() < 0.6:
                    formulario["descuento_porcentaje"] = str(
                        azar.choice([20, 30, 40, 50]))

            try:
                resultado = cobros.cobrar(formulario, items, id_empleado)
            except Exception:  # noqa: BLE001
                continue
            id_factura = resultado[0] if isinstance(resultado, tuple) else resultado
            hechos["facturas"] += 1

            # La fecha real de la venta: el servicio pone hoy, asi que
            # se corre hacia atras para tener historia.
            with obtener_cursor(commit=True) as c:
                momento = datetime.combine(
                    dia, time(azar.randint(9, 20), azar.choice([0, 15, 30, 45])))
                c.execute("UPDATE facturas SET fecha=%s WHERE id_factura=%s",
                          (momento, id_factura))
                c.execute(
                    "UPDATE membresias SET fecha_inicio=%s, "
                    "fecha_fin = %s + (fecha_fin - fecha_inicio) "
                    "WHERE id_factura=%s", (dia, dia, id_factura))

        dia += timedelta(days=1)

    # ---------- Una factura anulada ----------
    with obtener_cursor() as c:
        c.execute("SELECT id_factura FROM facturas WHERE estado='EMITIDA' "
                  "ORDER BY random() LIMIT 1")
        fila = c.fetchone()
    if fila:
        try:
            cobros.anular(fila["id_factura"], "Cobrada dos veces por error",
                          id_empleado)
        except Exception:  # noqa: BLE001
            pass

    # ---------- Gastos ----------
    mes = date(desde.year, desde.month, 1)
    while mes <= hoy:
        for concepto, base, segmento, facturado in GASTOS_FIJOS:
            dia_pago = mes.replace(day=min(azar.randint(1, 6), 28))
            if dia_pago > hoy:
                continue
            monto = base * azar.uniform(0.95, 1.08)
            gastos.guardar({
                "fecha": dia_pago.isoformat(),
                "monto": f"{monto:.2f}",
                "segmento": segmento,
                "concepto": concepto,
                "facturado": "on" if facturado else "",
                "metodo_pago": "TRANSFERENCIA",
                "descripcion": f"[demo] {concepto} de {mes.strftime('%m/%Y')}",
            }, id_empleado=id_empleado)
            hechos["gastos"] += 1

        for concepto, base, segmento, facturado in GASTOS_SUELTOS:
            if azar.random() > 0.45:
                continue
            dia_pago = mes.replace(day=min(azar.randint(1, 28), 28))
            if dia_pago > hoy:
                continue
            monto = base * azar.uniform(0.8, 1.3)
            gastos.guardar({
                "fecha": dia_pago.isoformat(),
                "monto": f"{monto:.2f}",
                "segmento": segmento,
                "concepto": concepto,
                "facturado": "on" if facturado else "",
                "metodo_pago": azar.choice(["EFECTIVO", "TRANSFERENCIA"]),
                "descripcion": f"[demo] {concepto}",
            }, id_empleado=id_empleado)
            hechos["gastos"] += 1

        mes = (mes.replace(day=28) + timedelta(days=5)).replace(day=1)

    # Un gasto anulado, para que se vea como queda.
    with obtener_cursor() as c:
        c.execute("SELECT id_gasto FROM gastos WHERE estado='REGISTRADO' "
                  "AND descripcion LIKE '%[demo]%' ORDER BY random() LIMIT 1")
        fila = c.fetchone()
    if fila:
        gastos.anular(fila["id_gasto"], "Cargado dos veces por error", id_empleado)

    # ---------- Posibles clientes y clases de prueba ----------
    # El servicio no deja agendar en el pasado, y hace bien: nadie
    # reserva una clase para ayer. Asi que todas se agendan a futuro y
    # despues se corre la fecha del evento hacia atras, igual que con
    # las facturas. De los catorce, nueve quedan en el pasado para que
    # haya asistencias y conversiones que mirar.
    atrasos = [azar.randint(3, 45) for _ in range(9)] + [0] * 5
    azar.shuffle(atrasos)

    for i, atraso in enumerate(atrasos):
        femenino = azar.random() < 0.5
        nombre = azar.choice(NOMBRES_F if femenino else NOMBRES_M)
        apellido = azar.choice(APELLIDOS)
        cuando = hoy + timedelta(days=azar.randint(1, 9))
        try:
            nuevo = posibles.agendar({
                "nombre": nombre,
                "apellido": apellido,
                "correo": f"posible{i}{MARCA}",
                "telefono": f"09{azar.randint(10000000, 99999999)}",
                "fecha": cuando.isoformat(),
                "hora_inicio": f"{azar.choice([10, 11, 16, 17, 18, 19])}:00",
                "id_coach": str(azar.choice(ids_coach)) if azar.random() < 0.8 else "",
                "notas": azar.choice(
                    ["Preguntó por la escuelita", "Viene con un amigo",
                     "Primera vez escalando", ""]),
            }, id_empleado=id_empleado)
            hechos["posibles"] += 1
        except Exception as error:  # noqa: BLE001
            print(f"  (no se pudo agendar a {nombre}: {error})")
            continue

        if atraso:
            with obtener_cursor(commit=True) as c:
                # Solo si el evento no tiene a nadie mas: moverlo
                # arrastraria la clase de otro.
                c.execute(
                    """
                    UPDATE eventos e SET fecha = fecha - %s * interval '1 day'
                     WHERE e.id_evento = (
                        SELECT i.id_evento FROM evento_inscritos i
                         WHERE i.id_posible = %s)
                       AND (SELECT count(*) FROM evento_inscritos i2
                             WHERE i2.id_evento = e.id_evento) = 1
                    """, (atraso, nuevo))

    # Asistencias de los que ya pasaron, y algunas conversiones.
    with obtener_cursor(commit=True) as c:
        c.execute(
            """
            UPDATE posibles_clientes p SET asistio = (random() < 0.7)
              FROM evento_inscritos i JOIN eventos e ON e.id_evento = i.id_evento
             WHERE i.id_posible = p.id_posible AND e.fecha < CURRENT_DATE
               AND p.correo LIKE %s
            """, (f"%{MARCA}",))

        # Los que asistieron y se quedaron: se los enlaza con un cliente
        # existente, que es lo que hace el cobro de verdad.
        c.execute(
            "SELECT id_posible FROM posibles_clientes "
            "WHERE asistio AND id_cliente IS NULL AND correo LIKE %s "
            "ORDER BY random() LIMIT 4", (f"%{MARCA}",))
        for fila in c.fetchall():
            # La fecha va junto con el cliente: el esquema no deja
            # marcar a alguien como convertido sin decir cuando.
            c.execute(
                "UPDATE posibles_clientes "
                "   SET id_cliente = %s, fecha_conversion = CURRENT_DATE - %s "
                " WHERE id_posible = %s",
                (azar.choice(ids_clientes), azar.randint(1, 30),
                 fila["id_posible"]))
            hechos["convertidos"] += 1

    return hechos


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Llena la base con datos inventados para ver el sistema.")
    parser.add_argument("--confirmar", action="store_true",
                        help="Obligatorio: sin esto no hace nada.")
    parser.add_argument("--meses", type=int, default=3,
                        help="Meses de historia a generar (por defecto 3).")
    parser.add_argument("--borrar", action="store_true",
                        help="Borra los datos de demostracion y termina.")
    parser.add_argument("--semilla", type=int, default=None,
                        help="Para repetir exactamente la misma generacion.")
    args = parser.parse_args(argv)

    app = crear_app()
    with app.app_context():
        if args.borrar:
            borrar()
            return 0

        if not args.confirmar:
            print("Esto escribe datos inventados en la base.")
            print("Si estas seguro, agrega --confirmar.")
            return 1

        reales = _hay_datos_reales()
        if reales:
            print(f"ALTO: la base tiene {reales} factura(s) que no son de prueba.")
            print("Este script es para una base de desarrollo, no para la del")
            print("gimnasio. Si de verdad queres seguir, borra esas facturas o")
            print("usa otra base.")
            return 1

        with obtener_cursor() as c:
            c.execute("SELECT id_empleado FROM empleados WHERE rol='ADMIN' "
                      "AND activo ORDER BY id_empleado LIMIT 1")
            fila = c.fetchone()
        if fila is None:
            print("No hay ningun ADMIN activo. Corre primero:")
            print("   python -m scripts.crear_admin")
            return 1

        print("Generando... (pasa por los servicios, tarda un poco)")
        borrar(verboso=False)  # por si quedo algo de una corrida anterior

        azar = random.Random(args.semilla)
        hechos = generar(args.meses, fila["id_empleado"], azar)

        print()
        print(f"  {hechos['clientes']} clientes ({hechos['menores']} menores a cargo)")
        print(f"  {hechos['facturas']} facturas en {args.meses} meses")
        print(f"  {hechos['gastos']} gastos")
        print(f"  {hechos['posibles']} posibles clientes ({hechos['convertidos']} convertidos)")
        print()
        print("Listo. Mira Contabilidad, Balance general y el Calendario.")
        print("Para quitarlo todo:  python -m scripts.datos_demo --borrar")

    return 0


if __name__ == "__main__":
    sys.exit(main())
