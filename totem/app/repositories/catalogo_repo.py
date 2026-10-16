"""Repositorios de productos y planes de membresía."""

from app.db import obtener_cursor
from app.models.catalogo import PlanMembresia, Producto


class ProductoRepositorio:

    def listar(self, incluir_inactivos: bool = False) -> list[Producto]:
        where = "" if incluir_inactivos else "WHERE activo = TRUE"
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id_producto, nombre, precio, activo
                  FROM productos
                  {where}
                 ORDER BY activo DESC, nombre
                """
            )
            return [Producto.desde_fila(f) for f in cursor.fetchall()]

    def obtener(self, id_producto: int) -> Producto | None:
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT id_producto, nombre, precio, activo "
                "FROM productos WHERE id_producto = %s",
                (id_producto,),
            )
            fila = cursor.fetchone()
        return Producto.desde_fila(fila) if fila else None

    def nombre_ocupado(self, nombre: str, excluir_id: int | None = None) -> bool:
        with obtener_cursor() as cursor:
            if excluir_id:
                cursor.execute(
                    "SELECT 1 FROM productos WHERE lower(nombre) = lower(%s) "
                    "AND id_producto <> %s",
                    (nombre, excluir_id),
                )
            else:
                cursor.execute(
                    "SELECT 1 FROM productos WHERE lower(nombre) = lower(%s)",
                    (nombre,),
                )
            return cursor.fetchone() is not None

    def crear(self, datos: dict) -> int:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "INSERT INTO productos (nombre, precio) VALUES (%s, %s) "
                "RETURNING id_producto",
                (datos["nombre"], datos["precio"]),
            )
            return cursor.fetchone()["id_producto"]

    def actualizar(self, id_producto: int, datos: dict) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE productos SET nombre = %s, precio = %s WHERE id_producto = %s",
                (datos["nombre"], datos["precio"], id_producto),
            )

    def cambiar_estado(self, id_producto: int, activo: bool) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE productos SET activo = %s WHERE id_producto = %s",
                (activo, id_producto),
            )

    def esta_en_uso(self, id_producto: int) -> bool:
        """Indica si el producto ya aparece en alguna factura."""
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM detalle_factura WHERE id_producto = %s LIMIT 1",
                (id_producto,),
            )
            return cursor.fetchone() is not None


CAMPOS_PLAN = (
    "nombre",
    "tipo",
    "precio",
    "duracion",
    "unidad_duracion",
    "dias_incluidos",
    "permite_pareja",
    "permite_descuento",
)


class PlanRepositorio:

    def listar(self, incluir_inactivos: bool = False) -> list[PlanMembresia]:
        where = "" if incluir_inactivos else "WHERE activo = TRUE"
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id_plan, nombre, tipo, precio, duracion, unidad_duracion,
                       dias_incluidos, permite_pareja, permite_descuento, activo
                  FROM planes_membresia
                  {where}
                 ORDER BY activo DESC, precio
                """
            )
            return [PlanMembresia.desde_fila(f) for f in cursor.fetchall()]

    def obtener(self, id_plan: int) -> PlanMembresia | None:
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT id_plan, nombre, tipo, precio, duracion, unidad_duracion,
                       dias_incluidos, permite_pareja, permite_descuento, activo
                  FROM planes_membresia WHERE id_plan = %s
                """,
                (id_plan,),
            )
            fila = cursor.fetchone()
        return PlanMembresia.desde_fila(fila) if fila else None

    def nombre_ocupado(self, nombre: str, excluir_id: int | None = None) -> bool:
        with obtener_cursor() as cursor:
            if excluir_id:
                cursor.execute(
                    "SELECT 1 FROM planes_membresia WHERE lower(nombre) = lower(%s) "
                    "AND id_plan <> %s",
                    (nombre, excluir_id),
                )
            else:
                cursor.execute(
                    "SELECT 1 FROM planes_membresia WHERE lower(nombre) = lower(%s)",
                    (nombre,),
                )
            return cursor.fetchone() is not None

    def crear(self, datos: dict) -> int:
        marcadores = ", ".join(["%s"] * len(CAMPOS_PLAN))
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                f"""
                INSERT INTO planes_membresia ({", ".join(CAMPOS_PLAN)})
                VALUES ({marcadores}) RETURNING id_plan
                """,
                [datos[c] for c in CAMPOS_PLAN],
            )
            return cursor.fetchone()["id_plan"]

    def actualizar(self, id_plan: int, datos: dict) -> None:
        asignaciones = ", ".join(f"{c} = %s" for c in CAMPOS_PLAN)
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                f"UPDATE planes_membresia SET {asignaciones} WHERE id_plan = %s",
                [datos[c] for c in CAMPOS_PLAN] + [id_plan],
            )

    def cambiar_estado(self, id_plan: int, activo: bool) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE planes_membresia SET activo = %s WHERE id_plan = %s",
                (activo, id_plan),
            )

    def esta_en_uso(self, id_plan: int) -> bool:
        """Indica si ya se vendió alguna membresía con este plan."""
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM membresias WHERE id_plan = %s LIMIT 1", (id_plan,)
            )
            return cursor.fetchone() is not None
