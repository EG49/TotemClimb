"""Servicio del catálogo: productos y planes de membresía.

Reglas que viven aquí:
  * Los precios no pueden ser negativos.
  * Un plan tipo PASES necesita cuántas entradas incluye; los mensuales
    no llevan ese dato.
  * Nada se borra: lo que deja de venderse se desactiva, para no romper
    las facturas que ya lo incluyen.
"""

from decimal import Decimal, InvalidOperation

from app.models.catalogo import (
    DIA,
    MES,
    PASES,
    TIPOS_PLAN,
    UNIDADES,
    PlanMembresia,
    Producto,
)
from app.repositories.catalogo_repo import PlanRepositorio, ProductoRepositorio
from app.services.validaciones import ErrorValidacion, limpiar

PRECIO_MAXIMO = Decimal("99999999")


def _a_decimal(valor) -> Decimal | None:
    """Convierte el texto del formulario a Decimal, o None si no se puede."""
    if valor is None or str(valor).strip() == "":
        return None
    try:
        return Decimal(str(valor).strip().replace(",", "."))
    except InvalidOperation:
        return None


def _a_entero(valor) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


class CatalogoService:

    def __init__(self, productos=None, planes=None):
        self.productos = productos or ProductoRepositorio()
        self.planes = planes or PlanRepositorio()

    # --- Productos ----------------------------------------------------

    def listar_productos(self, incluir_inactivos=False) -> list[Producto]:
        return self.productos.listar(incluir_inactivos)

    def obtener_producto(self, id_producto: int) -> Producto | None:
        return self.productos.obtener(id_producto)

    def _validar_producto(self, datos: dict, excluir_id=None) -> dict[str, str]:
        errores = {}

        nombre = datos.get("nombre")
        if not nombre:
            errores["nombre"] = "El nombre es obligatorio."
        elif self.productos.nombre_ocupado(nombre, excluir_id):
            errores["nombre"] = "Ya existe un producto con ese nombre."

        precio = datos.get("precio")
        if precio is None:
            errores["precio"] = "Escribe un precio válido."
        elif precio < 0:
            errores["precio"] = "El precio no puede ser negativo."
        elif precio > PRECIO_MAXIMO:
            errores["precio"] = "El precio es demasiado alto."

        return errores

    def guardar_producto(self, formulario: dict, id_producto: int | None = None) -> int:
        datos = {
            "nombre": limpiar(formulario.get("nombre")),
            "precio": _a_decimal(formulario.get("precio")),
        }
        errores = self._validar_producto(datos, excluir_id=id_producto)
        if errores:
            raise ErrorValidacion(errores)

        if id_producto:
            self.productos.actualizar(id_producto, datos)
            return id_producto
        return self.productos.crear(datos)

    def cambiar_estado_producto(self, id_producto: int, activo: bool) -> None:
        self.productos.cambiar_estado(id_producto, activo)

    # --- Planes -------------------------------------------------------

    def listar_planes(self, incluir_inactivos=False) -> list[PlanMembresia]:
        return self.planes.listar(incluir_inactivos)

    def obtener_plan(self, id_plan: int) -> PlanMembresia | None:
        return self.planes.obtener(id_plan)

    def _validar_plan(self, datos: dict, excluir_id=None) -> dict[str, str]:
        errores = {}

        nombre = datos.get("nombre")
        if not nombre:
            errores["nombre"] = "El nombre es obligatorio."
        elif self.planes.nombre_ocupado(nombre, excluir_id):
            errores["nombre"] = "Ya existe un plan con ese nombre."

        if datos.get("tipo") not in TIPOS_PLAN:
            errores["tipo"] = "Selecciona un tipo válido."

        precio = datos.get("precio")
        if precio is None:
            errores["precio"] = "Escribe un precio válido."
        elif precio < 0:
            errores["precio"] = "El precio no puede ser negativo."
        elif precio > PRECIO_MAXIMO:
            errores["precio"] = "El precio es demasiado alto."

        duracion = datos.get("duracion")
        if duracion is None or duracion <= 0:
            errores["duracion"] = "La duración debe ser mayor a cero."

        if datos.get("unidad_duracion") not in UNIDADES:
            errores["unidad_duracion"] = "Selecciona una unidad válida."

        # El esquema exige dias_incluidos en los pases y lo prohíbe en el
        # resto, así que se valida antes de llegar a la base.
        if datos.get("tipo") == PASES:
            dias = datos.get("dias_incluidos")
            if dias is None or dias <= 0:
                errores["dias_incluidos"] = (
                    "Un pase necesita saber cuántas entradas incluye."
                )

        return errores

    def guardar_plan(self, formulario: dict, id_plan: int | None = None) -> int:
        tipo = limpiar(formulario.get("tipo"))
        datos = {
            "nombre": limpiar(formulario.get("nombre")),
            "tipo": tipo,
            "precio": _a_decimal(formulario.get("precio")),
            "duracion": _a_entero(formulario.get("duracion")),
            "unidad_duracion": limpiar(formulario.get("unidad_duracion")) or MES,
            # Solo los pases guardan entradas; en los demás queda NULL.
            "dias_incluidos": (
                _a_entero(formulario.get("dias_incluidos")) if tipo == PASES else None
            ),
            "permite_pareja": formulario.get("permite_pareja") == "on",
            "permite_descuento": formulario.get("permite_descuento") == "on",
        }
        errores = self._validar_plan(datos, excluir_id=id_plan)
        if errores:
            raise ErrorValidacion(errores)

        if id_plan:
            self.planes.actualizar(id_plan, datos)
            return id_plan
        return self.planes.crear(datos)

    def cambiar_estado_plan(self, id_plan: int, activo: bool) -> None:
        self.planes.cambiar_estado(id_plan, activo)

    # --- Para "Cobrar" ------------------------------------------------

    def items_vendibles(self) -> dict:
        """Lo que puede aparecer en la lista única de Cobrar.

        Devuelve productos y planes activos por separado; la pantalla de
        cobro los muestra mezclados en un solo selector.
        """
        return {
            "productos": self.productos.listar(),
            "planes": self.planes.listar(),
        }
