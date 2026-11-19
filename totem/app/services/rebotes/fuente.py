"""De dónde salen los rebotes, visto desde el resto del sistema.

Un rebote es el aviso de que un correo no se pudo entregar. Hoy llega
como un mensaje al buzón del gimnasio, porque se envía por Gmail. Si
mañana el gimnasio pasa a un servicio de correo transaccional con
dominio propio, los rebotes llegan por otro camino —un webhook, una
consulta a su API— y lo único que debería cambiar es la clase que los
trae.

Por eso esto de acá es una interfaz y no una implementación: el
servicio que marca las facturas no sabe ni quiere saber si los
rebotes vinieron de un buzón IMAP o de una API. El buzón de hoy es
``buzon_imap.BuzonIMAP``; lo que venga después se escribe al lado,
implementando ``FuenteDeRebotes``, y se cambia una línea.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Rebote:
    """Un correo que no llegó.

    ``message_id`` es el del mensaje original, el que mandó el
    gimnasio; es lo que permite saber de qué factura se trata. Puede
    venir vacío: hay servidores que devuelven el rebote sin incluir el
    mensaje original, y entonces solo queda la dirección.
    """

    destinatario: str
    motivo: str
    ocurrido_en: datetime
    message_id: str = ""

    # Un rebote duro es definitivo: la dirección no existe. Uno blando
    # es temporal —buzón lleno, servidor caído— y no significa que el
    # correo esté mal escrito, así que no se marca al cliente por uno
    # de esos.
    definitivo: bool = True


class FuenteDeRebotes(ABC):
    """De aquí se sacan los rebotes, venga de donde venga."""

    @abstractmethod
    def configurada(self) -> bool:
        """¿Está lista para usarse? Sin esto no se intenta leer."""

    @abstractmethod
    def rebotes(self, desde: datetime) -> list[Rebote]:
        """Los rebotes ocurridos a partir de esa fecha.

        Puede devolver de más: el servicio descarta los repetidos. Lo
        que no debe hacer es devolver de menos, porque un rebote que
        no se lee no se lee nunca más.
        """
