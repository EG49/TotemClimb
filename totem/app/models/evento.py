"""Modelos del calendario: categorías, eventos e inscripciones.

Los cumpleaños no son eventos: se calculan al vuelo desde la fecha de
nacimiento de los clientes y de los empleados, así que no ocupan filas
en la base.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time

# Convención para un evento que dura todo el día.
HORA_INICIO_TODO_EL_DIA = time(0, 0)
HORA_FIN_TODO_EL_DIA = time(23, 59)

# Color de los cumpleaños, que no tienen categoría propia en la base.
COLOR_CUMPLE = "#3395A0"


@dataclass
class CategoriaEvento:
    id_categoria: int | None = None
    nombre: str = ""
    color: str = "#6A6A67"


@dataclass
class Evento:
    id_evento: int | None = None
    titulo: str = ""
    id_categoria: int | None = None
    fecha: date | None = None
    hora_inicio: time | None = None
    hora_fin: time | None = None
    descripcion: str | None = None
    cupo_maximo: int | None = None

    # Datos traídos con JOIN
    categoria_nombre: str | None = None
    categoria_color: str = "#6A6A67"
    inscritos: int = 0
    nombres_inscritos: list = field(default_factory=list)

    @property
    def es_todo_el_dia(self) -> bool:
        return (
            self.hora_inicio == HORA_INICIO_TODO_EL_DIA
            and self.hora_fin >= time(23, 59)
        )

    @property
    def horario(self) -> str:
        if self.es_todo_el_dia:
            return "Todo el día"
        return f"{self.hora_inicio.strftime('%H:%M')} – {self.hora_fin.strftime('%H:%M')}"

    @property
    def cupo_lleno(self) -> bool:
        return self.cupo_maximo is not None and self.inscritos >= self.cupo_maximo

    @property
    def cupo_texto(self) -> str:
        if self.cupo_maximo:
            return f"{self.inscritos}/{self.cupo_maximo}"
        return f"{self.inscritos} inscrito{'s' if self.inscritos != 1 else ''}"

    @property
    def ya_paso(self) -> bool:
        return self.fecha < date.today()

    @classmethod
    def desde_fila(cls, fila: dict) -> "Evento":
        conocidos = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in fila.items() if k in conocidos})


# Los empleados se distinguen con otro color, para que el personal vea
# de un vistazo si el cumpleaños es de un cliente o de un compañero.
COLOR_CUMPLE_EMPLEADO = "#C2DD58"


@dataclass
class Cumpleanos:
    """Marca de cumpleaños, calculada, no almacenada."""

    id_cliente: int
    nombre: str
    fecha: date
    edad: int
    es_empleado: bool = False
    es_cumple: bool = True

    @property
    def titulo(self) -> str:
        quien = "Cumpleaños del equipo" if self.es_empleado else "Cumpleaños"
        return f"{quien}: {self.nombre}"

    @property
    def horario(self) -> str:
        return f"Cumple {self.edad} años"

    @property
    def categoria_color(self) -> str:
        return COLOR_CUMPLE_EMPLEADO if self.es_empleado else COLOR_CUMPLE

    @property
    def categoria_nombre(self) -> str:
        return "Cumpleaños del equipo" if self.es_empleado else "Cumpleaños"
