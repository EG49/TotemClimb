"""Servicio del calendario.

Reglas que viven aquí:

  * Un evento no puede terminar antes de empezar. Si se marca "todo el
    día", se guarda de 00:00 a 23:59 y se indica en el título.
  * El cupo se valida al inscribir, contando dentro de la transacción
    para que dos inscripciones simultáneas no pasen del límite.
  * Un cliente no se inscribe dos veces al mismo evento.
  * Los cumpleaños se calculan, no se guardan.
"""

from calendar import monthrange
from datetime import date, datetime, time, timedelta

from app.db import obtener_cursor
from app.models.evento import (
    HORA_FIN_TODO_EL_DIA,
    HORA_INICIO_TODO_EL_DIA,
)
from app.repositories.evento_repo import (
    CategoriaRepositorio,
    CumpleanosRepositorio,
    EventoRepositorio,
    InscripcionRepositorio,
)
from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService
from app.services.validaciones import ErrorValidacion, limpiar

TITULO_TODO_EL_DIA = "(todo el día)"


def lunes_de(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())


def rango_vista(vista: str, ancla: date) -> tuple[date, date]:
    """Primer y último día que hay que traer para pintar la vista."""
    if vista == "semana":
        inicio = lunes_de(ancla)
        return inicio, inicio + timedelta(days=6)
    if vista == "anio":
        return date(ancla.year, 1, 1), date(ancla.year, 12, 31)
    # Mes: se extiende a semanas completas, porque la cuadrícula muestra
    # los días del mes anterior y el siguiente que completan las filas.
    primero = ancla.replace(day=1)
    ultimo = ancla.replace(day=monthrange(ancla.year, ancla.month)[1])
    return lunes_de(primero), lunes_de(ultimo) + timedelta(days=6)


class CalendarioService:

    def __init__(self):
        self.eventos = EventoRepositorio()
        self.categorias = CategoriaRepositorio()
        self.inscripciones = InscripcionRepositorio()
        self.cumpleanos = CumpleanosRepositorio()
        self.bitacora = BitacoraService()

    # --- Lectura ------------------------------------------------------

    def marcas_por_dia(self, desde: date, hasta: date) -> dict:
        """Todo lo que ocurre en el rango, agrupado por fecha.

        Mezcla eventos reales con cumpleaños calculados; la vista los
        pinta igual.
        """
        por_dia: dict[date, list] = {}

        for evento in self.eventos.entre(desde, hasta):
            por_dia.setdefault(evento.fecha, []).append(evento)

        for cumple in self.cumpleanos.entre(desde, hasta):
            por_dia.setdefault(cumple.fecha, []).append(cumple)

        for dia in por_dia:
            # Los cumpleaños no tienen hora, así que van primero.
            por_dia[dia].sort(key=lambda m: getattr(m, "hora_inicio", None) or time(0, 0))
        return por_dia

    def listar_categorias(self):
        return self.categorias.listar()

    def obtener_evento(self, id_evento: int):
        return self.eventos.obtener(id_evento)

    def proximos(self, limite=5):
        return self.eventos.proximos(limite)

    # --- Escritura ----------------------------------------------------

    def _normalizar(self, formulario: dict) -> tuple[dict, dict]:
        errores = {}

        titulo = limpiar(formulario.get("titulo"))
        if not titulo:
            errores["titulo"] = "Escribe un título para el evento."

        try:
            id_categoria = int(formulario.get("id_categoria") or 0)
        except (TypeError, ValueError):
            id_categoria = 0
        if not id_categoria or self.categorias.obtener(id_categoria) is None:
            errores["id_categoria"] = "Elige una categoría."

        fecha = None
        try:
            fecha = datetime.strptime(formulario.get("fecha", ""), "%Y-%m-%d").date()
        except ValueError:
            errores["fecha"] = "Elige una fecha válida."

        todo_el_dia = formulario.get("todo_el_dia") == "on"
        if todo_el_dia:
            inicio, fin = HORA_INICIO_TODO_EL_DIA, HORA_FIN_TODO_EL_DIA
            if titulo and TITULO_TODO_EL_DIA not in titulo.lower():
                titulo = f"{titulo} {TITULO_TODO_EL_DIA}"
        else:
            inicio = _a_hora(formulario.get("hora_inicio"))
            fin = _a_hora(formulario.get("hora_fin"))
            if inicio is None or fin is None:
                errores["hora_inicio"] = "Indica la hora de inicio y de fin."
            elif fin <= inicio:
                errores["hora_fin"] = "La hora de fin debe ser posterior a la de inicio."

        cupo = formulario.get("cupo_maximo")
        cupo_maximo = None
        if cupo not in (None, "", "0"):
            try:
                cupo_maximo = int(cupo)
                if cupo_maximo < 1:
                    errores["cupo_maximo"] = "El cupo debe ser mayor a cero."
            except (TypeError, ValueError):
                errores["cupo_maximo"] = "El cupo debe ser un número."

        return {
            "titulo": titulo,
            "id_categoria": id_categoria,
            "fecha": fecha,
            "hora_inicio": inicio,
            "hora_fin": fin,
            "descripcion": limpiar(formulario.get("descripcion")),
            "cupo_maximo": cupo_maximo,
        }, errores

    def crear_evento(
        self, formulario: dict, ids_clientes: list[int], id_empleado: int
    ) -> int:
        datos, errores = self._normalizar(formulario)

        if datos["cupo_maximo"] and len(ids_clientes) > datos["cupo_maximo"]:
            errores["cupo_maximo"] = (
                f"Elegiste {len(ids_clientes)} clientes pero el cupo es "
                f"{datos['cupo_maximo']}."
            )

        if errores:
            raise ErrorValidacion(errores)

        with obtener_cursor(commit=True) as cursor:
            id_evento = self.eventos.crear(datos, cursor)
            for id_cliente in ids_clientes:
                self.inscripciones.inscribir(id_evento, id_cliente, id_empleado, cursor)

        self.bitacora.registrar(
            id_empleado,
            bit.INSCRIPCION_REGISTRADA if ids_clientes else bit.ITEM_CREADO,
            bit.INSCRIPCION if ids_clientes else bit.CONFIGURACION,
            id_evento,
            {
                "evento": datos["titulo"],
                "fecha": datos["fecha"].isoformat(),
                "inscritos": len(ids_clientes),
            },
        )
        return id_evento

    def actualizar_evento(
        self, id_evento: int, formulario: dict, id_empleado: int
    ) -> None:
        datos, errores = self._normalizar(formulario)
        if errores:
            raise ErrorValidacion(errores)

        evento = self.eventos.obtener(id_evento)
        if evento is None:
            raise ValueError("El evento no existe.")
        if datos["cupo_maximo"] and evento.inscritos > datos["cupo_maximo"]:
            raise ErrorValidacion(
                {
                    "cupo_maximo": (
                        f"Ya hay {evento.inscritos} inscritos; el cupo no puede "
                        "ser menor."
                    )
                }
            )

        self.eventos.actualizar(id_evento, datos)

    def eliminar_evento(self, id_evento: int, id_empleado: int) -> None:
        evento = self.eventos.obtener(id_evento)
        if evento is None:
            return
        self.eventos.eliminar(id_evento)
        self.bitacora.registrar(
            id_empleado,
            bit.INSCRIPCION_CANCELADA,
            bit.INSCRIPCION,
            id_evento,
            {"evento": evento.titulo, "inscritos_afectados": evento.inscritos},
        )

    # --- Inscripciones ------------------------------------------------

    def inscribir(self, id_evento: int, id_cliente: int, id_empleado: int) -> None:
        """Inscribe a un cliente validando el cupo dentro de la transacción.

        Contar y luego insertar en la misma transacción evita que dos
        inscripciones simultáneas pasen del límite.
        """
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "SELECT cupo_maximo, titulo FROM eventos WHERE id_evento = %s "
                "FOR UPDATE",
                (id_evento,),
            )
            evento = cursor.fetchone()
            if evento is None:
                raise ValueError("El evento no existe.")

            cursor.execute(
                "SELECT 1 FROM evento_inscritos WHERE id_evento = %s AND id_cliente = %s",
                (id_evento, id_cliente),
            )
            if cursor.fetchone():
                raise ErrorValidacion(
                    {"general": "Ese cliente ya está inscrito en este evento."}
                )

            if evento["cupo_maximo"]:
                actuales = self.inscripciones.contar_en(id_evento, cursor)
                if actuales >= evento["cupo_maximo"]:
                    raise ErrorValidacion(
                        {"general": f"'{evento['titulo']}' ya tiene el cupo completo."}
                    )

            self.inscripciones.inscribir(id_evento, id_cliente, id_empleado, cursor)

        self.bitacora.registrar(
            id_empleado,
            bit.INSCRIPCION_REGISTRADA,
            bit.INSCRIPCION,
            id_evento,
            {"evento": evento["titulo"], "id_cliente": id_cliente},
        )

    def quitar_inscripcion(
        self, id_evento: int, id_cliente: int, id_empleado: int
    ) -> None:
        evento = self.eventos.obtener(id_evento)
        self.inscripciones.quitar(id_evento, id_cliente)
        self.bitacora.registrar(
            id_empleado,
            bit.INSCRIPCION_CANCELADA,
            bit.INSCRIPCION,
            id_evento,
            {
                "evento": evento.titulo if evento else None,
                "id_cliente": id_cliente,
            },
        )

    def agenda(self, **filtros) -> dict:
        """Agrupa por cliente lo que cada uno tiene agendado."""
        filas = self.inscripciones.agenda_por_cliente(**filtros)
        por_cliente: dict[int, dict] = {}
        for fila in filas:
            entrada = por_cliente.setdefault(
                fila["id_cliente"],
                {
                    "id_cliente": fila["id_cliente"],
                    "nombre": fila["cliente_nombre"],
                    "cedula": fila["cedula"],
                    "es_menor": fila["es_menor"],
                    "eventos": [],
                },
            )
            entrada["eventos"].append(fila)
        return por_cliente


def _a_hora(texto):
    if not texto:
        return None
    try:
        return datetime.strptime(str(texto), "%H:%M").time()
    except ValueError:
        return None
