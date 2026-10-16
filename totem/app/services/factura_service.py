"""Servicio del historial de facturas.

Reglas que viven aquí:

  * Una factura nunca se borra. Se anula con un motivo obligatorio y
    queda en el historial.
  * Anular una factura cancela las membresías que generó: si la venta no
    valió, la vigencia tampoco.
  * Un abono baja el saldo; cuando llega a cero, la factura pasa de
    PENDIENTE a EMITIDA y recién ahí cuenta como ingreso.
  * Una factura anulada no admite abonos.
"""

from decimal import Decimal, InvalidOperation

from app.db import obtener_cursor
from app.models.factura import ANULADA, CENTAVO, EMITIDA, METODOS_PAGO, PENDIENTE
from app.repositories.consulta_factura_repo import ConsultaFacturaRepositorio
from app.repositories.factura_repo import FacturaRepositorio
from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService
from app.services.validaciones import ErrorValidacion, limpiar

MOTIVO_MINIMO = 5


def _a_decimal(valor):
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return Decimal(str(valor).strip().replace(",", "."))
    except InvalidOperation:
        return None


class FacturaService:

    def __init__(self):
        self.consultas = ConsultaFacturaRepositorio()
        self.facturas = FacturaRepositorio()
        self.bitacora = BitacoraService()

    # --- Consultas ----------------------------------------------------

    def listar(self, filtros: dict, pagina: int = 1, por_pagina: int = 25):
        facturas = self.consultas.listar(filtros, pagina, por_pagina)
        total = self.consultas.contar(filtros)
        return facturas, total

    def resumen(self, filtros: dict) -> dict:
        return self.consultas.resumen(filtros)

    def agrupado(self, filtros: dict) -> list[dict]:
        return self.consultas.agrupado_por_cliente(filtros)

    def abonos_de(self, id_factura: int) -> list[dict]:
        return self.consultas.abonos_de(id_factura)

    def obtener(self, id_factura: int):
        return self.facturas.obtener(id_factura)

    def para_exportar(self, filtros: dict) -> list[dict]:
        return self.consultas.para_exportar(filtros)

    # --- Cobrar saldo -------------------------------------------------

    def registrar_abono(
        self, id_factura: int, formulario: dict, id_empleado: int
    ) -> dict:
        """Abona a una factura fiada. Devuelve cómo quedó."""
        factura = self.facturas.obtener(id_factura)
        if factura is None:
            raise ValueError("La factura no existe.")

        errores = {}
        if factura.estado == ANULADA:
            errores["general"] = "No se puede abonar a una factura anulada."
        elif factura.estado != PENDIENTE:
            errores["general"] = "Esa factura ya está pagada."

        monto = _a_decimal(formulario.get("monto"))
        if monto is None or monto <= 0:
            errores["monto"] = "Escribe un monto mayor a cero."
        elif not errores and monto > factura.saldo_pendiente:
            errores["monto"] = (
                f"El saldo pendiente es ${factura.saldo_pendiente:.2f}; "
                "no se puede abonar de más."
            )

        metodo = formulario.get("metodo_pago")
        if metodo not in METODOS_PAGO:
            errores["metodo_pago"] = "Elige con qué se recibió el abono."

        if errores:
            raise ErrorValidacion(errores)

        nuevo_saldo = (factura.saldo_pendiente - monto).quantize(CENTAVO)
        quedo_pagada = nuevo_saldo == 0

        with obtener_cursor(commit=True) as cursor:
            self.facturas.registrar_abono(
                id_factura, id_empleado, monto, metodo, cursor
            )
            cursor.execute(
                """
                UPDATE facturas
                   SET saldo_pendiente = %s,
                       estado = %s,
                       -- Al quedar saldada se deja el método del último
                       -- abono, que es con lo que se terminó de pagar.
                       metodo_pago = CASE WHEN %s THEN %s ELSE metodo_pago END
                 WHERE id_factura = %s
                """,
                (
                    nuevo_saldo,
                    EMITIDA if quedo_pagada else PENDIENTE,
                    quedo_pagada,
                    metodo,
                    id_factura,
                ),
            )

        self.bitacora.registrar(
            id_empleado,
            bit.ABONO_REGISTRADO,
            bit.FACTURA,
            id_factura,
            {
                "numero": factura.numero_factura,
                "monto": str(monto),
                "metodo": metodo,
                "saldo_restante": str(nuevo_saldo),
                "quedo_pagada": quedo_pagada,
            },
        )
        return {"saldo": nuevo_saldo, "pagada": quedo_pagada}

    # --- Anular -------------------------------------------------------

    def anular(self, id_factura: int, motivo: str, id_empleado: int) -> None:
        factura = self.facturas.obtener(id_factura)
        if factura is None:
            raise ValueError("La factura no existe.")

        errores = {}
        if factura.estado == ANULADA:
            errores["general"] = "Esa factura ya está anulada."

        motivo = limpiar(motivo) or ""
        if len(motivo) < MOTIVO_MINIMO:
            errores["motivo"] = (
                "Escribe el motivo de la anulación; queda en el historial."
            )

        if errores:
            raise ErrorValidacion(errores)

        with obtener_cursor(commit=True) as cursor:
            # Qué clientes quedan afectados, para refrescar su vigencia.
            cursor.execute(
                "SELECT DISTINCT id_cliente FROM membresias WHERE id_factura = %s",
                (id_factura,),
            )
            afectados = [f["id_cliente"] for f in cursor.fetchall()]

            cursor.execute(
                """
                UPDATE facturas
                   SET estado = %s, motivo_anulacion = %s, saldo_pendiente = 0
                 WHERE id_factura = %s
                """,
                (ANULADA, motivo, id_factura),
            )

            # Si la venta se anula, la vigencia que generó también.
            cursor.execute(
                "UPDATE membresias SET estado = 'CANCELADA' WHERE id_factura = %s",
                (id_factura,),
            )

            for id_cliente in afectados:
                cursor.execute(
                    """
                    UPDATE clientes
                       SET vigente_hasta = (
                             SELECT MAX(fecha_fin) FROM membresias
                              WHERE id_cliente = %s AND estado = 'ACTIVA'
                           )
                     WHERE id_cliente = %s
                    """,
                    (id_cliente, id_cliente),
                )

        self.bitacora.registrar(
            id_empleado,
            bit.FACTURA_ANULADA,
            bit.FACTURA,
            id_factura,
            {
                "numero": factura.numero_factura,
                "cliente": factura.cliente_nombre,
                "total": str(factura.total),
                "motivo": motivo,
                "membresias_canceladas": len(afectados),
            },
        )
