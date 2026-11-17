"""Servicio de gastos.

Reglas que viven aquí:

  * El monto tiene que ser mayor que cero. Un gasto de cero no es un
    gasto, y uno negativo sería un ingreso disfrazado.
  * Nada se borra. Un gasto mal cargado se corrige o se anula, y el
    anulado queda en el historial con su motivo. El balance de un mes
    cerrado no puede cambiar porque alguien borró una fila.
  * No se puede registrar un gasto con fecha futura: se registra lo
    que ya se pagó.
  * Un gasto anulado no se edita. Primero porque editarlo no tendría
    efecto en el balance, y segundo porque dejaría la bitácora
    diciendo que se modificó algo que ya no cuenta.
  * El concepto se normaliza (espacios fuera, primera en mayúscula)
    porque el balance agrupa por ese campo: "luz", "Luz" y "LUZ "
    serían tres filas distintas del mismo gasto.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.models.gasto import (
    CONCEPTOS_SUGERIDOS,
    METODOS,
    SEGMENTOS,
    Gasto,
)
from app.repositories.gasto_repo import GastoRepositorio
from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService
from app.services.validaciones import ErrorValidacion, limpiar

MONTO_MAXIMO = Decimal("99999999")
MOTIVO_MINIMO = 5


def _a_decimal(valor) -> Decimal | None:
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return Decimal(str(valor).strip().replace(",", "."))
    except InvalidOperation:
        return None


def _a_fecha(valor) -> date | None:
    if isinstance(valor, date):
        return valor
    if not valor:
        return None
    try:
        return datetime.strptime(str(valor).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _limpiar_concepto(valor: str | None) -> str | None:
    """Saca espacios de más y pone la primera en mayúscula.

    Solo toca la primera letra: 'luz' pasa a 'Luz', pero 'Pago SRI' se
    queda como está, porque pasarlo a 'Pago sri' sería peor. La
    unificación de mayúsculas la hace el servicio reusando el concepto
    que ya exista en la base.
    """
    texto = limpiar(valor)
    if not texto:
        return None
    texto = " ".join(texto.split())  # espacios internos de más
    return texto[0].upper() + texto[1:]


class GastoService:

    def __init__(self, repositorio=None, bitacora=None):
        self.repositorio = repositorio or GastoRepositorio()
        self.bitacora = bitacora or BitacoraService()

    def _anotar(self, id_empleado, accion, id_gasto, detalle):
        if id_empleado:
            self.bitacora.registrar(
                id_empleado, accion, bit.GASTO, id_gasto, detalle
            )

    # --- Lectura ------------------------------------------------------

    def listar(self, **filtros) -> tuple[list[Gasto], int]:
        return self.repositorio.listar(**filtros)

    def obtener(self, id_gasto: int) -> Gasto | None:
        return self.repositorio.obtener(id_gasto)

    def resumen(self, desde: date, hasta: date) -> dict:
        return self.repositorio.resumen(desde, hasta)

    def por_concepto(self, desde: date, hasta: date) -> list[dict]:
        return self.repositorio.por_concepto(desde, hasta)

    def conceptos_para_sugerir(self) -> list[str]:
        """Los ya usados primero; los de arranque completan la lista.

        Se deduplica ignorando mayúsculas: una base cargada antes de
        esta versión puede tener 'Luz' y 'LUZ', y ofrecer las dos
        invita a seguir partiendo el balance.
        """
        lista: list[str] = []
        vistos: set[str] = set()
        for concepto in list(self.repositorio.conceptos_usados()) + list(CONCEPTOS_SUGERIDOS):
            clave = concepto.lower()
            if clave not in vistos:
                vistos.add(clave)
                lista.append(concepto)
        return lista

    def recurrentes(self, desde: date) -> list[dict]:
        return self.repositorio.recurrentes_del_mes_anterior(desde)

    # --- Validación ---------------------------------------------------

    def _validar(self, datos: dict) -> dict[str, str]:
        errores = {}

        if datos["fecha"] is None:
            errores["fecha"] = "Ingrese una fecha válida."
        elif datos["fecha"] > date.today():
            errores["fecha"] = "No se puede registrar un gasto a futuro."

        monto = datos["monto"]
        if monto is None:
            errores["monto"] = "Ingrese un monto válido."
        elif monto <= 0:
            errores["monto"] = "El monto tiene que ser mayor que cero."
        elif monto > MONTO_MAXIMO:
            errores["monto"] = "El monto es demasiado alto."

        if datos["segmento"] not in SEGMENTOS:
            errores["segmento"] = "Elija a qué segmento se carga."

        if not datos["concepto"]:
            errores["concepto"] = "Indique qué se pagó."
        elif len(datos["concepto"]) > 80:
            errores["concepto"] = "El concepto es muy largo (máximo 80)."

        if datos["metodo_pago"] and datos["metodo_pago"] not in METODOS:
            errores["metodo_pago"] = "Método de pago no reconocido."

        if datos["descripcion"] and len(datos["descripcion"]) > 255:
            errores["descripcion"] = "La descripción es muy larga (máximo 255)."

        return errores

    def _concepto_final(self, valor: str | None) -> str | None:
        """Limpia el concepto y, si ya existe con otra caja, usa esa forma."""
        texto = _limpiar_concepto(valor)
        if not texto:
            return None
        return self.repositorio.concepto_canonico(texto) or texto

    def _desde_formulario(self, formulario: dict) -> dict:
        return {
            "fecha": _a_fecha(formulario.get("fecha")),
            "monto": _a_decimal(formulario.get("monto")),
            "segmento": (formulario.get("segmento") or "").strip().upper(),
            "concepto": self._concepto_final(formulario.get("concepto")),
            "facturado": formulario.get("facturado") in ("on", "1", "true", "True"),
            "descripcion": limpiar(formulario.get("descripcion")),
            "metodo_pago": limpiar(formulario.get("metodo_pago")),
        }

    # --- Escritura ----------------------------------------------------

    def guardar(
        self,
        formulario: dict,
        id_gasto: int | None = None,
        id_empleado: int | None = None,
    ) -> int:
        datos = self._desde_formulario(formulario)
        errores = self._validar(datos)
        if errores:
            raise ErrorValidacion(errores)

        if id_gasto:
            anterior = self.repositorio.obtener(id_gasto)
            if anterior is None:
                raise ErrorValidacion({"fecha": "El gasto ya no existe."})
            if anterior.anulado:
                raise ErrorValidacion(
                    {"monto": "Un gasto anulado no se puede editar."}
                )

            self.repositorio.actualizar(id_gasto, datos)
            self._anotar(
                id_empleado, bit.GASTO_EDITADO, id_gasto,
                self._cambios(anterior, datos),
            )
            return id_gasto

        nuevo = self.repositorio.crear(datos, id_empleado)
        self._anotar(
            id_empleado, bit.GASTO_REGISTRADO, nuevo,
            {
                "concepto": datos["concepto"],
                "monto": str(datos["monto"]),
                "segmento": datos["segmento"],
                "facturado": datos["facturado"],
            },
        )
        return nuevo

    def _cambios(self, anterior: Gasto, datos: dict) -> dict:
        """Solo lo que efectivamente cambió, para que la bitácora sirva."""
        cambios = {}
        for campo in ("fecha", "monto", "segmento", "concepto",
                      "facturado", "descripcion", "metodo_pago"):
            antes = getattr(anterior, campo)
            despues = datos[campo]
            if str(antes) != str(despues):
                cambios[campo] = {"antes": str(antes), "despues": str(despues)}
        return cambios

    def anular(self, id_gasto: int, motivo: str, id_empleado: int | None = None) -> None:
        motivo = (limpiar(motivo) or "")
        if len(motivo) < MOTIVO_MINIMO:
            raise ErrorValidacion(
                {"motivo": f"Explique el motivo (al menos {MOTIVO_MINIMO} letras)."}
            )

        gasto = self.repositorio.obtener(id_gasto)
        if gasto is None:
            raise ErrorValidacion({"motivo": "El gasto ya no existe."})
        if gasto.anulado:
            raise ErrorValidacion({"motivo": "Este gasto ya está anulado."})

        self.repositorio.anular(id_gasto, motivo)
        self._anotar(
            id_empleado, bit.GASTO_ANULADO, id_gasto,
            {
                "motivo": motivo,
                "concepto": gasto.concepto,
                "monto": str(gasto.monto),
            },
        )
