"""Acceso a PostgreSQL mediante un pool de conexiones.

Esta es la única pieza del sistema que sabe cómo se habla con la base de
datos. Los repositorios la usan; los servicios y las vistas no la tocan.
"""

from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def init_pool(dsn: str, min_size: int = 1, max_size: int = 5) -> None:
    """Crea el pool de conexiones. Se llama una vez, al arrancar la app."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=True,
        )


def cerrar_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def obtener_cursor(commit: bool = False):
    """Entrega un cursor dentro de una transacción.

    Con commit=True la transacción se confirma al salir sin error; si algo
    falla, psycopg hace rollback automáticamente al cerrar el contexto.
    """
    if _pool is None:
        raise RuntimeError("El pool no está inicializado. Llama a init_pool() primero.")

    with _pool.connection() as conexion:
        with conexion.cursor() as cursor:
            yield cursor
        if commit:
            conexion.commit()
        else:
            conexion.rollback()
