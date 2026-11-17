"""Envío de correos: comprobantes de venta y avisos de clases.

Tres decisiones que conviene entender antes de tocar este archivo:

  * **El envío nunca bloquea.** Sale en un hilo aparte. Si el servidor
    de correo tarda o se cae, el vendedor no se queda esperando con el
    cliente enfrente: la factura ya está guardada, y lo único que falla
    es el correo.
  * **El proveedor es intercambiable.** Aquí solo se habla SMTP. Pasar
    de Gmail a Brevo, a Resend o al servidor que sea es cambiar cuatro
    variables del .env, sin tocar este código.
  * **Un correo por persona.** Cuando hay varios destinatarios se manda
    un mensaje a cada uno, nunca todos en el "Para". Poner veinte
    direcciones juntas le entrega a cada cliente el correo de los otros
    diecinueve, que no es información suya.

El resultado de cada intento queda en la bitácora, el bueno y el malo.
"""

import smtplib
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from flask import current_app, render_template

from app.services import bitacora_service as bit
from app.services.bitacora_service import BitacoraService

# Si el servidor no responde en este tiempo, se corta el intento. Sin
# tope, un servidor que no contesta deja el hilo colgado para siempre.
TIEMPO_LIMITE_SEGUNDOS = 20

# Pausa entre mensajes de un envío múltiple. Gmail corta la conexión
# si se le disparan muchos seguidos; medio segundo basta y a nadie le
# molesta que veinte correos tarden diez segundos en salir.
PAUSA_ENTRE_ENVIOS = 0.5

# Hilos de envío en curso. Un proceso de larga vida (la aplicación) no
# necesita mirarlos: son demonios y viven lo que haga falta. Pero un
# script que termina enseguida —la tarea programada del recordatorio—
# mataría los envíos al salir, así que tiene que poder esperarlos.
#
# Se guardan acá y no se recorren todos los hilos del proceso: el pool
# de la base y el servidor también tienen hilos demonio, y esperarlos
# a ellos cuelga el script para siempre.
_hilos_en_curso: list[threading.Thread] = []
_candado_hilos = threading.Lock()


def _anotar_hilo(hilo: threading.Thread) -> None:
    with _candado_hilos:
        _hilos_en_curso[:] = [h for h in _hilos_en_curso if h.is_alive()]
        _hilos_en_curso.append(hilo)


def esperar_envios(segundos: float = 120) -> bool:
    """Espera a que salgan los correos en curso. Para scripts.

    Devuelve si terminaron todos dentro del plazo. La aplicación web
    nunca llama a esto: ahí el punto es justamente no esperar.
    """
    limite = time.monotonic() + segundos
    with _candado_hilos:
        pendientes = list(_hilos_en_curso)

    for hilo in pendientes:
        restante = limite - time.monotonic()
        if restante <= 0:
            return False
        hilo.join(timeout=restante)

    return all(not h.is_alive() for h in pendientes)


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
        mensaje["Subject"] = f"Comprobante {factura.numero_factura} — Totem Climb Gym"
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
        hilo = threading.Thread(
            target=self._enviar_en_segundo_plano,
            args=(app, mensaje, id_empleado, datos),
            daemon=True,
        )
        _anotar_hilo(hilo)
        hilo.start()
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
                datos.get("entidad", bit.FACTURA),
                datos.get("id_entidad", datos.get("id_factura")),
                {"numero": datos["numero"], "destino": datos["destino"], **extra},
            )
        except Exception:  # noqa: BLE001
            # Si ni siquiera la bitácora responde, no hay nada que hacer
            # desde un hilo de fondo. Queda en el log de la aplicación.
            current_app.logger.exception("No se pudo registrar el envío en la bitácora")

    # --- Correos de clases y eventos ----------------------------------

    def _armar_aviso(self, asunto, plantilla, contexto, destinatario) -> EmailMessage:
        a = self._ajustes()
        mensaje = EmailMessage()
        mensaje["Subject"] = asunto
        mensaje["From"] = formataddr((a["nombre"], a["remitente"]))
        mensaje["To"] = destinatario
        dominio = a["remitente"].split("@")[-1] if "@" in (a["remitente"] or "") else None
        mensaje["Message-ID"] = make_msgid(domain=dominio)

        mensaje.set_content(render_template(f"correo/{plantilla}.txt", **contexto))
        mensaje.add_alternative(
            render_template(f"correo/{plantilla}.html", **contexto), subtype="html"
        )
        return mensaje

    def enviar_aviso(
        self,
        destinatarios: list[dict],
        asunto: str,
        plantilla: str,
        contexto: dict,
        id_empleado: int,
        id_evento: int | None = None,
    ) -> int:
        """Manda un correo a cada destinatario y devuelve cuántos salieron.

        Cada destinatario es {"correo": ..., "nombre": ...}. Se arma un
        mensaje por persona, con su nombre adentro: además de no filtrar
        direcciones, el correo se lee como escrito para quien lo recibe.

        Devuelve enseguida; el envío ocurre en un hilo. El número que
        devuelve es a cuántos se les VA a escribir, no cuántos llegaron:
        eso no se sabe hasta que el servidor responde, y queda en la
        bitácora.
        """
        if not self.configurado():
            raise CorreoNoConfigurado("Falta configurar el correo en el archivo .env.")

        validos = [
            {"correo": d["correo"].strip(), "nombre": d.get("nombre") or ""}
            for d in destinatarios
            if (d.get("correo") or "").strip()
        ]
        if not validos:
            raise ValueError("Ninguno de ellos tiene correo registrado.")

        # Si la misma persona está dos veces, recibe un solo correo.
        vistos = set()
        unicos = []
        for d in validos:
            clave = d["correo"].lower()
            if clave not in vistos:
                vistos.add(clave)
                unicos.append(d)

        mensajes = [
            (
                d["correo"],
                self._armar_aviso(
                    asunto, plantilla, {**contexto, "destinatario": d}, d["correo"]
                ),
            )
            for d in unicos
        ]

        app = current_app._get_current_object()
        hilo = threading.Thread(
            target=self._enviar_lote,
            args=(app, mensajes, id_empleado, asunto, id_evento),
            daemon=True,
        )
        _anotar_hilo(hilo)
        hilo.start()
        return len(unicos)

    def _enviar_lote(self, app, mensajes, id_empleado, asunto, id_evento) -> None:
        """Manda los mensajes uno por uno. Un fallo no detiene al resto."""
        with app.app_context():
            enviados, fallados = [], []
            for destino, mensaje in mensajes:
                try:
                    self._entregar(mensaje)
                except Exception as error:  # noqa: BLE001
                    app.logger.warning(
                        "No se pudo enviar «%s» a %s: %s", asunto, destino, error
                    )
                    fallados.append({"destino": destino, "error": str(error)})
                else:
                    enviados.append(destino)
                time.sleep(PAUSA_ENTRE_ENVIOS)

            app.logger.info(
                "Aviso «%s»: %s enviados, %s fallidos",
                asunto, len(enviados), len(fallados),
            )

            # Una sola anotación por lote: veinte entradas iguales en la
            # bitácora la vuelven ilegible.
            datos = {
                "numero": asunto,
                "destino": f"{len(enviados)} destinatario(s)",
                "entidad": bit.EVENTO,
                "id_entidad": id_evento,
            }
            if enviados:
                self._registrar(
                    id_empleado, bit.CORREO_ENVIADO, datos,
                    {"enviados": enviados},
                )
            if fallados:
                self._registrar(
                    id_empleado, bit.CORREO_FALLIDO,
                    {**datos, "destino": f"{len(fallados)} fallaron"},
                    {"fallados": fallados},
                )
