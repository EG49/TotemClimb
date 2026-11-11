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


def interpretar_iva(valor) -> Decimal:
    """Traduce el valor guardado en configuración a un porcentaje.

    Única fuente de verdad: antes el cobro tenía su propia copia de
    esta lógica y la copia hacía `Decimal(valor) or IVA_POR_DEFECTO`.
    Decimal("0") es falso en Python, así que poner el IVA en 0
    devolvía 15: la pantalla de configuración mostraba 0% y el cobro
    seguía aplicando el 15%.

    Un valor ausente o ilegible cae en el 15 por defecto. Un cero
    explícito es cero.
    """
    if valor is None or str(valor).strip() == "":
        return IVA_POR_DEFECTO
    try:
        porcentaje = Decimal(str(valor).strip().replace(",", "."))
    except InvalidOperation:
        return IVA_POR_DEFECTO

    # Un porcentaje fuera de rango solo puede venir de una edición a
    # mano en la base: se ignora antes de que rompa una factura.
    if porcentaje < 0 or porcentaje > 100:
        return IVA_POR_DEFECTO
    return porcentaje


class ConfiguracionService:

    def __init__(self):
        self.repositorio = ConfiguracionRepositorio()
        self.bitacora = BitacoraService()

    def iva_vigente(self) -> Decimal:
        return interpretar_iva(self.repositorio.obtener(CLAVE_IVA))

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
