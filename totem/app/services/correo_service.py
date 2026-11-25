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
            # Suman de arriba abajo; el subtotal con IVA solo si hubo
            # descuento, porque si no es igual al total.
            *([f"Subtotal con IVA: ${factura.subtotal:.2f}"]
              if factura.descuento_porcentaje else []),
            f"Base imponible: ${factura.base_imponible:.2f}",
            f"IVA {factura.iva_porcentaje}% incluido: ${factura.iva:.2f}",
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

    # --- Correo con archivos adjuntos ----------------------------------

    def armar_con_adjuntos(
        self,
        destinatario: str,
        asunto: str,
        texto: str,
        adjuntos: list[tuple[str, bytes, str, str]],
        html: str | None = None,
    ) -> EmailMessage:
        """Un correo con archivos encima.

        `adjuntos` son tuplas (nombre, contenido, tipo, subtipo), por
        ejemplo ("factura.pdf", b"...", "application", "pdf").

        Existe para la factura electrónica: al cliente hay que
        mandarle el XML autorizado Y el RIDE en PDF. El XML es la
        factura ante el SRI y el PDF es la que se lee; entregar solo
        uno de los dos deja al cliente a medias.
        """
        ajustes = self._ajustes()
        mensaje = EmailMessage()
        mensaje["Subject"] = asunto
        mensaje["From"] = formataddr((ajustes["nombre"], ajustes["remitente"]))
        mensaje["To"] = destinatario
        remitente = ajustes["remitente"] or ""
        dominio = remitente.split("@")[-1] if "@" in remitente else None
        mensaje["Message-ID"] = make_msgid(domain=dominio)

        mensaje.set_content(texto)
        if html:
            mensaje.add_alternative(html, subtype="html")

        for nombre, contenido, tipo, subtipo in adjuntos:
            mensaje.add_attachment(
                contenido, maintype=tipo, subtype=subtipo, filename=nombre
            )
        return mensaje

    def enviar_con_adjuntos(
        self,
        destinatario: str,
        asunto: str,
        texto: str,
        adjuntos: list[tuple[str, bytes, str, str]],
        html: str | None = None,
    ) -> None:
        """Arma y entrega en el acto, sin hilo.

        A diferencia de enviar_comprobante(), este espera: quien lo
        llama quiere saber si salió. Para el envío desde una pantalla
        hace falta la versión en segundo plano.
        """
        if not self.configurado():
            raise CorreoNoConfigurado(
                "Falta configurar el correo en el archivo .env."
            )
        self._entregar(
            self.armar_con_adjuntos(
                destinatario, asunto, texto, adjuntos, html
            )
        )

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
            "id_cliente": getattr(factura, "id_cliente", None),
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

    # --- Factura electrónica -------------------------------------

    def enviar_factura(
        self, factura, id_empleado: int, destinatario: str | None = None
    ) -> tuple[str, bool, str | None]:
        """Manda la factura del SRI si existe, y si no el comprobante.

        Devuelve a quién se le manda, si salió la factura electrónica,
        y cuando no salió, por qué: "autorizandose" si el comprobante
        sigue en camino, "sin_comprobante" si esa factura no tiene.
        Sirve para que la pantalla lo explique en lugar de dejar a
        quien cobra adivinando cuál de los dos correos salió.

        El mismo botón hace las dos cosas a propósito: quien cobra no
        tiene por qué saber en qué estado quedó el comprobante ante el
        SRI, ni elegir entre dos envíos parecidos. Si la factura está
        autorizada se manda esa, que es la que vale; si todavía no, se
        manda el comprobante interno, que es lo que hay.

        Si el comprobante todavía se está autorizando, espera unos
        segundos antes de rendirse. Entre cobrar y pulsar "Enviar"
        pasan uno o dos segundos, y la autorización tarda más: sin
        esta espera, el correo caía siempre en el comprobante interno
        justo cuando mas se queria la factura, y al rato la factura ya
        estaba autorizada.
        """
        self._esperar_autorizacion(factura)
        electronica = self._factura_electronica(factura)
        if electronica is None:
            destino = self.enviar_comprobante(
                factura, id_empleado, destinatario
            )
            return destino, False, self._por_que_no(factura)

        if not self.configurado():
            raise CorreoNoConfigurado(
                "Falta configurar el correo en el archivo .env."
            )
        destino = (destinatario or factura.cliente_correo or "").strip()
        if not destino:
            raise ValueError("Este cliente no tiene un correo registrado.")

        pdf, autorizacion, numero = electronica
        from flask import render_template

        asunto = f"Factura {numero} — Totem Climb Gym"
        if autorizacion.es_prueba:
            asunto = f"[PRUEBA] {asunto}"

        html = render_template(
            "correo/factura_electronica.html",
            factura=factura,
            numero=numero,
            autorizacion=autorizacion.numero,
            es_prueba=autorizacion.es_prueba,
        )
        texto = (
            f"Factura {numero} — Totem Climb Gym\n\n"
            f"Adjuntamos su factura electrónica autorizada por el SRI en "
            f"dos archivos: el PDF, para leer o imprimir, y el XML, que "
            f"es el comprobante oficial.\n\n"
            f"Total: ${factura.total:.2f}\n\n"
            f"Número de autorización:\n{autorizacion.numero}\n\n"
            f"Puede verificarla en www.sri.gob.ec con esa clave de acceso.\n"
        )

        mensaje = self.armar_con_adjuntos(
            destino, asunto, texto,
            [
                (f"{autorizacion.numero}.pdf", pdf, "application", "pdf"),
                (f"{autorizacion.numero}.xml",
                 autorizacion.comprobante.encode("utf-8"), "application", "xml"),
            ],
            html=html,
        )

        app = current_app._get_current_object()
        datos = {
            "numero": factura.numero_factura,
            "id_factura": factura.id_factura,
            "id_cliente": getattr(factura, "id_cliente", None),
            "destino": destino,
            "autorizacion": autorizacion.numero,
        }
        hilo = threading.Thread(
            target=self._enviar_en_segundo_plano,
            args=(app, mensaje, id_empleado, datos),
            daemon=True,
        )
        _anotar_hilo(hilo)
        hilo.start()
        return destino, True, None

    @staticmethod
    def _por_que_no(factura) -> str:
        """Por qué no salió la factura electrónica."""
        from app.db import obtener_cursor

        with obtener_cursor() as cursor:
            cursor.execute(
                "SELECT sri_estado FROM facturas WHERE id_factura = %s",
                (factura.id_factura,),
            )
            fila = cursor.fetchone()
        estado = fila["sri_estado"] if fila else None
        if estado in ("PENDIENTE", "FIRMADA", "ENVIADA"):
            return "autorizandose"
        return "sin_comprobante"

    @staticmethod
    def _esperar_autorizacion(factura, segundos: float = 12) -> None:
        """Le da tiempo al SRI, si el comprobante va en camino.

        Solo espera mientras el comprobante esté en vuelo. Si ya está
        resuelto —autorizado o rechazado— vuelve en el acto, y si la
        factura no tiene comprobante tampoco espera: no hay nada que
        esperar.
        """
        import time

        from app.db import obtener_cursor

        EN_VUELO = ("PENDIENTE", "FIRMADA", "ENVIADA")
        limite = time.monotonic() + segundos
        while True:
            with obtener_cursor() as cursor:
                cursor.execute(
                    "SELECT sri_estado FROM facturas WHERE id_factura = %s",
                    (factura.id_factura,),
                )
                fila = cursor.fetchone()
            estado = fila["sri_estado"] if fila else None
            if estado not in EN_VUELO:
                return
            if time.monotonic() >= limite:
                current_app.logger.info(
                    "SRI: la factura %s seguía en %s al mandar el correo; "
                    "sale el comprobante interno",
                    factura.numero_factura, estado,
                )
                return
            time.sleep(1)

    @staticmethod
    def _factura_electronica(factura):
        """El RIDE y la autorización, o None si todavía no hay factura.

        Se arma desde la respuesta del SRI que quedó guardada, no desde
        los datos del sistema: lo que recibe el cliente tiene que ser
        lo que el SRI autorizó. Ver app/services/sri/ride.py.
        """
        from app.db import obtener_cursor
        from app.services.sri.ride import ErrorRide, generar_desde_respuesta

        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT sri_estado, sri_xml, sri_establecimiento,
                       sri_punto_emision, sri_secuencial
                  FROM facturas WHERE id_factura = %s
                """,
                (factura.id_factura,),
            )
            fila = cursor.fetchone()

        if fila is None or fila["sri_estado"] != "AUTORIZADA" or not fila["sri_xml"]:
            return None

        try:
            pdf, autorizacion = generar_desde_respuesta(fila["sri_xml"])
        except ErrorRide as error:
            current_app.logger.warning(
                "No se pudo armar el RIDE de la factura %s: %s",
                factura.numero_factura, error,
            )
            return None

        numero = (
            f"{fila['sri_establecimiento']}-{fila['sri_punto_emision']}-"
            f"{str(fila['sri_secuencial']).zfill(9)}"
        )
        return pdf, autorizacion, numero

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
                # Que el servidor lo haya aceptado no quiere decir que
                # haya llegado. Se guarda el Message-ID para poder
                # reconocer el rebote si vuelve.
                self._anotar_envio(mensaje, datos)

    @staticmethod
    def _anotar_envio(mensaje: EmailMessage, datos: dict) -> None:
        """Deja el mensaje anotado para poder casarlo con su rebote."""
        from app.services.rebote_service import ReboteService

        ReboteService.registrar_envio(
            destinatario=datos["destino"],
            message_id=mensaje.get("Message-ID", ""),
            asunto=mensaje.get("Subject", ""),
            id_factura=datos.get("id_factura"),
            id_cliente=datos.get("id_cliente"),
        )

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
