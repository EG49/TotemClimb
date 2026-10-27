"""Repositorios del calendario: eventos, categorías e inscripciones."""

from datetime import date

from app.db import obtener_cursor
from app.models.evento import CategoriaEvento, Cumpleanos, Evento

_SELECT_EVENTO = """
    SELECT e.id_evento, e.titulo, e.id_categoria, e.fecha,
           e.hora_inicio, e.hora_fin, e.descripcion, e.cupo_maximo,
           c.nombre AS categoria_nombre, c.color AS categoria_color,
           (SELECT count(*) FROM evento_inscritos i
             WHERE i.id_evento = e.id_evento) AS inscritos
      FROM eventos e
      JOIN categorias_evento c ON c.id_categoria = e.id_categoria
"""


class CategoriaRepositorio:

    def listar(self) -> list[CategoriaEvento]:
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT id_categoria, nombre, color FROM categorias_evento "
                "ORDER BY id_categoria"
            )
            return [CategoriaEvento(**f) for f in cursor.fetchall()]

    def obtener(self, id_categoria: int) -> CategoriaEvento | None:
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT id_categoria, nombre, color FROM categorias_evento "
                "WHERE id_categoria = %s",
                (id_categoria,),
            )
            fila = cursor.fetchone()
        return CategoriaEvento(**fila) if fila else None


class EventoRepositorio:

    def entre(self, desde: date, hasta: date) -> list[Evento]:
        with obtener_cursor() as cursor:
            cursor.execute(
                f"{_SELECT_EVENTO} WHERE e.fecha BETWEEN %s AND %s "
                "ORDER BY e.fecha, e.hora_inicio",
                (desde, hasta),
            )
            return [Evento.desde_fila(f) for f in cursor.fetchall()]

    def obtener(self, id_evento: int) -> Evento | None:
        with obtener_cursor() as cursor:
            cursor.execute(f"{_SELECT_EVENTO} WHERE e.id_evento = %s", (id_evento,))
            fila = cursor.fetchone()
            if fila is None:
                return None
            evento = Evento.desde_fila(fila)

            cursor.execute(
                """
                SELECT i.id_evento_inscrito, i.fecha_inscripcion,
                       cl.id_cliente,
                       cl.nombre || ' ' || cl.apellido AS cliente_nombre,
                       cl.cedula,
                       em.nombre || ' ' || em.apellido AS agendado_por
                  FROM evento_inscritos i
                  JOIN clientes cl ON cl.id_cliente = i.id_cliente
                  JOIN empleados em ON em.id_empleado = i.id_empleado
                 WHERE i.id_evento = %s
                 ORDER BY i.fecha_inscripcion
                """,
                (id_evento,),
            )
            evento.nombres_inscritos = cursor.fetchall()
        return evento

    def proximos(self, limite: int = 5) -> list[Evento]:
        with obtener_cursor() as cursor:
            cursor.execute(
                f"{_SELECT_EVENTO} WHERE e.fecha >= CURRENT_DATE "
                "ORDER BY e.fecha, e.hora_inicio LIMIT %s",
                (limite,),
            )
            return [Evento.desde_fila(f) for f in cursor.fetchall()]

    def de_categoria_entre(
        self, id_categoria: int, desde: date, hasta: date
    ) -> list[Evento]:
        """Eventos de una categoría en un rango. Lo usa la clase de prueba."""
        with obtener_cursor() as cursor:
            cursor.execute(
                f"{_SELECT_EVENTO} WHERE e.id_categoria = %s "
                "AND e.fecha BETWEEN %s AND %s ORDER BY e.fecha, e.hora_inicio",
                (id_categoria, desde, hasta),
            )
            return [Evento.desde_fila(f) for f in cursor.fetchall()]

    def crear(self, datos: dict, cursor=None) -> int:
        sql = """
            INSERT INTO eventos
                (titulo, id_categoria, fecha, hora_inicio, hora_fin,
                 descripcion, cupo_maximo)
            VALUES (%(titulo)s, %(id_categoria)s, %(fecha)s, %(hora_inicio)s,
                    %(hora_fin)s, %(descripcion)s, %(cupo_maximo)s)
            RETURNING id_evento
        """
        if cursor is not None:
            cursor.execute(sql, datos)
            return cursor.fetchone()["id_evento"]
        with obtener_cursor(commit=True) as c:
            c.execute(sql, datos)
            return c.fetchone()["id_evento"]

    def actualizar(self, id_evento: int, datos: dict) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE eventos
                   SET titulo = %(titulo)s, id_categoria = %(id_categoria)s,
                       fecha = %(fecha)s, hora_inicio = %(hora_inicio)s,
                       hora_fin = %(hora_fin)s, descripcion = %(descripcion)s,
                       cupo_maximo = %(cupo_maximo)s
                 WHERE id_evento = %(id_evento)s
                """,
                {**datos, "id_evento": id_evento},
            )

    def eliminar(self, id_evento: int) -> None:
        """Borra el evento. Las inscripciones caen con él (ON DELETE CASCADE)."""
        with obtener_cursor(commit=True) as cursor:
            cursor.execute("DELETE FROM eventos WHERE id_evento = %s", (id_evento,))


class InscripcionRepositorio:

    def inscribir(self, id_evento: int, id_cliente: int, id_empleado: int, cursor=None):
        sql = """
            INSERT INTO evento_inscritos (id_evento, id_cliente, id_empleado)
            VALUES (%s, %s, %s)
            ON CONFLICT (id_evento, id_cliente) DO NOTHING
            RETURNING id_evento_inscrito
        """
        if cursor is not None:
            cursor.execute(sql, (id_evento, id_cliente, id_empleado))
            fila = cursor.fetchone()
            return fila["id_evento_inscrito"] if fila else None
        with obtener_cursor(commit=True) as c:
            c.execute(sql, (id_evento, id_cliente, id_empleado))
            fila = c.fetchone()
            return fila["id_evento_inscrito"] if fila else None

    def quitar(self, id_evento: int, id_cliente: int) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "DELETE FROM evento_inscritos WHERE id_evento = %s AND id_cliente = %s",
                (id_evento, id_cliente),
            )

    def contar_en(self, id_evento: int, cursor) -> int:
        cursor.execute(
            "SELECT count(*) AS n FROM evento_inscritos WHERE id_evento = %s",
            (id_evento,),
        )
        return cursor.fetchone()["n"]

    def agenda_por_cliente(
        self, busqueda=None, id_categoria=None, estado="proximas", agendado_por=None
    ) -> list[dict]:
        """Qué tiene agendado cada cliente, y quién lo inscribió."""
        condiciones, parametros = [], []

        if busqueda:
            condiciones.append(
                "((cl.nombre || ' ' || cl.apellido) ILIKE %s OR cl.cedula LIKE %s)"
            )
            patron = f"%{busqueda}%"
            parametros += [patron, patron]

        if id_categoria:
            condiciones.append("e.id_categoria = %s")
            parametros.append(id_categoria)

        if estado == "proximas":
            condiciones.append("e.fecha >= CURRENT_DATE")
        elif estado == "realizadas":
            condiciones.append("e.fecha < CURRENT_DATE")

        if agendado_por:
            condiciones.append("i.id_empleado = %s")
            parametros.append(agendado_por)

        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT cl.id_cliente,
                       cl.nombre || ' ' || cl.apellido AS cliente_nombre,
                       cl.cedula,
                       cl.id_representante IS NOT NULL AS es_menor,
                       e.id_evento, e.titulo, e.fecha, e.hora_inicio, e.hora_fin,
                       cat.nombre AS categoria_nombre, cat.color AS categoria_color,
                       e.fecha >= CURRENT_DATE AS es_proxima,
                       i.fecha_inscripcion,
                       em.nombre || ' ' || em.apellido AS agendado_por
                  FROM evento_inscritos i
                  JOIN clientes cl ON cl.id_cliente = i.id_cliente
                  JOIN eventos e ON e.id_evento = i.id_evento
                  JOIN categorias_evento cat ON cat.id_categoria = e.id_categoria
                  JOIN empleados em ON em.id_empleado = i.id_empleado
                  {where}
                 ORDER BY cl.nombre, cl.apellido, e.fecha
                """,
                parametros,
            )
            return cursor.fetchall()


# Días de gracia tras vencer una membresía durante los que el cliente
# sigue apareciendo en el calendario. Alguien que venció hace una semana
# todavía va al gimnasio, y felicitarlo es además una oportunidad de
# renovación. Poner 0 deja solo a los que tienen vigencia hoy.
DIAS_GRACIA_CUMPLE = 30


class CumpleanosRepositorio:

    def entre(self, desde: date, hasta: date) -> list[Cumpleanos]:
        """Cumpleaños que caen en el rango.

        Solo de clientes activos: los que tienen membresía vigente o la
        tuvieron hace poco. Sin este filtro el calendario se llena de
        gente que dejó de venir hace meses.

        También salen los cumpleaños de los empleados activos, marcados
        con es_empleado para que el calendario los pinte de otro color.

        Se comparan mes y día, ignorando el año, y se maneja el caso de
        un rango que cruza de diciembre a enero.
        """
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id_cliente,
                       c.nombre || ' ' || c.apellido AS nombre,
                       c.fecha_nacimiento
                  FROM clientes c
                 WHERE c.fecha_nacimiento IS NOT NULL
                   AND EXISTS (
                         SELECT 1 FROM membresias m
                          WHERE m.id_cliente = c.id_cliente
                            AND m.estado = 'ACTIVA'
                            AND m.fecha_fin >= CURRENT_DATE - %s
                       )
                """,
                (DIAS_GRACIA_CUMPLE,),
            )
            filas = [dict(f, es_empleado=False) for f in cursor.fetchall()]

            # Los empleados activos también cumplen años.
            cursor.execute(
                """
                SELECT id_empleado AS id_cliente,
                       nombre || ' ' || apellido AS nombre,
                       fecha_nacimiento
                  FROM empleados
                 WHERE fecha_nacimiento IS NOT NULL
                   AND activo = TRUE
                """
            )
            filas += [dict(f, es_empleado=True) for f in cursor.fetchall()]

        resultado = []
        for fila in filas:
            nacimiento = fila["fecha_nacimiento"]
            # Prueba el cumpleaños en cada año que toque el rango.
            for anio in range(desde.year, hasta.year + 1):
                try:
                    cumple = nacimiento.replace(year=anio)
                except ValueError:
                    # 29 de febrero en un año no bisiesto: se marca el 28.
                    cumple = nacimiento.replace(year=anio, day=28)
                if desde <= cumple <= hasta:
                    edad = anio - nacimiento.year
                    if edad > 0:
                        resultado.append(
                            Cumpleanos(
                                id_cliente=fila["id_cliente"],
                                nombre=fila["nombre"],
                                fecha=cumple,
                                edad=edad,
                                es_empleado=fila["es_empleado"],
                            )
                        )
        return sorted(resultado, key=lambda c: c.fecha)
