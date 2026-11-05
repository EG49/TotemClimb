"""Servicio de posibles clientes: quienes vienen a una clase de prueba.

Reglas que viven aquí:

  * El correo es obligatorio. No es burocracia: es la llave con la que
    después se detecta que esa persona se inscribió, y sin él la
    conversión no se puede medir.
  * Alta y agendamiento ocurren juntos o no ocurren. Un posible cliente
    sin clase agendada no sirve de nada, así que van en una sola
    transacción.
  * El coach es opcional al agendar y se puede asignar después.
  * La conversión se marca cuando paga su primera membresía, no cuando
    se le crea la ficha de cliente: es cuando entra el dinero.
"""

from datetime import date, datetime, time

from app.db import obtener_cursor
from app.models.posible_cliente import PosibleCliente
from app.repositories.evento_repo import (
    EventoRepositorio,
    InscripcionRepositorio,
)
from app.repositories.posible_cliente_repo import PosibleClienteRepositorio
from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService
from app.services.validaciones import (
    ErrorValidacion,
    limpiar,
    solo_digitos,
    validar_celular,
    validar_correo,
)

# Categoría del calendario bajo la que se agendan las clases de prueba.
CATEGORIA_CLASE_PRUEBA = "Clase de prueba"

# Si no se dice otra cosa, la clase dura una hora.
DURACION_CLASE_HORAS = 1


class PosibleClienteService:

    def __init__(self):
        self.repositorio = PosibleClienteRepositorio()
        self.eventos = EventoRepositorio()
        self.inscripciones = InscripcionRepositorio()
        self.bitacora = BitacoraService()

    # --- Consultas ----------------------------------------------------

    def listar(self, estado=None, id_coach=None, busqueda=None) -> list[PosibleCliente]:
        return self.repositorio.listar(estado, id_coach, busqueda)

    def obtener(self, id_posible: int) -> PosibleCliente | None:
        return self.repositorio.obtener(id_posible)

    def resumen(self) -> dict:
        return self.repositorio.resumen()

    def por_coach(self) -> list[dict]:
        """Rendimiento de cada coach, con su tasa de conversión."""
        filas = self.repositorio.por_coach()
        for f in filas:
            asignados = f["asignados"] or 0
            f["tasa"] = (
                round(f["convertidos"] / asignados * 100, 1) if asignados else 0.0
            )
            f["tasa_asistencia"] = (
                round(f["asistieron"] / asignados * 100, 1) if asignados else 0.0
            )
        return filas

    # --- Validación ---------------------------------------------------

    def _normalizar(self, formulario: dict) -> dict:
        return {
            "nombre": limpiar(formulario.get("nombre")),
            "apellido": limpiar(formulario.get("apellido")),
            "correo": (limpiar(formulario.get("correo")) or "").lower() or None,
            "telefono": solo_digitos(formulario.get("telefono")) or None,
            "id_coach": _a_entero(formulario.get("id_coach")),
        }

    def _validar(self, datos: dict) -> dict[str, str]:
        errores = {}

        if not datos.get("nombre"):
            errores["nombre"] = "El nombre es obligatorio."
        if not datos.get("apellido"):
            errores["apellido"] = "El apellido es obligatorio."

        correo = datos.get("correo")
        if not correo:
            errores["correo"] = (
                "El correo es obligatorio: es con lo que después se sabe "
                "si esta persona se inscribió."
            )
        elif not validar_correo(correo):
            errores["correo"] = "Ese correo no tiene un formato válido."

        if datos.get("telefono") and not validar_celular(datos["telefono"]):
            errores["telefono"] = "El celular debe tener 10 dígitos y empezar en 09."

        return errores

    # --- Operaciones --------------------------------------------------

    def agendar(self, formulario: dict, id_empleado: int) -> int:
        """Da de alta al posible cliente y le agenda la clase de prueba.

        Las dos cosas van en la misma transacción: si falla el
        agendamiento no queda una ficha suelta sin clase.
        """
        datos = self._normalizar(formulario)
        errores = self._validar(datos)

        fecha_texto = limpiar(formulario.get("fecha"))
        hora_texto = limpiar(formulario.get("hora_inicio")) or "10:00"
        fecha = _a_fecha(fecha_texto)
        hora = _a_hora(hora_texto)

        if fecha is None:
            errores["fecha"] = "Indica el día de la clase."
        elif fecha < date.today():
            errores["fecha"] = "Esa fecha ya pasó."
        if hora is None:
            errores["hora_inicio"] = "La hora no tiene un formato válido."

        if errores:
            raise ErrorValidacion(errores)

        datos["id_empleado"] = id_empleado

        with obtener_cursor(commit=True) as cursor:
            nuevo = self.repositorio.crear(datos, cursor=cursor)
            id_evento = self._evento_de_la_clase(cursor, fecha, hora)
            self.inscripciones.inscribir_posible(
                id_evento, nuevo, id_empleado, cursor=cursor
            )

        self.bitacora.registrar(
            id_empleado,
            bit.POSIBLE_CREADO,
            bit.POSIBLE_CLIENTE,
            nuevo,
            {
                "nombre": f"{datos['nombre']} {datos['apellido']}",
                "correo": datos["correo"],
                "fecha_clase": fecha.isoformat(),
                "id_coach": datos["id_coach"],
            },
        )
        return nuevo

    def _evento_de_la_clase(self, cursor, fecha: date, hora: time) -> int:
        """Busca la clase de prueba de ese día y hora, o la crea.

        Varias personas pueden probar el mismo día a la misma hora, así
        que comparten el evento en vez de llenar el calendario con una
        entrada por persona.
        """
        cursor.execute(
            "SELECT id_categoria FROM categorias_evento WHERE nombre = %s",
            (CATEGORIA_CLASE_PRUEBA,),
        )
        fila = cursor.fetchone()
        if fila is None:
            raise ValueError(
                f"Falta la categoría '{CATEGORIA_CLASE_PRUEBA}' en el calendario."
            )
        id_categoria = fila["id_categoria"]

        cursor.execute(
            """
            SELECT id_evento FROM eventos
             WHERE id_categoria = %s AND fecha = %s AND hora_inicio = %s
             LIMIT 1
            """,
            (id_categoria, fecha, hora),
        )
        fila = cursor.fetchone()
        if fila:
            return fila["id_evento"]

        hora_fin = time((hora.hour + DURACION_CLASE_HORAS) % 24, hora.minute)
        cursor.execute(
            """
            INSERT INTO eventos (titulo, id_categoria, fecha, hora_inicio, hora_fin,
                                 descripcion)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id_evento
            """,
            (
                "Clase de prueba",
                id_categoria,
                fecha,
                hora,
                hora_fin,
                "Creada automáticamente al agendar un posible cliente.",
            ),
        )
        return cursor.fetchone()["id_evento"]

    def actualizar(self, id_posible: int, formulario: dict, id_empleado: int) -> None:
        actual = self.repositorio.obtener(id_posible)
        if actual is None:
            raise ValueError("Ese posible cliente no existe.")

        datos = self._normalizar(formulario)
        errores = self._validar(datos)
        if errores:
            raise ErrorValidacion(errores)

        cambios = {}
        for campo in ("nombre", "apellido", "correo", "telefono", "id_coach"):
            antes, despues = getattr(actual, campo), datos[campo]
            if antes != despues:
                cambios[campo] = {"antes": antes, "despues": despues}

        self.repositorio.actualizar(id_posible, datos)

        if cambios:
            # Asignar coach es la acción que más interesa seguir, así
            # que se registra con su propio nombre.
            accion = (
                bit.COACH_ASIGNADO
                if set(cambios) == {"id_coach"}
                else bit.POSIBLE_EDITADO
            )
            self.bitacora.registrar(
                id_empleado, accion, bit.POSIBLE_CLIENTE, id_posible,
                {"nombre": actual.nombre_completo, "cambios": cambios},
            )

    def marcar_asistencia(self, id_posible: int, asistio: bool | None,
                          id_empleado: int) -> None:
        posible = self.repositorio.obtener(id_posible)
        if posible is None:
            raise ValueError("Ese posible cliente no existe.")

        self.repositorio.marcar_asistencia(id_posible, asistio)
        self.bitacora.registrar(
            id_empleado, bit.ASISTENCIA_MARCADA, bit.POSIBLE_CLIENTE, id_posible,
            {"nombre": posible.nombre_completo, "asistio": asistio},
        )

    def deshacer_conversion(self, id_posible: int, id_empleado: int) -> None:
        """Para cuando el enlace automático juntó a dos personas
        distintas que comparten correo."""
        posible = self.repositorio.obtener(id_posible)
        if posible is None:
            raise ValueError("Ese posible cliente no existe.")

        self.repositorio.deshacer_conversion(id_posible)
        self.bitacora.registrar(
            id_empleado, bit.POSIBLE_EDITADO, bit.POSIBLE_CLIENTE, id_posible,
            {"nombre": posible.nombre_completo, "conversion": "deshecha"},
        )


def _a_entero(valor):
    try:
        numero = int(valor)
        return numero if numero > 0 else None
    except (TypeError, ValueError):
        return None


def _a_fecha(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _a_hora(texto):
    try:
        return datetime.strptime(texto, "%H:%M").time()
    except (TypeError, ValueError):
        return None
