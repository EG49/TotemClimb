"""Modelo de dominio: Empleado.

Los modelos son objetos de datos sin lógica de acceso a la base ni de
negocio. Solo describen la forma de una entidad.
"""

from dataclasses import dataclass
from datetime import date, datetime


ROL_ADMIN = "ADMIN"
ROL_VENDEDOR = "VENDEDOR"

# El rol dice qué puede hacer alguien DENTRO del sistema, y solo lo
# tiene quien inicia sesión. Ser coach es otra cosa: una función en el
# gimnasio, que no habilita ningún acceso. Por eso van separados y una
# misma persona puede ser vendedora y coach a la vez.


@dataclass
class Empleado:
    id_empleado: int
    nombre: str
    apellido: str
    # Nulos en un coach que no entra al sistema.
    usuario: str | None
    rol: str | None
    activo: bool
    es_coach: bool = False
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
    def tiene_acceso(self) -> bool:
        """Si puede iniciar sesión. Un coach puro no puede."""
        return self.rol is not None

    @property
    def iniciales(self) -> str:
        partes = [p for p in (self.nombre, self.apellido) if p]
        return "".join(p[0].upper() for p in partes)[:2]

    @property
    def rol_etiqueta(self) -> str:
        """Cómo se describe a esta persona en pantalla.

        Un coach que además vende es las dos cosas, y conviene que se
        vea así en el listado.
        """
        if self.rol is None:
            return "Coach"
        base = "Administrador" if self.es_admin else "Vendedor"
        return f"{base} y coach" if self.es_coach else base

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
            es_coach=fila.get("es_coach", False),
            fecha_nacimiento=fila.get("fecha_nacimiento"),
            fecha_registro=fila.get("fecha_registro"),
            password_hash=fila.get("password_hash"),
        )
