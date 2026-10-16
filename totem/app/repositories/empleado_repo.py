"""Repositorio de empleados: todas las consultas SQL sobre la tabla.

Un repositorio solo lee y escribe. No decide nada de negocio: eso vive en
los servicios.
"""

from app.db import obtener_cursor
from app.models.empleado import Empleado

_CAMPOS = """
    id_empleado, nombre, apellido, usuario, rol, activo,
    fecha_nacimiento, fecha_registro
"""


class EmpleadoRepositorio:

    def buscar_por_usuario(self, usuario: str) -> Empleado | None:
        """Busca por nombre de usuario. Incluye el hash, porque lo usa
        el servicio de autenticación."""
        with obtener_cursor() as cursor:
            cursor.execute(
                f"SELECT {_CAMPOS}, password_hash FROM empleados WHERE usuario = %s",
                (usuario,),
            )
            fila = cursor.fetchone()
        return Empleado.desde_fila(fila) if fila else None

    def obtener(self, id_empleado: int) -> Empleado | None:
        """Obtiene un empleado por su id, sin el hash."""
        with obtener_cursor() as cursor:
            cursor.execute(
                f"SELECT {_CAMPOS} FROM empleados WHERE id_empleado = %s",
                (id_empleado,),
            )
            fila = cursor.fetchone()
        return Empleado.desde_fila(fila) if fila else None

    def listar(self, incluir_inactivos: bool = True) -> list[Empleado]:
        where = "" if incluir_inactivos else "WHERE activo = TRUE"
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {_CAMPOS} FROM empleados
                {where}
                ORDER BY activo DESC, rol, nombre, apellido
                """
            )
            return [Empleado.desde_fila(f) for f in cursor.fetchall()]

    def listar_activos(self) -> list[Empleado]:
        return self.listar(incluir_inactivos=False)

    def usuario_ocupado(self, usuario: str, excluir_id: int | None = None) -> bool:
        with obtener_cursor() as cursor:
            if excluir_id:
                cursor.execute(
                    "SELECT 1 FROM empleados WHERE lower(usuario) = lower(%s) "
                    "AND id_empleado <> %s",
                    (usuario, excluir_id),
                )
            else:
                cursor.execute(
                    "SELECT 1 FROM empleados WHERE lower(usuario) = lower(%s)",
                    (usuario,),
                )
            return cursor.fetchone() is not None

    def contar_admins_activos(self, excluir_id: int | None = None) -> int:
        """Cuántos administradores activos quedan.

        Lo usa el servicio para no dejar el sistema sin nadie que pueda
        administrarlo.
        """
        with obtener_cursor() as cursor:
            if excluir_id:
                cursor.execute(
                    "SELECT count(*) AS n FROM empleados "
                    "WHERE rol = 'ADMIN' AND activo = TRUE AND id_empleado <> %s",
                    (excluir_id,),
                )
            else:
                cursor.execute(
                    "SELECT count(*) AS n FROM empleados "
                    "WHERE rol = 'ADMIN' AND activo = TRUE"
                )
            return cursor.fetchone()["n"]

    def crear(self, datos: dict) -> int:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO empleados
                    (nombre, apellido, usuario, password_hash, rol, fecha_nacimiento)
                VALUES (%(nombre)s, %(apellido)s, %(usuario)s, %(password_hash)s,
                        %(rol)s, %(fecha_nacimiento)s)
                RETURNING id_empleado
                """,
                datos,
            )
            return cursor.fetchone()["id_empleado"]

    def actualizar(self, id_empleado: int, datos: dict) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE empleados
                   SET nombre = %(nombre)s, apellido = %(apellido)s,
                       usuario = %(usuario)s, rol = %(rol)s,
                       fecha_nacimiento = %(fecha_nacimiento)s
                 WHERE id_empleado = %(id_empleado)s
                """,
                {**datos, "id_empleado": id_empleado},
            )

    def actualizar_password(self, id_empleado: int, password_hash: str) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE empleados SET password_hash = %s WHERE id_empleado = %s",
                (password_hash, id_empleado),
            )

    def cambiar_estado(self, id_empleado: int, activo: bool) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE empleados SET activo = %s WHERE id_empleado = %s",
                (activo, id_empleado),
            )

    def actividad(self, id_empleado: int) -> dict:
        """Resumen de lo que hizo un empleado, para su ficha."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  (SELECT count(*) FROM facturas WHERE id_empleado = %(id)s)
                    AS facturas,
                  (SELECT COALESCE(SUM(total), 0) FROM facturas
                    WHERE id_empleado = %(id)s AND estado = 'EMITIDA') AS facturado,
                  (SELECT count(*) FROM pagos_fiado WHERE id_empleado = %(id)s)
                    AS abonos,
                  (SELECT count(*) FROM evento_inscritos WHERE id_empleado = %(id)s)
                    AS inscripciones,
                  (SELECT max(fecha) FROM bitacora WHERE id_empleado = %(id)s)
                    AS ultima_accion
                """,
                {"id": id_empleado},
            )
            return cursor.fetchone()
