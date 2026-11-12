"""Servicio de clientes: validaciones y reglas de negocio.

Reglas que viven aquí:
  * La cédula es opcional, pero si se da debe ser válida y no estar
    repetida.
  * Un menor a cargo se crea como cliente ligado a su representante, en
    la misma transacción que este.
  * Toda alta y edición queda registrada en la bitácora.
"""

from datetime import date, datetime

from app.db import obtener_cursor
from app.models.cliente import Cliente
from app.repositories.cliente_repo import ClienteRepositorio
from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService
from app.services.validaciones import (
    ErrorValidacion,
    limpiar,
    solo_digitos,
    validar_cedula,
    validar_celular,
    validar_correo,
    validar_fecha_nacimiento,
)

GENEROS = ("MASCULINO", "FEMENINO", "OTRO")

# Campos que se comparan para anotar qué cambió en una edición.
CAMPOS_AUDITABLES = (
    "nombre",
    "apellido",
    "cedula",
    "fecha_nacimiento",
    "correo",
    "telefono",
    "genero",
    "contacto_emergencia",
    "referencia",
    "seguro_nombre",
    "seguro_numero",
    "id_representante",
)


class ClienteService:

    def __init__(
        self,
        repositorio: ClienteRepositorio | None = None,
        bitacora: BitacoraService | None = None,
    ):
        self.repositorio = repositorio or ClienteRepositorio()
        self.bitacora = bitacora or BitacoraService()

    # --- Validación ---------------------------------------------------

    def _normalizar(self, datos: dict, prefijo: str = "") -> dict:
        """Limpia el formulario y lo deja listo para guardar."""
        def campo(nombre):
            return limpiar(datos.get(prefijo + nombre))

        normalizado = {
            "nombre": campo("nombre"),
            "apellido": campo("apellido"),
            "cedula": solo_digitos(campo("cedula") or "") or None,
            "fecha_nacimiento": campo("fecha_nacimiento"),
            "correo": (campo("correo") or "").lower() or None,
            "telefono": solo_digitos(campo("telefono") or "") or None,
            "genero": campo("genero"),
            "contacto_emergencia": solo_digitos(campo("contacto_emergencia") or "")
            or None,
            "referencia": campo("referencia"),
            "seguro_nombre": campo("seguro_nombre"),
            "seguro_numero": campo("seguro_numero"),
        }

        fecha = normalizado["fecha_nacimiento"]
        if isinstance(fecha, str) and fecha:
            try:
                normalizado["fecha_nacimiento"] = datetime.strptime(
                    fecha, "%Y-%m-%d"
                ).date()
            except ValueError:
                normalizado["fecha_nacimiento"] = "__invalida__"

        return normalizado

    def _validar(
        self,
        datos: dict,
        excluir_id: int | None = None,
        es_menor: bool = False,
    ) -> dict[str, str]:
        errores: dict[str, str] = {}

        if not datos.get("nombre"):
            errores["nombre"] = "El nombre es obligatorio."
        if not datos.get("apellido"):
            errores["apellido"] = "El apellido es obligatorio."

        fecha = datos.get("fecha_nacimiento")
        if fecha == "__invalida__":
            errores["fecha_nacimiento"] = "La fecha no tiene un formato válido."
        elif isinstance(fecha, date):
            problema = validar_fecha_nacimiento(fecha)
            if problema:
                errores["fecha_nacimiento"] = problema

        cedula = datos.get("cedula")
        if cedula:
            if not validar_cedula(cedula):
                errores["cedula"] = (
                    "La cédula no es válida. Revisa que tenga 10 dígitos "
                    "y esté bien escrita."
                )
            elif self.repositorio.cedula_ocupada(cedula, excluir_id):
                errores["cedula"] = "Ya existe un cliente con esa cédula."

        correo = datos.get("correo")
        if correo and not validar_correo(correo):
            errores["correo"] = "El correo no tiene un formato válido."

        telefono = datos.get("telefono")
        if telefono and not validar_celular(telefono):
            errores["telefono"] = "El celular debe tener 10 dígitos y empezar en 09."

        contacto = datos.get("contacto_emergencia")
        if contacto and not validar_celular(contacto):
            errores["contacto_emergencia"] = (
                "El celular del contacto debe tener 10 dígitos y empezar en 09."
            )

        genero = datos.get("genero")
        if genero and genero not in GENEROS:
            errores["genero"] = "Selecciona una opción válida."

        # A un titular se le pide forma de contacto; a un menor no, porque
        # se contacta a través de su representante.
        if not es_menor and not datos.get("telefono") and not datos.get("correo"):
            errores["telefono"] = "Registra al menos un celular o un correo."

        return errores

    # --- Operaciones --------------------------------------------------

    def crear(
        self,
        datos_formulario: dict,
        menores: list[dict],
        id_empleado: int,
    ) -> int:
        """Da de alta un cliente y, si los hay, sus menores a cargo.

        Todo ocurre en una sola transacción: si falla un menor, no queda
        el representante a medias.
        """
        titular = self._normalizar(datos_formulario)
        errores = self._validar(titular)

        menores_normalizados = []
        for indice, menor in enumerate(menores):
            datos_menor = self._normalizar(menor)
            if not datos_menor["nombre"] and not datos_menor["apellido"]:
                continue  # tarjeta vacía: se ignora
            for campo, mensaje in self._validar(datos_menor, es_menor=True).items():
                errores[f"menor_{indice}_{campo}"] = mensaje
            menores_normalizados.append(datos_menor)

        if errores:
            raise ErrorValidacion(errores)

        with obtener_cursor(commit=True) as cursor:
            id_cliente = self.repositorio.crear(titular, cursor=cursor)
            for datos_menor in menores_normalizados:
                datos_menor["id_representante"] = id_cliente
                self.repositorio.crear(datos_menor, cursor=cursor)

        self.bitacora.registrar(
            id_empleado,
            bit.CLIENTE_CREADO,
            bit.CLIENTE,
            id_cliente,
            {
                "nombre": titular["nombre"] + " " + titular["apellido"],
                "menores_registrados": len(menores_normalizados),
            },
        )
        return id_cliente

    def actualizar(
        self, id_cliente: int, datos_formulario: dict, id_empleado: int
    ) -> None:
        actual = self.repositorio.obtener(id_cliente)
        if actual is None:
            raise ValueError("El cliente no existe.")

        datos = self._normalizar(datos_formulario)
        es_menor = actual.tiene_representante
        errores = self._validar(datos, excluir_id=id_cliente, es_menor=es_menor)
        if errores:
            raise ErrorValidacion(errores)

        cambios = self._diferencias(actual, datos)
        self.repositorio.actualizar(id_cliente, datos)

        if cambios:
            self.bitacora.registrar(
                id_empleado,
                bit.CLIENTE_EDITADO,
                bit.CLIENTE,
                id_cliente,
                {"cambios": cambios},
            )

    def quitar_representante(self, id_cliente: int, id_empleado: int) -> None:
        """Desliga a un cliente de su representante.

        Se usa cuando un menor cumple 18 y pasa a ser titular por su
        cuenta. Es poco frecuente y vive en el perfil del propio menor.
        """
        actual = self.repositorio.obtener(id_cliente)
        if actual is None:
            raise ValueError("El cliente no existe.")
        if not actual.tiene_representante:
            return

        self.repositorio.actualizar(id_cliente, {"id_representante": None})
        self.bitacora.registrar(
            id_empleado,
            bit.CLIENTE_EDITADO,
            bit.CLIENTE,
            id_cliente,
            {
                "cambios": {
                    "id_representante": {
                        "antes": actual.representante_nombre,
                        "despues": None,
                    }
                },
                "motivo": "Quitar representante (mayoría de edad)",
            },
        )

    def _diferencias(self, actual: Cliente, nuevos: dict) -> dict:
        """Compara el estado anterior con el nuevo, para la bitácora."""
        cambios = {}
        for campo in CAMPOS_AUDITABLES:
            if campo not in nuevos:
                continue
            antes, despues = getattr(actual, campo, None), nuevos[campo]
            if isinstance(antes, date):
                antes = antes.isoformat()
            if isinstance(despues, date):
                despues = despues.isoformat()
            if antes != despues:
                cambios[campo] = {"antes": antes, "despues": despues}
        return cambios

    # --- Consultas ----------------------------------------------------

    def listar(self, busqueda=None, filtro="todos", pagina=1, por_pagina=20):
        clientes = self.repositorio.listar(busqueda, filtro, pagina, por_pagina)
        total = self.repositorio.contar(busqueda, filtro)
        return clientes, total

    def obtener(self, id_cliente: int) -> Cliente | None:
        return self.repositorio.obtener(id_cliente)

    def menores_de(self, id_representante: int) -> list[Cliente]:
        return self.repositorio.menores_de(id_representante)

    def conteos(self) -> dict[str, int]:
        return self.repositorio.contar_por_filtro()
