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

# Datos del gimnasio que salen en los correos.
CLAVES_GYM = (
    "gym_direccion",
    "gym_mapa_url",
    "gym_telefono",
    "gym_que_traer",
)
LARGO_MAXIMO_GYM = 500


def _es_enlace(texto: str) -> bool:
    """Acepta solo https, y nada que parezca un intento de inyección.

    El valor termina dentro de un href de un correo, así que un
    javascript: o un data: ahí serían un agujero. Con exigir https
    alcanza: Google Maps siempre lo da así.
    """
    return texto.lower().startswith("https://") and "\n" not in texto


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

    # --- Datos del gimnasio -------------------------------------------
    # Salen en los correos de clases y eventos. No se escriben en el
    # código porque son del gimnasio, no del sistema: los carga el
    # admin y los puede cambiar sin tocar nada.

    def datos_del_gym(self) -> dict:
        """Los cuatro datos, siempre como texto. Vacío si no se cargó."""
        return {
            clave.removeprefix("gym_"): (self.repositorio.obtener(clave) or "").strip()
            for clave in CLAVES_GYM
        }

    def guardar_datos_del_gym(self, formulario: dict, id_empleado: int) -> list[str]:
        """Guarda los que cambiaron y devuelve sus nombres.

        Devolver solo lo que cambió evita llenar la bitácora de
        entradas vacías cada vez que alguien abre y guarda la
        pantalla sin tocar nada.
        """
        actuales = self.datos_del_gym()
        errores: dict[str, str] = {}
        cambios: dict[str, dict] = {}

        for clave in CLAVES_GYM:
            corto = clave.removeprefix("gym_")
            nuevo = " ".join((formulario.get(clave) or "").split())

            if len(nuevo) > LARGO_MAXIMO_GYM:
                errores[clave] = (
                    f"Es muy largo (máximo {LARGO_MAXIMO_GYM} caracteres)."
                )
                continue

            if clave == "gym_mapa_url" and nuevo and not _es_enlace(nuevo):
                errores[clave] = (
                    "Tiene que ser un enlace que empiece con https://"
                )
                continue

            if nuevo != actuales[corto]:
                cambios[clave] = {"antes": actuales[corto], "despues": nuevo}

        if errores:
            raise ErrorValidacion(errores)

        for clave, cambio in cambios.items():
            self.repositorio.guardar(clave, cambio["despues"])

        if cambios:
            self.bitacora.registrar(
                id_empleado, bit.DATOS_GYM_CAMBIADOS, bit.CONFIGURACION,
                None, cambios,
            )

        return [c.removeprefix("gym_") for c in cambios]
