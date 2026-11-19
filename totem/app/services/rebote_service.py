"""Qué se hace con un rebote cuando llega.

El envío de un correo no dice nada sobre si llegó. El servidor del
gimnasio lo acepta, responde que salió, y recién minutos después el
servidor del destinatario devuelve el aviso de que esa dirección no
existe. Ese aviso es lo único que confirma de verdad un correo malo, y
hasta ahora se perdía en un buzón que nadie mira.

Esto lo recoge y lo convierte en dos cosas útiles:

  * la factura queda marcada como no entregada, para que se vea en su
    pantalla y alguien pueda reenviarla a otra dirección
  * el cliente queda señalado, para que la próxima vez que venga al
    gimnasio alguien le pregunte el correo bueno

Cómo se casa un rebote con su factura: al enviar se guarda el
Message-ID en ``envios_correo``, y el rebote trae ese mismo
Message-ID. Es una coincidencia exacta, no una adivinanza. Cuando el
servidor que rebotó no lo devuelve —pasa—, se busca por dirección
entre los envíos recientes, y ahí sí es el más probable y no el
seguro; por eso se limita a una ventana de días y no se marca al
cliente si hay más de un candidato.

Un rebote temporal (buzón lleno, servidor caído) se anota en el envío
pero **no** marca al cliente: su correo está bien, el problema es del
otro lado y se arregla solo.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import current_app

from app.db import obtener_cursor
from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService
from app.services.rebotes.buzon_imap import BuzonIMAP
from app.services.rebotes.fuente import FuenteDeRebotes, Rebote

# Cuántos días hacia atrás se busca un envío cuando el rebote no trae
# el Message-ID. Más que esto empieza a casar con envíos viejos que no
# tienen nada que ver.
DIAS_DE_BUSQUEDA = 7

# Margen hacia atrás al releer el buzón. Sin esto, un rebote que llega
# con la fecha un poco corrida se saltearía para siempre.
MARGEN_HORAS = 6


class ReboteService:
    """Lee los rebotes y marca lo que corresponde."""

    def __init__(self, fuente: FuenteDeRebotes | None = None):
        # La fuente se puede cambiar: hoy es el buzón de Gmail, mañana
        # puede ser la API del servicio de correo transaccional.
        self.fuente = fuente if fuente is not None else BuzonIMAP()
        self.bitacora = BitacoraService()

    def configurado(self) -> bool:
        return self.fuente.configurada()

    def revisar(self, id_empleado: int | None = None) -> dict:
        """Una pasada completa. Devuelve el resumen de lo que hizo."""
        if not self.configurado():
            return {
                "configurado": False,
                "leidos": 0, "casados": 0, "clientes": 0, "sueltos": 0,
            }

        desde = self._desde_cuando()
        rebotes = self.fuente.rebotes(desde)

        casados = clientes = sueltos = 0
        for rebote in rebotes:
            resultado = self._procesar(rebote, id_empleado)
            if resultado == "casado":
                casados += 1
            elif resultado == "casado_y_cliente":
                casados += 1
                clientes += 1
            elif resultado == "suelto":
                sueltos += 1

        self._anotar_pasada()
        return {
            "configurado": True,
            "leidos": len(rebotes),
            "casados": casados,
            "clientes": clientes,
            "sueltos": sueltos,
        }

    # --- Un rebote -------------------------------------------------------

    def _procesar(self, rebote: Rebote, id_empleado: int | None) -> str:
        with obtener_cursor(commit=True) as cursor:
            envio = self._buscar_envio(cursor, rebote)
            if envio is None:
                return "suelto"

            if envio["estado"] == "REBOTADO":
                return "repetido"  # ya se había leído este rebote

            cursor.execute(
                "UPDATE envios_correo "
                "   SET estado = 'REBOTADO', motivo = %s, rebotado_en = %s "
                " WHERE id_envio = %s",
                (rebote.motivo[:400], rebote.ocurrido_en, envio["id_envio"]),
            )

            # La bitácora registra lo que hizo una persona, y un
            # rebote no lo hizo nadie: cuando la revisión corre sola,
            # desde la tarea programada, no hay empleado a quien
            # atribuirlo. El registro de que el correo no llegó está
            # igual en envios_correo, que es donde corresponde.
            if envio["id_factura"] and id_empleado:
                self._anotar_en_bitacora(rebote, envio, id_empleado)

            # Un rebote temporal no dice nada malo del correo del
            # cliente: no se lo marca.
            if rebote.definitivo and envio["id_cliente"]:
                cursor.execute(
                    "UPDATE clientes "
                    "   SET correo_rebotado_en = %s, correo_rebote_motivo = %s "
                    " WHERE id_cliente = %s",
                    (rebote.ocurrido_en, rebote.motivo[:400],
                     envio["id_cliente"]),
                )
                return "casado_y_cliente"
            return "casado"

    def _buscar_envio(self, cursor, rebote: Rebote) -> dict | None:
        """El envío al que corresponde este rebote, si se puede saber."""
        if rebote.message_id:
            cursor.execute(
                "SELECT id_envio, id_factura, id_cliente, estado "
                "  FROM envios_correo WHERE message_id = %s",
                (rebote.message_id,),
            )
            fila = cursor.fetchone()
            if fila:
                return dict(fila)

        # Sin Message-ID solo queda la dirección. Si hay más de un
        # envío reciente a esa dirección no se puede saber cuál rebotó;
        # se toma el más reciente para dejar constancia, pero esa
        # ambigüedad es la razón de la ventana corta.
        cursor.execute(
            "SELECT id_envio, id_factura, id_cliente, estado "
            "  FROM envios_correo "
            " WHERE LOWER(destinatario) = %s "
            "   AND enviado_en >= %s "
            "   AND estado <> 'REBOTADO' "
            " ORDER BY enviado_en DESC LIMIT 1",
            (rebote.destinatario.lower(),
             rebote.ocurrido_en - timedelta(days=DIAS_DE_BUSQUEDA)),
        )
        fila = cursor.fetchone()
        return dict(fila) if fila else None

    def _anotar_en_bitacora(self, rebote, envio, id_empleado) -> None:
        try:
            self.bitacora.registrar(
                id_empleado,
                bit.CORREO_REBOTADO,
                bit.FACTURA,
                envio["id_factura"],
                {
                    "destino": rebote.destinatario,
                    "motivo": rebote.motivo[:200],
                    "definitivo": rebote.definitivo,
                },
            )
        except Exception:  # noqa: BLE001
            # Que no se pueda anotar no debe impedir marcar la factura:
            # lo importante es que alguien vea que el correo no llegó.
            current_app.logger.exception("No se pudo anotar el rebote")

    # --- Hasta dónde se leyó ---------------------------------------------

    def _desde_cuando(self) -> datetime:
        with obtener_cursor() as cursor:
            cursor.execute("SELECT revisado_hasta FROM rebotes_revision")
            fila = cursor.fetchone()
        hasta = fila["revisado_hasta"] if fila else None
        if hasta is None:
            return datetime.now() - timedelta(days=DIAS_DE_BUSQUEDA)
        return hasta - timedelta(hours=MARGEN_HORAS)

    def _anotar_pasada(self) -> None:
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE rebotes_revision "
                "   SET revisado_hasta = NOW(), ultima_pasada = NOW()"
            )

    # --- Registro de los envíos ------------------------------------------

    @staticmethod
    def registrar_envio(
        destinatario: str,
        message_id: str,
        asunto: str = "",
        id_factura: int | None = None,
        id_cliente: int | None = None,
        cursor=None,
    ) -> None:
        """Deja constancia de un correo que salió.

        Sin esto no hay con qué casar el rebote después. Nunca debe
        hacer fallar un envío: si esta anotación revienta, el correo ya
        salió igual y lo único que se pierde es poder rastrear su
        rebote.
        """
        sentencia = (
            "INSERT INTO envios_correo "
            "  (id_factura, id_cliente, destinatario, asunto, message_id) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (message_id) DO NOTHING"
        )
        valores = (id_factura, id_cliente, destinatario[:120],
                   (asunto or "")[:200], (message_id or "")[:255] or None)
        try:
            if cursor is not None:
                cursor.execute(sentencia, valores)
            else:
                with obtener_cursor(commit=True) as propio:
                    propio.execute(sentencia, valores)
        except Exception:  # noqa: BLE001
            current_app.logger.exception("No se pudo registrar el envío")

    # --- Consultas para las pantallas ------------------------------------

    @staticmethod
    def de_la_factura(id_factura: int) -> list[dict]:
        """Los envíos de una factura, del más nuevo al más viejo."""
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT destinatario, asunto, enviado_en, estado, motivo, "
                "       rebotado_en "
                "  FROM envios_correo WHERE id_factura = %s "
                " ORDER BY enviado_en DESC",
                (id_factura,),
            )
            return [dict(f) for f in cursor.fetchall()]

    @staticmethod
    def clientes_con_correo_rebotado() -> list[dict]:
        """Clientes a los que hay que preguntarles el correo de nuevo."""
        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT id_cliente, nombre, apellido, correo, "
                "       correo_rebotado_en, correo_rebote_motivo "
                "  FROM clientes "
                " WHERE correo_rebotado_en IS NOT NULL "
                " ORDER BY correo_rebotado_en DESC"
            )
            return [dict(f) for f in cursor.fetchall()]

    @staticmethod
    def limpiar_marca(id_cliente: int, cursor=None) -> None:
        """Se le cambió el correo: la marca ya no corresponde."""
        sentencia = (
            "UPDATE clientes "
            "   SET correo_rebotado_en = NULL, correo_rebote_motivo = NULL "
            " WHERE id_cliente = %s"
        )
        if cursor is not None:
            cursor.execute(sentencia, (id_cliente,))
        else:
            with obtener_cursor(commit=True) as propio:
                propio.execute(sentencia, (id_cliente,))


__all__ = ["ReboteService", "bit"]
