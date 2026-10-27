"""Servicio de autenticación.

Aquí vive la regla de negocio: qué significa que alguien pueda entrar.
El hash de contraseñas se maneja con bcrypt y nunca sale de este módulo.
"""

import bcrypt

from app.models.empleado import Empleado
from app.repositories.empleado_repo import EmpleadoRepositorio


class CredencialesInvalidas(Exception):
    """Usuario inexistente o contraseña incorrecta."""


class EmpleadoInactivo(Exception):
    """El empleado existe pero está dado de baja."""


def generar_hash(password: str) -> str:
    """Genera el hash bcrypt de una contraseña en texto plano."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_password(password: str, password_hash: str) -> bool:
    """Compara una contraseña contra su hash.

    Devuelve False en vez de reventar si el hash guardado no tiene formato
    bcrypt válido, que es el caso del marcador que deja el script SQL
    inicial.
    """
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


class AuthService:

    def __init__(self, repositorio: EmpleadoRepositorio | None = None):
        self.repositorio = repositorio or EmpleadoRepositorio()

    def autenticar(self, usuario: str, password: str) -> Empleado:
        """Valida credenciales y devuelve el empleado.

        Lanza CredencialesInvalidas o EmpleadoInactivo según el caso. La
        vista muestra el mismo mensaje genérico para el primero, para no
        revelar si el usuario existe.
        """
        empleado = self.repositorio.buscar_por_usuario(usuario.strip())

        if empleado is None:
            # Gastamos el mismo tiempo que una verificación real, para que
            # no se pueda deducir qué usuarios existen midiendo la demora.
            verificar_password(password, _HASH_SEÑUELO)
            raise CredencialesInvalidas()

        if not verificar_password(password, empleado.password_hash or ""):
            raise CredencialesInvalidas()

        if not empleado.activo:
            raise EmpleadoInactivo()

        # El hash no viaja más allá de este punto.
        empleado.password_hash = None
        return empleado

    def cambiar_password(self, id_empleado: int, password_nueva: str) -> None:
        self.repositorio.actualizar_password(id_empleado, generar_hash(password_nueva))


# Hash fijo de una contraseña cualquiera, usado solo para igualar tiempos.
_HASH_SEÑUELO = "$2b$12$Cq8pTJ0mYy1u0J8Qk0Z0h.0cYxYgqKQ0t9m1b1pZ8s6Yl1wYy0Zq2"
