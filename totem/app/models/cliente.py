"""Modelo de dominio: Cliente.

Un menor a cargo es un cliente más, con su propia membresía e historial,
ligado a su representante por id_representante.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

# Estados de membresía calculados al vuelo a partir de fecha_fin.
VIGENTE = "VIGENTE"
POR_VENCER = "POR_VENCER"
VENCIDO = "VENCIDO"
SIN_MEMBRESIA = "SIN_MEMBRESIA"

ETIQUETA_ESTADO = {
    VIGENTE: "Vigente",
    POR_VENCER: "Por vencer",
    VENCIDO: "Vencido",
    SIN_MEMBRESIA: "Sin membresía",
}

# Días de antelación con los que una membresía se marca "por vencer".
DIAS_AVISO_VENCIMIENTO = 7


@dataclass
class Cliente:
    id_cliente: int | None = None
    nombre: str = ""
    apellido: str = ""
    cedula: str | None = None
    fecha_nacimiento: date | None = None
    correo: str | None = None
    telefono: str | None = None
    genero: str | None = None
    contacto_emergencia: str | None = None
    referencia: str | None = None
    seguro_nombre: str | None = None
    seguro_numero: str | None = None
    id_representante: int | None = None
    fecha_registro: datetime | None = None

    # Datos que vienen de otras tablas en el listado y el detalle.
    representante_nombre: str | None = None
    menores_a_cargo: int = 0
    plan_nombre: str | None = None
    plan_tipo: str | None = None
    fecha_fin: date | None = None
    dias_totales: int | None = None
    dias_restantes: int | None = None

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}".strip()

    @property
    def iniciales(self) -> str:
        partes = [p for p in (self.nombre, self.apellido) if p]
        return "".join(p[0].upper() for p in partes)[:2]

    @property
    def edad(self) -> int | None:
        if self.fecha_nacimiento is None:
            return None
        hoy = date.today()
        años = hoy.year - self.fecha_nacimiento.year
        if (hoy.month, hoy.day) < (
            self.fecha_nacimiento.month,
            self.fecha_nacimiento.day,
        ):
            años -= 1
        return años

    @property
    def tiene_representante(self) -> bool:
        return self.id_representante is not None

    @property
    def cumplio_mayoria(self) -> bool:
        """Menor registrado que ya cumplió 18 y sigue con representante.

        Dispara el aviso para que firme su propio contrato como adulto.
        """
        edad = self.edad
        return self.tiene_representante and edad is not None and edad >= 18

    @property
    def tiene_seguro(self) -> bool:
        return bool(self.seguro_nombre or self.seguro_numero)

    @property
    def dias_para_vencer(self) -> int | None:
        if self.fecha_fin is None:
            return None
        return (self.fecha_fin - date.today()).days

    @property
    def estado_membresia(self) -> str:
        if self.fecha_fin is None:
            return SIN_MEMBRESIA
        dias = self.dias_para_vencer
        if dias < 0:
            return VENCIDO
        if dias <= DIAS_AVISO_VENCIMIENTO:
            return POR_VENCER
        return VIGENTE

    @property
    def estado_etiqueta(self) -> str:
        return ETIQUETA_ESTADO[self.estado_membresia]

    @property
    def vencimiento_relativo(self) -> str:
        """Texto amable para la columna 'Vence' del listado."""
        dias = self.dias_para_vencer
        if dias is None:
            return "—"
        if dias < 0:
            return f"hace {abs(dias)} día{'s' if abs(dias) != 1 else ''}"
        if dias == 0:
            return "hoy"
        if dias == 1:
            return "mañana"
        return f"en {dias} días"

    @classmethod
    def desde_fila(cls, fila: dict) -> "Cliente":
        conocidos = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in fila.items() if k in conocidos})
