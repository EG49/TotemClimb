"""Servicio de empleados: alta, edición y baja de usuarios del sistema.

Reglas de seguridad que viven aquí, para que nadie deje el sistema
inutilizable sin querer:

  * Un empleado nunca se borra. Se desactiva: deja de poder entrar, pero
    sus facturas y su rastro en la bitácora siguen diciendo quién fue.
  * Nadie puede desactivarse a sí mismo ni quitarse el rol de
    administrador: se quedaría fuera en mitad de la sesión.
  * Siempre tiene que quedar al menos un administrador activo.
"""

from datetime import date, datetime

from app.models.empleado import ROL_ADMIN, ROL_VENDEDOR, Empleado
from app.repositories.empleado_repo import EmpleadoRepositorio
from app.services import bitacora_service as bit
from app.services.auth_service import generar_hash
from app.services.bitacora_service import BitacoraService
from app.services.validaciones import (
    ErrorValidacion,
    limpiar,
    validar_fecha_nacimiento,
)

ROLES = (ROL_ADMIN, ROL_VENDEDOR)
LARGO_MINIMO_PASSWORD = 8
LARGO_MINIMO_USUARIO = 3


class EmpleadoService:

    def __init__(self, repositorio=None, bitacora=None):
        self.repositorio = repositorio or EmpleadoRepositorio()
        self.bitacora = bitacora or BitacoraService()

    # --- Consultas ----------------------------------------------------

    def listar(self, incluir_inactivos=True) -> list[Empleado]:
        return self.repositorio.listar(incluir_inactivos)

    def obtener(self, id_empleado: int) -> Empleado | None:
        return self.repositorio.obtener(id_empleado)

    def actividad(self, id_empleado: int) -> dict:
        return self.repositorio.actividad(id_empleado)

    # --- Validación ---------------------------------------------------

    def _normalizar(self, formulario: dict) -> dict:
        fecha = limpiar(formulario.get("fecha_nacimiento"))
        if fecha:
            try:
                fecha = datetime.strptime(fecha, "%Y-%m-%d").date()
            except ValueError:
                fecha = "__invalida__"

        return {
            "nombre": limpiar(formulario.get("nombre")),
            "apellido": limpiar(formulario.get("apellido")),
            "usuario": (limpiar(formulario.get("usuario")) or "").lower() or None,
            "rol": limpiar(formulario.get("rol")) or ROL_VENDEDOR,
            "fecha_nacimiento": fecha or None,
        }

    def _validar(self, datos: dict, excluir_id=None) -> dict[str, str]:
        errores = {}

        if not datos.get("nombre"):
            errores["nombre"] = "El nombre es obligatorio."
        if not datos.get("apellido"):
            errores["apellido"] = "El apellido es obligatorio."

        usuario = datos.get("usuario")
        if not usuario:
            errores["usuario"] = "El usuario es obligatorio."
        elif len(usuario) < LARGO_MINIMO_USUARIO:
            errores["usuario"] = (
                f"El usuario debe tener al menos {LARGO_MINIMO_USUARIO} caracteres."
            )
        elif not usuario.replace(".", "").replace("_", "").isalnum():
            errores["usuario"] = (
                "El usuario solo puede llevar letras, números, punto y guion bajo."
            )
        elif self.repositorio.usuario_ocupado(usuario, excluir_id):
            errores["usuario"] = "Ese usuario ya existe."

        if datos.get("rol") not in ROLES:
            errores["rol"] = "Selecciona un rol válido."

        fecha = datos.get("fecha_nacimiento")
        if fecha == "__invalida__":
            errores["fecha_nacimiento"] = "La fecha no tiene un formato válido."
        elif isinstance(fecha, date):
            problema = validar_fecha_nacimiento(fecha)
            if problema:
                errores["fecha_nacimiento"] = problema

        return errores

    def _validar_password(self, password: str, repetida: str) -> dict[str, str]:
        if not password:
            return {"password": "Escribe una contraseña."}
        if len(password) < LARGO_MINIMO_PASSWORD:
            return {
                "password": (
                    f"La contraseña debe tener al menos "
                    f"{LARGO_MINIMO_PASSWORD} caracteres."
                )
            }
        if password != repetida:
            return {"password_repetida": "Las contraseñas no coinciden."}
        return {}

    # --- Operaciones --------------------------------------------------

    def crear(self, formulario: dict, id_empleado_actual: int) -> int:
        datos = self._normalizar(formulario)
        errores = self._validar(datos)
        errores.update(
            self._validar_password(
                formulario.get("password", ""), formulario.get("password_repetida", "")
            )
        )
        if errores:
            raise ErrorValidacion(errores)

        datos["password_hash"] = generar_hash(formulario["password"])
        nuevo = self.repositorio.crear(datos)

        self.bitacora.registrar(
            id_empleado_actual,
            bit.EMPLEADO_CREADO,
            bit.EMPLEADO,
            nuevo,
            {
                "usuario": datos["usuario"],
                "nombre": f"{datos['nombre']} {datos['apellido']}",
                "rol": datos["rol"],
            },
        )
        return nuevo

    def actualizar(
        self, id_empleado: int, formulario: dict, id_empleado_actual: int
    ) -> None:
        actual = self.repositorio.obtener(id_empleado)
        if actual is None:
            raise ValueError("El empleado no existe.")

        datos = self._normalizar(formulario)
        errores = self._validar(datos, excluir_id=id_empleado)

        # Quitarse a uno mismo el rol de administrador deja al sistema
        # sin quien lo administre, o al menos deja fuera a quien lo hizo.
        if (
            id_empleado == id_empleado_actual
            and actual.es_admin
            and datos["rol"] != ROL_ADMIN
        ):
            errores["rol"] = (
                "No puedes quitarte a ti mismo el rol de administrador. "
                "Pídeselo a otro administrador."
            )
        elif (
            actual.es_admin
            and datos["rol"] != ROL_ADMIN
            and self.repositorio.contar_admins_activos(excluir_id=id_empleado) == 0
        ):
            errores["rol"] = (
                "Es el único administrador activo. Nombra a otro antes de "
                "cambiarle el rol."
            )

        if errores:
            raise ErrorValidacion(errores)

        cambios = {}
        for campo in ("nombre", "apellido", "usuario", "rol", "fecha_nacimiento"):
            antes, despues = getattr(actual, campo), datos[campo]
            if isinstance(antes, date):
                antes = antes.isoformat()
            if isinstance(despues, date):
                despues = despues.isoformat()
            if antes != despues:
                cambios[campo] = {"antes": antes, "despues": despues}

        self.repositorio.actualizar(id_empleado, datos)

        if cambios:
            self.bitacora.registrar(
                id_empleado_actual,
                bit.EMPLEADO_EDITADO,
                bit.EMPLEADO,
                id_empleado,
                {"usuario": datos["usuario"], "cambios": cambios},
            )

    def cambiar_password(
        self, id_empleado: int, formulario: dict, id_empleado_actual: int
    ) -> None:
        empleado = self.repositorio.obtener(id_empleado)
        if empleado is None:
            raise ValueError("El empleado no existe.")

        errores = self._validar_password(
            formulario.get("password", ""), formulario.get("password_repetida", "")
        )
        if errores:
            raise ErrorValidacion(errores)

        self.repositorio.actualizar_password(
            id_empleado, generar_hash(formulario["password"])
        )
        self.bitacora.registrar(
            id_empleado_actual,
            bit.PASSWORD_CAMBIADA,
            bit.EMPLEADO,
            id_empleado,
            {
                "usuario": empleado.usuario,
                "propia": id_empleado == id_empleado_actual,
            },
        )

    def cambiar_estado(
        self, id_empleado: int, activo: bool, id_empleado_actual: int
    ) -> None:
        empleado = self.repositorio.obtener(id_empleado)
        if empleado is None:
            raise ValueError("El empleado no existe.")

        if not activo:
            if id_empleado == id_empleado_actual:
                raise ErrorValidacion(
                    {
                        "general": (
                            "No puedes desactivarte a ti mismo: perderías el "
                            "acceso en este momento."
                        )
                    }
                )
            if (
                empleado.es_admin
                and self.repositorio.contar_admins_activos(excluir_id=id_empleado) == 0
            ):
                raise ErrorValidacion(
                    {
                        "general": (
                            "Es el único administrador activo. Nombra a otro "
                            "antes de desactivarlo."
                        )
                    }
                )

        self.repositorio.cambiar_estado(id_empleado, activo)
        self.bitacora.registrar(
            id_empleado_actual,
            bit.EMPLEADO_REACTIVADO if activo else bit.EMPLEADO_DESACTIVADO,
            bit.EMPLEADO,
            id_empleado,
            {"usuario": empleado.usuario, "nombre": empleado.nombre_completo},
        )
