"""Repositorio de la bitácora (trazabilidad para el ADMIN)."""

import json

from app.db import obtener_cursor


class BitacoraRepositorio:

    def registrar(
        self,
        id_empleado: int,
        accion: str,
        entidad: str,
        id_entidad: int | None = None,
        detalle: dict | None = None,
    ) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO bitacora (id_empleado, accion, entidad, id_entidad, detalle)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    id_empleado,
                    accion,
                    entidad,
                    id_entidad,
                    json.dumps(detalle) if detalle else None,
                ),
            )

    def listar(
        self,
        id_empleado: int | None = None,
        accion: str | None = None,
        limite: int = 100,
    ) -> list[dict]:
        """Listado para la vista del ADMIN, con el nombre del empleado."""
        condiciones, parametros = [], []
        if id_empleado is not None:
            condiciones.append("b.id_empleado = %s")
            parametros.append(id_empleado)
        if accion:
            condiciones.append("b.accion = %s")
            parametros.append(accion)

        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
        parametros.append(limite)

        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT b.id_bitacora, b.accion, b.entidad, b.id_entidad,
                       b.detalle, b.fecha,
                       e.nombre || ' ' || e.apellido AS empleado
                  FROM bitacora b
                  JOIN empleados e ON e.id_empleado = b.id_empleado
                  {where}
                 ORDER BY b.fecha DESC
                 LIMIT %s
                """,
                parametros,
            )
            return cursor.fetchall()
