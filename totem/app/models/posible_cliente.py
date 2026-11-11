"""Modelo de dominio: PosibleCliente.

Quien viene a una clase de prueba sin ser todavía cliente del gimnasio.
Antes se lo registraba como cliente de una vez, lo que ensuciaba el
listado con gente que probó una tarde y no volvió.

Tiene tres estados, y el orden importa porque de ahí salen los números
de cada coach:

    agendado  ->  ¿asistió?  ->  ¿se inscribió?

Un coach que agenda veinte y asisten tres tiene un problema distinto al
de uno que agenda cinco, asisten cinco y no compran. Por eso se guardan
los dos momentos y no solo el final.
"""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class PosibleCliente:
    id_posible: int | None = None
    nombre: str = ""
    apellido: str = ""
    correo: str = ""
    telefono: str | None = None

    id_coach: int | None = None
    id_empleado: int | None = None

    # None mientras la clase no haya pasado o nadie la haya marcado.
    asistio: bool | None = None

    # Se llenan juntos, cuando paga su primera membresía.
    id_cliente: int | None = None
    fecha_conversion: datetime | None = None

    fecha_registro: datetime | None = None

    # Traídos con JOIN
    coach_nombre: str | None = None
    registrado_por: str | None = None
    fecha_clase: date | None = None
    id_evento: int | None = None

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}"

    @property
    def iniciales(self) -> str:
        partes = [p for p in (self.nombre, self.apellido) if p]
        return "".join(p[0].upper() for p in partes)[:2]

    @property
    def convertido(self) -> bool:
        return self.id_cliente is not None

    @property
    def estado(self) -> str:
        """Clave corta del estado, para el filtro y el color."""
        if self.convertido:
            return "convertido"
        if self.asistio is True:
            return "asistio"
        if self.asistio is False:
            return "no_asistio"
        return "agendado"

    @property
    def estado_etiqueta(self) -> str:
        return {
            "convertido": "Se inscribió",
            "asistio": "Asistió",
            "no_asistio": "No asistió",
            "agendado": "Agendado",
        }[self.estado]

    @classmethod
    def desde_fila(cls, fila: dict) -> "PosibleCliente":
        conocidos = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in fila.items() if k in conocidos})
