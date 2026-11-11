"""Modelo de dominio: Gasto.

Un gasto es plata que sale. Junto con las facturas (plata que entra)
es lo que forma el balance.

Dos campos merecen explicación:

  segmento   A qué parte del gym se le carga el gasto: JUNIOR,
             SENIOR o GENERAL. Lo acordado el 23/10 es poder ver si
             la escuelita de chicos se sostiene sola, y para eso
             hace falta saber qué gasto es de quién. Lo que no se
             puede repartir va a GENERAL.

  facturado  Si hay factura de respaldo. Es lo que separa lo
             deducible de lo que no. Un gasto real sin factura
             sigue siendo un gasto: resta en el balance igual, pero
             no se puede justificar ante el SRI.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

# Segmentos (ver chk_gasto_segmento en el esquema)
JUNIOR = "JUNIOR"
SENIOR = "SENIOR"
GENERAL = "GENERAL"

SEGMENTOS = (JUNIOR, SENIOR, GENERAL)
ETIQUETA_SEGMENTO = {
    JUNIOR: "Junior",
    SENIOR: "Senior",
    GENERAL: "General",
}

# Estados (ver chk_gasto_estado)
REGISTRADO = "REGISTRADO"
ANULADO = "ANULADO"

ESTADOS = (REGISTRADO, ANULADO)
ETIQUETA_ESTADO = {REGISTRADO: "Registrado", ANULADO: "Anulado"}

# Métodos de pago (ver chk_gasto_metodo)
EFECTIVO = "EFECTIVO"
TRANSFERENCIA = "TRANSFERENCIA"

METODOS = (EFECTIVO, TRANSFERENCIA)
ETIQUETA_METODO = {EFECTIVO: "Efectivo", TRANSFERENCIA: "Transferencia"}

# Conceptos que se ofrecen de arranque, cuando todavía no hay
# historial del cual sacar sugerencias. No es una lista cerrada: el
# campo es libre y acepta cualquier cosa.
CONCEPTOS_SUGERIDOS = (
    "Arriendo",
    "Luz",
    "Agua",
    "Internet",
    "Sueldos",
    "Magnesio",
    "Mantenimiento de presas",
    "Cuerdas y equipo",
    "Limpieza",
    "Publicidad",
    "Contador",
    "Impuestos",
)


@dataclass
class Gasto:
    id_gasto: int | None = None
    fecha: date | None = None
    monto: Decimal = Decimal("0")
    segmento: str = GENERAL
    concepto: str = ""
    facturado: bool = False
    descripcion: str | None = None
    metodo_pago: str | None = None
    id_empleado: int | None = None
    estado: str = REGISTRADO
    motivo_anulacion: str | None = None
    fecha_registro: datetime | None = None

    # Viene del JOIN con empleados; no está en la tabla gastos.
    empleado_nombre: str | None = None

    @property
    def monto_texto(self) -> str:
        return f"${self.monto:,.2f}"

    @property
    def segmento_etiqueta(self) -> str:
        return ETIQUETA_SEGMENTO.get(self.segmento, self.segmento)

    @property
    def estado_etiqueta(self) -> str:
        return ETIQUETA_ESTADO.get(self.estado, self.estado)

    @property
    def metodo_etiqueta(self) -> str:
        if not self.metodo_pago:
            return "—"
        return ETIQUETA_METODO.get(self.metodo_pago, self.metodo_pago)

    @property
    def anulado(self) -> bool:
        return self.estado == ANULADO

    @property
    def respaldo_etiqueta(self) -> str:
        return "Facturado" if self.facturado else "Sin factura"

    @property
    def cuenta_en_balance(self) -> bool:
        """Un gasto anulado no resta. Todo lo demás sí, con factura o sin ella."""
        return not self.anulado

    @classmethod
    def desde_fila(cls, fila: dict) -> "Gasto":
        conocidos = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in fila.items() if k in conocidos})
