"""Modelo de dominio: Empleado.

Los modelos son objetos de datos sin lógica de acceso a la base ni de
negocio. Solo describen la forma de una entidad.
"""

from dataclasses import dataclass
from datetime import date, datetime


ROL_ADMIN = "ADMIN"
ROL_VENDEDOR = "VENDEDOR"


@dataclass
class Empleado:
    id_empleado: int
    nombre: str
    apellido: str
    usuario: str
    rol: str
    activo: bool
    fecha_nacimiento: date | None = None
    fecha_registro: datetime | None = None

    # El hash nunca sale de la capa de datos hacia las vistas; solo el
    # servicio de autenticación lo necesita.
    password_hash: str | None = None

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}"

    @property
    def es_admin(self) -> bool:
        return self.rol == ROL_ADMIN

    @property
    def iniciales(self) -> str:
        partes = [p for p in (self.nombre, self.apellido) if p]
        return "".join(p[0].upper() for p in partes)[:2]

    @property
    def rol_etiqueta(self) -> str:
        return "Administrador" if self.es_admin else "Vendedor"

    @classmethod
    def desde_fila(cls, fila: dict) -> "Empleado":
        """Construye un Empleado a partir de una fila de la base."""
        return cls(
            id_empleado=fila["id_empleado"],
            nombre=fila["nombre"],
            apellido=fila["apellido"],
            usuario=fila["usuario"],
            rol=fila["rol"],
            activo=fila["activo"],
            fecha_nacimiento=fila.get("fecha_nacimiento"),
            fecha_registro=fila.get("fecha_registro"),
            password_hash=fila.get("password_hash"),
        )
