"""Envío de comprobantes por correo.

Dos decisiones que conviene entender antes de tocar este archivo:

  * **El envío nunca bloquea el cobro.** Sale en un hilo aparte. Si el
    servidor de correo tarda o se cae, el vendedor no se queda esperando
    con el cliente enfrente: la factura ya está guardada, y lo único que
    falla es el correo.
  * **El proveedor es intercambiable.** Aquí solo se habla SMTP. Pasar
    de Gmail a Brevo, a Resend o al servidor que sea es cambiar cuatro
    variables del .env, sin tocar este código.

El resultado de cada intento queda en la bitácora, el bueno y el malo.
"""

import smtplib
import threading
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from flask import current_app, render_template

from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService

# Si el servidor no responde en este tiempo, se corta el intento. Sin
# tope, un servidor que no contesta deja el hilo colgado para siempre.
TIEMPO_LIMITE_SEGUNDOS = 20


class CorreoNoConfigurado(Exception):
    """Falta el .env del correo. No es un error del usuario."""


class ServicioCorreo:

    def __init__(self, bitacora=None):
        self.bitacora = bitacora or BitacoraService()

    # --- Configuración ------------------------------------------------

    @staticmethod
    def _ajustes() -> dict:
        c = current_app.config
        return {
            "servidor": c.get("MAIL_SERVIDOR"),
            "puerto": c.get("MAIL_PUERTO"),
            "usuario": c.get("MAIL_USUARIO"),
            "password": c.get("MAIL_PASSWORD"),
            "remitente": c.get("MAIL_REMITENTE") or c.get("MAIL_USUARIO"),
            "nombre": c.get("MAIL_NOMBRE_REMITENTE"),
            "tls": c.get("MAIL_TLS"),
        }

    @classmethod
    def configurado(cls) -> bool:
        a = cls._ajustes()
        return all([a["servidor"], a["puerto"], a["usuario"], a["password"]])

    # --- Armado del mensaje -------------------------------------------

    def _armar(self, factura, destinatario: str) -> EmailMessage:
        a = self._ajustes()
        mensaje = EmailMessage()
        mensaje["Subject"] = f"Tu comprobante {factura.numero_factura} — Totem Climb Gym"
        mensaje["From"] = formataddr((a["nombre"], a["remitente"]))
        mensaje["To"] = destinatario
        # Un Message-ID propio ayuda a que los clientes de correo no
        # agrupen comprobantes distintos en una misma conversación.
        # El dominio sale del remitente: sin él, make_msgid() escribe
        # "@localhost", que varios filtros antispam penalizan.
        dominio = a["remitente"].split("@")[-1] if "@" in (a["remitente"] or "") else None
        mensaje["Message-ID"] = make_msgid(domain=dominio)

        cuerpo_html = render_template("correo/comprobante.html", factura=factura)
        mensaje.set_content(self._version_texto(factura))
        mensaje.add_alternative(cuerpo_html, subtype="html")
        return mensaje

    @staticmethod
    def _version_texto(factura) -> str:
        """Alternativa en texto plano.

        No es decorativa: sin ella, varios filtros marcan el mensaje como
        sospechoso, y algunos clientes de correo no muestran nada.
        """
        lineas = [
            f"Comprobante {factura.numero_factura}",
            f"Totem Climb Gym — {factura.fecha.strftime('%d/%m/%Y %H:%M')}",
            "",
            f"Cliente: {factura.cliente_nombre}",
            "",
        ]
        for d in factura.detalle:
            lineas.append(
                f"  {d['cantidad']} x {d['nombre']}  ${d['subtotal']:.2f}"
            )
        lineas += [
            "",
            f"Subtotal: ${factura.subtotal:.2f}",
            f"IVA {factura.iva_porcentaje}%: ${factura.iva:.2f}",
            f"TOTAL: ${factura.total:.2f}",
        ]
        if factura.esta_fiada:
            lineas.append(f"Saldo pendiente: ${factura.saldo_pendiente:.2f}")
        lineas += [
            "",
            "Documento interno de control. No constituye comprobante de",
            "venta autorizado por el SRI.",
        ]
        return "\n".join(lineas)

    # --- Envío ---------------------------------------------------------

    def _entregar(self, mensaje: EmailMessage) -> None:
        a = self._ajustes()
        with smtplib.SMTP(
            a["servidor"], a["puerto"], timeout=TIEMPO_LIMITE_SEGUNDOS
        ) as smtp:
            if a["tls"]:
                smtp.starttls()
            if a["password"]:
                smtp.login(a["usuario"], a["password"])
            smtp.send_message(mensaje)

    def enviar_comprobante(
        self, factura, id_empleado: int, destinatario: str | None = None
    ) -> str:
        """Deja el envío en marcha y devuelve a quién se le va a mandar.

        Devuelve enseguida: el envío ocurre en un hilo. Lo que puede
        fallar aquí mismo son los datos (sin configuración, sin correo
        del cliente), no la red.
        """
        if not self.configurado():
            raise CorreoNoConfigurado(
                "Falta configurar el correo en el archivo .env."
            )

        destino = (destinatario or factura.cliente_correo or "").strip()
        if not destino:
            raise ValueError("Este cliente no tiene un correo registrado.")

        mensaje = self._armar(factura, destino)

        # El hilo necesita su propio contexto: el de la petición ya no
        # existe cuando el correo sale.
        app = current_app._get_current_object()
        datos = {
            "numero": factura.numero_factura,
            "id_factura": factura.id_factura,
            "destino": destino,
        }
        threading.Thread(
            target=self._enviar_en_segundo_plano,
            args=(app, mensaje, id_empleado, datos),
            daemon=True,
        ).start()
        return destino

    def _enviar_en_segundo_plano(self, app, mensaje, id_empleado, datos) -> None:
        with app.app_context():
            try:
                self._entregar(mensaje)
            except Exception as error:  # noqa: BLE001
                # Se atrapa todo a propósito: este hilo no tiene a quién
                # propagarle la excepción, y perder el registro sería
                # peor que el fallo mismo.
                app.logger.warning(
                    "No se pudo enviar el comprobante %s a %s: %s",
                    datos["numero"], datos["destino"], error,
                )
                self._registrar(
                    id_empleado, bit.CORREO_FALLIDO, datos,
                    {"error": f"{type(error).__name__}: {error}"},
                )
            else:
                app.logger.info(
                    "Comprobante %s enviado a %s", datos["numero"], datos["destino"]
                )
                self._registrar(id_empleado, bit.CORREO_ENVIADO, datos, {})

    def _registrar(self, id_empleado, accion, datos, extra) -> None:
        try:
            self.bitacora.registrar(
                id_empleado,
                accion,
                bit.FACTURA,
                datos["id_factura"],
                {"numero": datos["numero"], "destino": datos["destino"], **extra},
            )
        except Exception:  # noqa: BLE001
            # Si ni siquiera la bitácora responde, no hay nada que hacer
            # desde un hilo de fondo. Queda en el log de la aplicación.
            current_app.logger.exception("No se pudo registrar el envío en la bitácora")
