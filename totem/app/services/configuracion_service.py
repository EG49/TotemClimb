"""Servicio de configuración del sistema.

Hoy solo gestiona el IVA. Cambiarlo afecta a las facturas futuras: cada
factura guarda la tasa con la que se emitió, así que las anteriores no
se tocan.
"""

from decimal import Decimal, InvalidOperation

from app.repositories.factura_repo import ConfiguracionRepositorio
from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService
from app.services.validaciones import ErrorValidacion

CLAVE_IVA = "iva_porcentaje"
IVA_POR_DEFECTO = Decimal("15")


class ConfiguracionService:

    def __init__(self):
        self.repositorio = ConfiguracionRepositorio()
        self.bitacora = BitacoraService()

    def iva_vigente(self) -> Decimal:
        valor = self.repositorio.obtener(CLAVE_IVA)
        try:
            return Decimal(valor) if valor else IVA_POR_DEFECTO
        except InvalidOperation:
            return IVA_POR_DEFECTO

    def cambiar_iva(self, valor, id_empleado: int) -> None:
        anterior = self.iva_vigente()

        try:
            nuevo = Decimal(str(valor).strip().replace(",", "."))
        except (InvalidOperation, AttributeError, TypeError):
            raise ErrorValidacion({"iva_porcentaje": "Escribe un número válido."})

        if nuevo < 0 or nuevo > 100:
            raise ErrorValidacion(
                {"iva_porcentaje": "El IVA debe estar entre 0 y 100."}
            )
        if nuevo == anterior:
            raise ErrorValidacion(
                {"iva_porcentaje": f"El IVA ya está en {anterior}%."}
            )

        self.repositorio.guardar(CLAVE_IVA, str(nuevo))
        self.bitacora.registrar(
            id_empleado,
            bit.IVA_CAMBIADO,
            bit.CONFIGURACION,
            None,
            {"antes": str(anterior), "despues": str(nuevo)},
        )

    def historial_iva(self, limite: int = 10) -> list[dict]:
        return self.bitacora.consultar(accion=bit.IVA_CAMBIADO, limite=limite)
