"""Servicio de cobro: el corazón del sistema.

Reglas que viven aquí:

  * Los totales SIEMPRE se recalculan en el servidor a partir de los
    precios de la base. Lo que manda el navegador solo dice qué ítems y
    en qué cantidad, nunca cuánto cuestan.
  * Si cualquier ítem de la factura tiene permite_descuento = false, el
    descuento queda bloqueado para la factura completa.
  * Un plan con permite_pareja genera dos membresías enlazadas entre sí,
    desde la misma factura.
  * Una renovación anticipada arranca donde termina la vigencia actual,
    para que el cliente no pierda los días que le quedaban.
  * Una venta fiada queda PENDIENTE con su saldo; el monto recibido al
    momento se guarda como el primer abono.
  * Todo el cobro ocurre en una sola transacción.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.db import obtener_cursor
from app.models.catalogo import MES, PASES
from app.models.factura import (
    CENTAVO,
    EMITIDA,
    METODOS_PAGO,
    PENDIENTE,
    PLAN,
    PRODUCTO,
    LineaCobro,
    Totales,
)
from app.repositories.catalogo_repo import PlanRepositorio, ProductoRepositorio
from app.repositories.cliente_repo import ClienteRepositorio
from app.repositories.factura_repo import (
    ConfiguracionRepositorio,
    FacturaRepositorio,
    MembresiaRepositorio,
)
from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService
from app.services.validaciones import ErrorValidacion

CLAVE_IVA = "iva_porcentaje"
IVA_POR_DEFECTO = Decimal("15")
CANTIDAD_MAXIMA = 99


def sumar_meses(fecha: date, meses: int) -> date:
    """Suma meses respetando el fin de mes.

    El 31 de enero más un mes da 28 o 29 de febrero, no un error.
    """
    indice = fecha.month - 1 + meses
    anio = fecha.year + indice // 12
    mes = indice % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def _a_decimal(valor, por_defecto=None) -> Decimal | None:
    if valor is None or str(valor).strip() == "":
        return por_defecto
    try:
        return Decimal(str(valor).strip().replace(",", "."))
    except InvalidOperation:
        return None


class CobroService:

    def __init__(self):
        self.clientes = ClienteRepositorio()
        self.productos = ProductoRepositorio()
        self.planes = PlanRepositorio()
        self.facturas = FacturaRepositorio()
        self.membresias = MembresiaRepositorio()
        self.configuracion = ConfiguracionRepositorio()
        self.bitacora = BitacoraService()

    # --- Lectura ------------------------------------------------------

    def iva_vigente(self) -> Decimal:
        valor = self.configuracion.obtener(CLAVE_IVA)
        return _a_decimal(valor, IVA_POR_DEFECTO) or IVA_POR_DEFECTO

    def catalogo_para_cobrar(self) -> dict:
        """Productos y planes activos, para la lista única de la pantalla."""
        return {
            "productos": self.productos.listar(),
            "planes": self.planes.listar(),
        }

    # --- Armado de líneas ---------------------------------------------

    def _construir_lineas(self, items: list[dict]) -> tuple[list[LineaCobro], dict]:
        """Convierte lo que llegó del formulario en líneas con precio real.

        El precio NUNCA viene del navegador: se lee de la base.
        """
        lineas, errores = [], {}

        for indice, item in enumerate(items):
            tipo = item.get("tipo")
            id_item = item.get("id_item")
            cantidad = item.get("cantidad", 1)

            try:
                id_item = int(id_item)
                cantidad = int(cantidad)
            except (TypeError, ValueError):
                errores[f"item_{indice}"] = "Ítem inválido."
                continue

            if cantidad < 1 or cantidad > CANTIDAD_MAXIMA:
                errores[f"item_{indice}"] = (
                    f"La cantidad debe estar entre 1 y {CANTIDAD_MAXIMA}."
                )
                continue

            if tipo == PRODUCTO:
                producto = self.productos.obtener(id_item)
                if producto is None or not producto.activo:
                    errores[f"item_{indice}"] = "Ese producto ya no está disponible."
                    continue
                lineas.append(
                    LineaCobro(
                        tipo=PRODUCTO,
                        id_item=producto.id_producto,
                        nombre=producto.nombre,
                        precio_unitario=producto.precio,
                        cantidad=cantidad,
                    )
                )

            elif tipo == PLAN:
                plan = self.planes.obtener(id_item)
                if plan is None or not plan.activo:
                    errores[f"item_{indice}"] = "Ese plan ya no está disponible."
                    continue
                # Un plan se vende de a uno: dos membresías para la misma
                # persona no tendrían sentido. La promo de pareja ya
                # genera dos vigencias desde una sola línea.
                lineas.append(
                    LineaCobro(
                        tipo=PLAN,
                        id_item=plan.id_plan,
                        nombre=plan.nombre,
                        precio_unitario=plan.precio,
                        cantidad=1,
                        permite_descuento=plan.permite_descuento,
                        permite_pareja=plan.permite_pareja,
                    )
                )
            else:
                errores[f"item_{indice}"] = "Tipo de ítem desconocido."

        return lineas, errores

    # --- Cálculo ------------------------------------------------------

    def calcular(
        self, lineas: list[LineaCobro], descuento_porcentaje: Decimal = Decimal("0")
    ) -> Totales:
        subtotal = sum((l.subtotal for l in lineas), Decimal("0")).quantize(CENTAVO)

        if not self.permite_descuento(lineas):
            descuento_porcentaje = Decimal("0")

        descuento_monto = (subtotal * descuento_porcentaje / 100).quantize(CENTAVO)
        base = (subtotal - descuento_monto).quantize(CENTAVO)
        iva_pct = self.iva_vigente()
        iva = (base * iva_pct / 100).quantize(CENTAVO)

        return Totales(
            subtotal=subtotal,
            descuento_porcentaje=descuento_porcentaje,
            descuento_monto=descuento_monto,
            base_imponible=base,
            iva_porcentaje=iva_pct,
            iva=iva,
            total=(base + iva).quantize(CENTAVO),
        )

    def permite_descuento(self, lineas: list[LineaCobro]) -> bool:
        """Basta un ítem que no lo permita para bloquear toda la factura."""
        return all(l.permite_descuento for l in lineas)

    # --- Cobro --------------------------------------------------------

    def cobrar(self, formulario: dict, items: list[dict], id_empleado: int) -> int:
        lineas, errores = self._construir_lineas(items)

        if not lineas and not errores:
            errores["items"] = "Agrega al menos un ítem para cobrar."

        # Cliente
        id_cliente = None
        try:
            id_cliente = int(formulario.get("id_cliente") or 0)
        except (TypeError, ValueError):
            pass
        cliente = self.clientes.obtener(id_cliente) if id_cliente else None
        if cliente is None:
            errores["id_cliente"] = "Elige un cliente."

        # Pareja: solo si hay un plan que la permita
        linea_pareja = next((l for l in lineas if l.permite_pareja), None)
        cliente_pareja = None
        if linea_pareja is not None:
            try:
                id_pareja = int(formulario.get("id_cliente_pareja") or 0)
            except (TypeError, ValueError):
                id_pareja = 0
            cliente_pareja = self.clientes.obtener(id_pareja) if id_pareja else None
            if cliente_pareja is None:
                errores["id_cliente_pareja"] = (
                    f"'{linea_pareja.nombre}' es para dos personas: elige la segunda."
                )
            elif cliente is not None and cliente_pareja.id_cliente == cliente.id_cliente:
                errores["id_cliente_pareja"] = (
                    "La segunda persona debe ser distinta del titular."
                )

        # Descuento
        descuento = Decimal("0")
        if formulario.get("aplica_descuento") == "on":
            descuento = _a_decimal(formulario.get("descuento_porcentaje"))
            if descuento is None or descuento < 0 or descuento > 100:
                errores["descuento_porcentaje"] = "El descuento debe ir entre 0 y 100."
                descuento = Decimal("0")
            elif lineas and not self.permite_descuento(lineas):
                bloqueantes = [l.nombre for l in lineas if not l.permite_descuento]
                errores["descuento_porcentaje"] = (
                    f"'{bloqueantes[0]}' no permite descuento, así que no se "
                    "puede aplicar a esta factura."
                )

        if errores:
            raise ErrorValidacion(errores)

        totales = self.calcular(lineas, descuento)

        # Forma de cobro
        fiar = formulario.get("forma_cobro") == "fiar"
        metodo = formulario.get("metodo_pago")
        monto_recibido = Decimal("0")

        if fiar:
            monto_recibido = _a_decimal(formulario.get("monto_recibido"), Decimal("0"))
            if monto_recibido is None or monto_recibido < 0:
                errores["monto_recibido"] = "El monto recibido no es válido."
            elif monto_recibido >= totales.total:
                errores["monto_recibido"] = (
                    "Si cubre el total, cobra completo en vez de fiar."
                )
            if monto_recibido and metodo not in METODOS_PAGO:
                errores["metodo_pago"] = "Elige con qué se recibió el abono."
        else:
            if metodo not in METODOS_PAGO:
                errores["metodo_pago"] = "Elige la forma de pago."

        if errores:
            raise ErrorValidacion(errores)

        estado = PENDIENTE if fiar else EMITIDA
        saldo = (totales.total - monto_recibido).quantize(CENTAVO) if fiar else Decimal("0")

        # --- Transacción ---
        with obtener_cursor(commit=True) as cursor:
            numero = self.facturas.siguiente_numero(cursor)
            id_factura = self.facturas.crear(
                {
                    "numero_factura": numero,
                    "id_cliente": cliente.id_cliente,
                    "id_empleado": id_empleado,
                    # Una fiada sin abono inicial no tiene método todavía.
                    "metodo_pago": metodo if (not fiar or monto_recibido) else None,
                    "descuento_porcentaje": totales.descuento_porcentaje,
                    "iva_porcentaje": totales.iva_porcentaje,
                    "subtotal": totales.subtotal,
                    "iva": totales.iva,
                    "total": totales.total,
                    "estado": estado,
                    "saldo_pendiente": saldo,
                },
                cursor,
            )

            clientes_tocados = set()

            for linea in lineas:
                self.facturas.agregar_detalle(
                    id_factura,
                    None if linea.es_plan else linea.id_item,
                    linea.id_item if linea.es_plan else None,
                    linea.cantidad,
                    linea.precio_unitario,
                    linea.subtotal,
                    cursor,
                )

                if linea.es_plan:
                    plan = self.planes.obtener(linea.id_item)
                    ids = [cliente.id_cliente]
                    if linea.permite_pareja and cliente_pareja is not None:
                        ids.append(cliente_pareja.id_cliente)

                    creadas = []
                    for id_c in ids:
                        creadas.append(
                            self._crear_membresia(plan, id_c, id_factura, cursor)
                        )
                        clientes_tocados.add(id_c)

                    if len(creadas) == 2:
                        self.membresias.enlazar_pareja(creadas[0], creadas[1], cursor)

            if fiar and monto_recibido > 0:
                self.facturas.registrar_abono(
                    id_factura, id_empleado, monto_recibido, metodo, cursor
                )

            for id_c in clientes_tocados:
                self.membresias.actualizar_cache_cliente(id_c, cursor)

        self.bitacora.registrar(
            id_empleado,
            bit.FACTURA_EMITIDA,
            bit.FACTURA,
            id_factura,
            {
                "numero": numero,
                "cliente": cliente.nombre_completo,
                "total": str(totales.total),
                "estado": estado,
                "items": [f"{l.cantidad}x {l.nombre}" for l in lineas],
            },
        )
        return id_factura

    def _crear_membresia(self, plan, id_cliente: int, id_factura: int, cursor) -> int:
        """Crea la vigencia de un plan para un cliente.

        Si el cliente todavía tiene una membresía activa, la nueva empieza
        el día en que termina esa, para no quitarle los días pagados.
        """
        hoy = date.today()
        fin_actual = self.membresias.fin_vigencia_actual(id_cliente, cursor)
        inicio = fin_actual if (fin_actual and fin_actual >= hoy) else hoy

        if plan.unidad_duracion == MES:
            fin = sumar_meses(inicio, plan.duracion)
        else:
            fin = inicio + timedelta(days=plan.duracion)

        # Las entradas solo aplican a los pases.
        dias = plan.dias_incluidos if plan.tipo == PASES else None

        return self.membresias.crear(
            {
                "id_cliente": id_cliente,
                "id_plan": plan.id_plan,
                "id_factura": id_factura,
                "fecha_inicio": inicio,
                "fecha_fin": fin,
                "dias_totales": dias,
                "dias_restantes": dias,
            },
            cursor,
        )
