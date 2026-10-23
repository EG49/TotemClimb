"""Servicio de bitácora.

Centraliza el registro de acciones para que las vistas no escriban
cadenas sueltas. Las constantes deben coincidir con los CHECK de la tabla.
"""

from app.repositories.bitacora_repo import BitacoraRepositorio

# Acciones permitidas (ver chk_bitacora_accion en el esquema)
CLIENTE_CREADO = "CLIENTE_CREADO"
CLIENTE_EDITADO = "CLIENTE_EDITADO"
FACTURA_EMITIDA = "FACTURA_EMITIDA"
FACTURA_ANULADA = "FACTURA_ANULADA"
ABONO_REGISTRADO = "ABONO_REGISTRADO"
INSCRIPCION_REGISTRADA = "INSCRIPCION_REGISTRADA"
INSCRIPCION_CANCELADA = "INSCRIPCION_CANCELADA"
IVA_CAMBIADO = "IVA_CAMBIADO"
ITEM_CREADO = "ITEM_CREADO"
ITEM_EDITADO = "ITEM_EDITADO"
ITEM_DESACTIVADO = "ITEM_DESACTIVADO"
ITEM_REACTIVADO = "ITEM_REACTIVADO"
EMPLEADO_CREADO = "EMPLEADO_CREADO"
EMPLEADO_EDITADO = "EMPLEADO_EDITADO"
EMPLEADO_DESACTIVADO = "EMPLEADO_DESACTIVADO"
EMPLEADO_REACTIVADO = "EMPLEADO_REACTIVADO"
PASSWORD_CAMBIADA = "PASSWORD_CAMBIADA"
CORREO_ENVIADO = "CORREO_ENVIADO"
CORREO_FALLIDO = "CORREO_FALLIDO"

# Entidades permitidas (ver chk_bitacora_entidad)
CLIENTE = "CLIENTE"
FACTURA = "FACTURA"
PAGO_FIADO = "PAGO_FIADO"
INSCRIPCION = "INSCRIPCION"
CONFIGURACION = "CONFIGURACION"
PRODUCTO = "PRODUCTO"
PLAN = "PLAN"
EMPLEADO = "EMPLEADO"


class BitacoraService:

    def __init__(self, repositorio: BitacoraRepositorio | None = None):
        self.repositorio = repositorio or BitacoraRepositorio()

    def registrar(
        self,
        id_empleado: int,
        accion: str,
        entidad: str,
        id_entidad: int | None = None,
        detalle: dict | None = None,
    ) -> None:
        self.repositorio.registrar(id_empleado, accion, entidad, id_entidad, detalle)

    def consultar(
        self,
        id_empleado: int | None = None,
        accion: str | None = None,
        limite: int = 100,
    ) -> list[dict]:
        return self.repositorio.listar(id_empleado, accion, limite)
