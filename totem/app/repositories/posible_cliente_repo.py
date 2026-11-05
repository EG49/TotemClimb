"""Repositorio de posibles clientes: todo el SQL de la tabla.

Un repositorio solo lee y escribe. Las reglas viven en el servicio.
"""

from app.db import obtener_cursor
from app.models.posible_cliente import PosibleCliente

# La fecha de la clase no se guarda aquí: sale de la inscripción al
# evento, para no tener el mismo dato en dos lados y que algún día no
# coincidan.
_CAMPOS = """
    p.id_posible, p.nombre, p.apellido, p.correo, p.telefono,
    p.id_coach, p.id_empleado, p.asistio, p.id_cliente,
    p.fecha_conversion, p.fecha_registro,
    co.nombre || ' ' || co.apellido AS coach_nombre,
    em.nombre || ' ' || em.apellido AS registrado_por,
    ev.fecha AS fecha_clase,
    ev.id_evento
"""

_ORIGEN = """
    FROM posibles_clientes p
    LEFT JOIN empleados co ON co.id_empleado = p.id_coach
    LEFT JOIN empleados em ON em.id_empleado = p.id_empleado
    LEFT JOIN evento_inscritos ei ON ei.id_posible = p.id_posible
    LEFT JOIN eventos ev ON ev.id_evento = ei.id_evento
"""


class PosibleClienteRepositorio:

    def obtener(self, id_posible: int) -> PosibleCliente | None:
        with obtener_cursor() as cursor:
            cursor.execute(
                f"SELECT {_CAMPOS} {_ORIGEN} WHERE p.id_posible = %s",
                (id_posible,),
            )
            fila = cursor.fetchone()
        return PosibleCliente.desde_fila(fila) if fila else None

    def listar(self, estado: str | None = None, id_coach: int | None = None,
               busqueda: str | None = None) -> list[PosibleCliente]:
        """Listado con filtros opcionales por estado, coach y texto."""
        condiciones, parametros = [], []

        if estado == "convertido":
            condiciones.append("p.id_cliente IS NOT NULL")
        elif estado == "asistio":
            condiciones.append("p.asistio IS TRUE AND p.id_cliente IS NULL")
        elif estado == "no_asistio":
            condiciones.append("p.asistio IS FALSE")
        elif estado == "agendado":
            condiciones.append("p.asistio IS NULL AND p.id_cliente IS NULL")

        if id_coach:
            condiciones.append("p.id_coach = %s")
            parametros.append(id_coach)

        if busqueda:
            condiciones.append(
                "(p.nombre ILIKE %s OR p.apellido ILIKE %s OR p.correo ILIKE %s)"
            )
            patron = f"%{busqueda}%"
            parametros += [patron, patron, patron]

        where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""

        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {_CAMPOS} {_ORIGEN} {where}
                ORDER BY COALESCE(ev.fecha, p.fecha_registro::date) DESC,
                         p.id_posible DESC
                """,
                parametros,
            )
            return [PosibleCliente.desde_fila(f) for f in cursor.fetchall()]

    def pendiente_por_correo(self, correo: str) -> PosibleCliente | None:
        """Busca un posible cliente sin convertir con ese correo.

        Es la llave de la conversión. Se busca por correo y no por
        nombre porque el nombre se escribe de mil formas —"Maria" y
        "María" no cruzarían— y el correo es lo único realmente
        distintivo que se pide al agendar.
        """
        if not correo:
            return None
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {_CAMPOS} {_ORIGEN}
                 WHERE lower(p.correo) = lower(%s)
                   AND p.id_cliente IS NULL
                 ORDER BY p.id_posible DESC
                 LIMIT 1
                """,
                (correo.strip(),),
            )
            fila = cursor.fetchone()
        return PosibleCliente.desde_fila(fila) if fila else None

    def crear(self, datos: dict, cursor=None) -> int:
        sql = """
            INSERT INTO posibles_clientes
                (nombre, apellido, correo, telefono, id_coach, id_empleado)
            VALUES (%(nombre)s, %(apellido)s, %(correo)s, %(telefono)s,
                    %(id_coach)s, %(id_empleado)s)
            RETURNING id_posible
        """
        if cursor is not None:
            cursor.execute(sql, datos)
            return cursor.fetchone()["id_posible"]
        with obtener_cursor(commit=True) as c:
            c.execute(sql, datos)
            return c.fetchone()["id_posible"]

    def actualizar(self, id_posible: int, datos: dict) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE posibles_clientes
                   SET nombre = %(nombre)s, apellido = %(apellido)s,
                       correo = %(correo)s, telefono = %(telefono)s,
                       id_coach = %(id_coach)s
                 WHERE id_posible = %(id_posible)s
                """,
                {**datos, "id_posible": id_posible},
            )

    def marcar_asistencia(self, id_posible: int, asistio: bool | None,
                          cursor=None) -> None:
        sql = "UPDATE posibles_clientes SET asistio = %s WHERE id_posible = %s"
        if cursor is not None:
            cursor.execute(sql, (asistio, id_posible))
            return
        with obtener_cursor(commit=True) as c:
            c.execute(sql, (asistio, id_posible))

    def convertir(self, id_posible: int, id_cliente: int, cursor=None) -> None:
        """Lo marca como convertido. Los dos campos van juntos: el
        esquema no admite uno sin el otro."""
        sql = """
            UPDATE posibles_clientes
               SET id_cliente = %s, fecha_conversion = CURRENT_TIMESTAMP
             WHERE id_posible = %s
               AND id_cliente IS NULL
        """
        if cursor is not None:
            cursor.execute(sql, (id_cliente, id_posible))
            return
        with obtener_cursor(commit=True) as c:
            c.execute(sql, (id_cliente, id_posible))

    def deshacer_conversion(self, id_posible: int) -> None:
        """Para cuando el enlace automático se equivocó de persona."""
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE posibles_clientes
                   SET id_cliente = NULL, fecha_conversion = NULL
                 WHERE id_posible = %s
                """,
                (id_posible,),
            )

    def resumen(self) -> dict:
        """Totales para las tarjetas del listado."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE asistio IS NULL
                                          AND id_cliente IS NULL) AS agendados,
                       count(*) FILTER (WHERE asistio IS TRUE)     AS asistieron,
                       count(*) FILTER (WHERE id_cliente IS NOT NULL) AS convertidos
                  FROM posibles_clientes
                """
            )
            return cursor.fetchone()

    def por_coach(self) -> list[dict]:
        """Rendimiento de cada coach, para el reporte de eficiencia.

        Incluye a los coaches sin posibles clientes asignados, para que
        se note que están en cero y no que faltan del listado.
        """
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT e.id_empleado,
                       e.nombre || ' ' || e.apellido AS coach,
                       e.activo,
                       count(p.id_posible) AS asignados,
                       count(*) FILTER (WHERE p.asistio IS TRUE) AS asistieron,
                       count(*) FILTER (WHERE p.id_cliente IS NOT NULL)
                         AS convertidos
                  FROM empleados e
             LEFT JOIN posibles_clientes p ON p.id_coach = e.id_empleado
                 WHERE e.es_coach = TRUE
              GROUP BY e.id_empleado, coach, e.activo
              ORDER BY convertidos DESC, asignados DESC, coach
                """
            )
            return cursor.fetchall()
