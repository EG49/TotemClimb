"""Modelos del cobro: líneas, totales y factura."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

# Estados de factura
EMITIDA = "EMITIDA"
PENDIENTE = "PENDIENTE"
ANULADA = "ANULADA"

# Métodos de pago aceptados
EFECTIVO = "EFECTIVO"
TRANSFERENCIA = "TRANSFERENCIA"
METODOS_PAGO = (EFECTIVO, TRANSFERENCIA)
ETIQUETA_METODO = {EFECTIVO: "Efectivo", TRANSFERENCIA: "Transferencia"}

# Tipos de línea
PRODUCTO = "producto"
PLAN = "plan"

CENTAVO = Decimal("0.01")


@dataclass
class LineaCobro:
    """Una línea del cobro: un producto o un plan de membresía."""

    tipo: str
    id_item: int
    nombre: str
    precio_unitario: Decimal
    cantidad: int = 1
    permite_descuento: bool = True
    permite_pareja: bool = False

    @property
    def subtotal(self) -> Decimal:
        return (self.precio_unitario * self.cantidad).quantize(CENTAVO)

    @property
    def es_plan(self) -> bool:
        return self.tipo == PLAN


@dataclass
class Totales:
    """Resultado del cálculo. Lo produce siempre el servidor."""

    subtotal: Decimal = Decimal("0")
    descuento_porcentaje: Decimal = Decimal("0")
    descuento_monto: Decimal = Decimal("0")
    base_imponible: Decimal = Decimal("0")
    iva_porcentaje: Decimal = Decimal("0")
    iva: Decimal = Decimal("0")
    total: Decimal = Decimal("0")


@dataclass
class Factura:
    id_factura: int | None = None
    numero_factura: str = ""
    id_cliente: int | None = None
    id_empleado: int | None = None
    fecha: datetime | None = None
    metodo_pago: str | None = None
    descuento_porcentaje: Decimal = Decimal("0")
    iva_porcentaje: Decimal = Decimal("0")
    subtotal: Decimal = Decimal("0")
    iva: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    estado: str = EMITIDA
    motivo_anulacion: str | None = None
    saldo_pendiente: Decimal = Decimal("0")

    # Datos traídos con JOIN para mostrar
    cliente_nombre: str | None = None
    empleado_nombre: str | None = None
    detalle: list = field(default_factory=list)

    @property
    def esta_fiada(self) -> bool:
        return self.estado == PENDIENTE

    @property
    def abonado(self) -> Decimal:
        return (self.total - self.saldo_pendiente).quantize(CENTAVO)

    @property
    def metodo_etiqueta(self) -> str:
        return ETIQUETA_METODO.get(self.metodo_pago, "—")

    @classmethod
    def desde_fila(cls, fila: dict) -> "Factura":
        conocidos = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in fila.items() if k in conocidos})


@dataclass
class Membresia:
    """Vigencia generada por la venta de un plan."""

    id_membresia: int | None = None
    id_cliente: int | None = None
    id_plan: int | None = None
    id_factura: int | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    dias_totales: int | None = None
    dias_restantes: int | None = None
    estado: str = "ACTIVA"
    id_membresia_pareja: int | None = None
