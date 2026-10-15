"""Repositorio de empleados: todas las consultas SQL sobre la tabla.

Un repositorio solo lee y escribe. No decide nada de negocio: eso vive en
los servicios.
"""

from app.db import obtener_cursor
from app.models.empleado import Empleado


class EmpleadoRepositorio:

    def buscar_por_usuario(self, usuario: str) -> Empleado | None:
        """Busca por nombre de usuario. Incluye el hash, porque lo usa
        el servicio de autenticación."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT id_empleado, nombre, apellido, usuario, password_hash,
                       rol, activo, fecha_registro
                  FROM empleados
                 WHERE usuario = %s
                """,
                (usuario,),
            )
            fila = cursor.fetchone()
        return Empleado.desde_fila(fila) if fila else None

    def obtener(self, id_empleado: int) -> Empleado | None:
        """Obtiene un empleado por su id, sin el hash."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT id_empleado, nombre, apellido, usuario,
                       rol, activo, fecha_registro
                  FROM empleados
                 WHERE id_empleado = %s
                """,
                (id_empleado,),
            )
            fila = cursor.fetchone()
        return Empleado.desde_fila(fila) if fila else None

    def listar_activos(self) -> list[Empleado]:
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT id_empleado, nombre, apellido, usuario,
                       rol, activo, fecha_registro
                  FROM empleados
                 WHERE activo = TRUE
                 ORDER BY nombre, apellido
                """
            )
            filas = cursor.fetchall()
        return [Empleado.desde_fila(f) for f in filas]

    def actualizar_password(self, id_empleado: int, password_hash: str) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE empleados SET password_hash = %s WHERE id_empleado = %s",
                (password_hash, id_empleado),
            )
