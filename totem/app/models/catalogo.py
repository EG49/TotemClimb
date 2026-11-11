"""Modelos de dominio: Producto y PlanMembresia.

Son las dos cosas que se pueden vender. Un producto es un artículo
físico; un plan genera una membresía al facturarse. Viven en tablas
separadas pero en "Cobrar" se eligen de una sola lista.
"""

from dataclasses import dataclass
from decimal import Decimal

# Tipos de plan. Solo son dos: Senior es todo lo que no es Junior, y
# los pases también son Senior.
#
# "tipo" es SOLO la categoría comercial, la que se usa para precios y
# reportes. Que un plan sea un pase NO se deduce del tipo sino de que
# tenga entradas incluidas (dias_incluidos). Antes el tipo hacía las
# dos cosas a la vez, y por eso no se podía clasificar un pase como
# Senior sin romper el cálculo de la venta.
JUNIOR = "JUNIOR"
SENIOR = "SENIOR"

TIPOS_PLAN = (JUNIOR, SENIOR)
ETIQUETA_TIPO = {JUNIOR: "Junior", SENIOR: "Senior"}

# Unidades de duración
DIA = "DIA"
MES = "MES"
UNIDADES = (DIA, MES)
ETIQUETA_UNIDAD = {DIA: "Día", MES: "Mes"}


@dataclass
class Producto:
    id_producto: int | None = None
    nombre: str = ""
    precio: Decimal = Decimal("0")
    activo: bool = True

    @property
    def precio_texto(self) -> str:
        return f"${self.precio:,.2f}"

    @classmethod
    def desde_fila(cls, fila: dict) -> "Producto":
        conocidos = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in fila.items() if k in conocidos})


@dataclass
class PlanMembresia:
    id_plan: int | None = None
    nombre: str = ""
    tipo: str = SENIOR
    precio: Decimal = Decimal("0")
    duracion: int = 1
    unidad_duracion: str = MES
    dias_incluidos: int | None = None
    permite_pareja: bool = False
    permite_descuento: bool = True
    activo: bool = True

    @property
    def precio_texto(self) -> str:
        return f"${self.precio:,.2f}"

    @property
    def tipo_etiqueta(self) -> str:
        return ETIQUETA_TIPO.get(self.tipo, self.tipo)

    @property
    def es_pase(self) -> bool:
        """Un plan es pase si trae entradas contadas, no por su tipo."""
        return self.dias_incluidos is not None

    @property
    def duracion_texto(self) -> str:
        """Ej.: '1 mes', '30 días'. Para los pases añade las entradas."""
        unidad = "mes" if self.unidad_duracion == MES else "día"
        plural = "es" if unidad == "mes" and self.duracion != 1 else (
            "s" if unidad == "día" and self.duracion != 1 else ""
        )
        texto = f"{self.duracion} {unidad}{plural}"
        if self.es_pase and self.dias_incluidos:
            entradas = "entrada" if self.dias_incluidos == 1 else "entradas"
            texto = f"{self.dias_incluidos} {entradas} · vence en {texto}"
        return texto

    @classmethod
    def desde_fila(cls, fila: dict) -> "PlanMembresia":
        conocidos = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in fila.items() if k in conocidos})
