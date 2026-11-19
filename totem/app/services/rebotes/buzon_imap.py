"""Lee los rebotes del buzón del gimnasio por IMAP.

Cuando un correo no se puede entregar, el servidor del destinatario
devuelve un mensaje al remitente. Ese mensaje llega al buzón de
``MAIL_REMITENTE`` y tiene una forma estandarizada: un contenedor
``multipart/report`` con tres partes, de las cuales dos importan:

  * ``message/delivery-status``: campos legibles por máquina. Ahí está
    ``Final-Recipient`` (a quién no se le pudo entregar), ``Status``
    (un código como 5.1.1) y ``Diagnostic-Code`` (lo que dijo el
    servidor con sus palabras).
  * ``message/rfc822`` o ``text/rfc822-headers``: el mensaje original,
    o al menos sus cabeceras. De ahí sale el ``Message-ID``, que es lo
    que permite decir de qué factura era.

El primer dígito del ``Status`` es lo que decide si el rebote es
definitivo: 5 es permanente (la dirección no existe), 4 es temporal
(buzón lleno, servidor caído). Un rebote temporal no quiere decir que
el correo esté mal escrito y no debe marcar al cliente.

No todos los rebotes vienen tan prolijos. Algunos servidores mandan un
texto suelto sin estructura; para esos hay una lectura de respaldo que
busca la dirección y el código en el texto. Es menos confiable, así
que solo se usa cuando la forma estandarizada no está.

Este archivo **solo lee**. No borra nada del buzón ni lo marca como
leído: si alguien abre ese correo desde el teléfono, debe seguir
viendo lo mismo. Para no releer el buzón entero cada vez, el servicio
recuerda hasta qué fecha llegó.
"""

from __future__ import annotations

import email
import imaplib
import re
from datetime import datetime, timedelta
from email.message import Message

from flask import current_app

from app.services.rebotes.fuente import FuenteDeRebotes, Rebote

TIEMPO_LIMITE = 30  # segundos

# Direcciones desde las que llegan los rebotes. No se filtra por esto
# —se filtra por la forma del mensaje— pero sirve para la búsqueda.
REMITENTES_DE_REBOTE = ("mailer-daemon", "postmaster")

RE_DIRECCION = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
RE_ESTADO = re.compile(r"^Status:\s*([245])\.\d+\.\d+", re.M | re.I)
RE_FINAL = re.compile(r"^Final-Recipient:\s*[^;]*;\s*(.+)$", re.M | re.I)
RE_ORIGINAL = re.compile(r"^Original-Recipient:\s*[^;]*;\s*(.+)$", re.M | re.I)
RE_DIAGNOSTICO = re.compile(r"^Diagnostic-Code:\s*[^;]*;\s*(.+)$", re.M | re.I)


class BuzonIMAP(FuenteDeRebotes):
    """Los rebotes que haya en el buzón de salida del gimnasio."""

    def _ajustes(self) -> dict:
        cfg = current_app.config
        return {
            "servidor": cfg.get("IMAP_SERVIDOR", ""),
            "puerto": int(cfg.get("IMAP_PUERTO", 993) or 993),
            "usuario": cfg.get("IMAP_USUARIO", "") or cfg.get("MAIL_USUARIO", ""),
            "password": cfg.get("IMAP_PASSWORD", "") or cfg.get("MAIL_PASSWORD", ""),
            "carpeta": cfg.get("IMAP_CARPETA", "INBOX") or "INBOX",
        }

    def configurada(self) -> bool:
        a = self._ajustes()
        return bool(a["servidor"] and a["usuario"] and a["password"])

    def rebotes(self, desde: datetime) -> list[Rebote]:
        if not self.configurada():
            return []

        a = self._ajustes()
        encontrados: list[Rebote] = []

        # Un día de margen: IMAP busca por fecha sin hora, y el huso
        # del servidor de correo no tiene por qué ser el de acá.
        criterio = (desde - timedelta(days=1)).strftime("%d-%b-%Y")

        buzon = imaplib.IMAP4_SSL(
            a["servidor"], a["puerto"], timeout=TIEMPO_LIMITE
        )
        try:
            buzon.login(a["usuario"], a["password"])
            # readonly: que abrir el buzón no marque nada como leído.
            buzon.select(a["carpeta"], readonly=True)

            estado, respuesta = buzon.search(None, "SINCE", criterio)
            if estado != "OK":
                return []

            for numero in respuesta[0].split():
                # BODY.PEEK en lugar de BODY: leer sin marcar leído.
                estado, datos = buzon.fetch(numero, "(BODY.PEEK[])")
                if estado != "OK" or not datos or not isinstance(datos[0], tuple):
                    continue
                mensaje = email.message_from_bytes(datos[0][1])
                rebote = self._leer(mensaje)
                if rebote and rebote.ocurrido_en >= desde:
                    encontrados.append(rebote)
        finally:
            try:
                buzon.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                buzon.logout()
            except Exception:  # noqa: BLE001
                pass

        return encontrados

    # --- Lectura de un mensaje -----------------------------------------

    def _leer(self, mensaje: Message) -> Rebote | None:
        """Devuelve el rebote, o None si el mensaje no es un rebote."""
        cuando = self._fecha(mensaje)

        informe = self._parte(mensaje, "message/delivery-status")
        if informe is not None:
            rebote = self._leer_informe(informe, mensaje, cuando)
            if rebote:
                return rebote

        return self._leer_a_mano(mensaje, cuando)

    def _leer_informe(
        self, informe: Message, completo: Message, cuando: datetime
    ) -> Rebote | None:
        texto = self._texto_de_informe(informe)

        direccion = self._primer_grupo(RE_FINAL, texto) or \
            self._primer_grupo(RE_ORIGINAL, texto)
        if direccion:
            hallado = RE_DIRECCION.search(direccion)
            direccion = hallado.group(0) if hallado else ""
        if not direccion:
            return None

        estado = RE_ESTADO.search(texto)
        definitivo = estado.group(1) == "5" if estado else True

        motivo = self._primer_grupo(RE_DIAGNOSTICO, texto) or ""
        if not motivo and estado:
            motivo = f"El servidor respondió {estado.group(0).split()[-1]}"

        return Rebote(
            destinatario=direccion.strip().lower(),
            motivo=motivo.strip()[:400] or "No se pudo entregar.",
            ocurrido_en=cuando,
            message_id=self._message_id_original(completo),
            definitivo=definitivo,
        )

    def _leer_a_mano(self, mensaje: Message, cuando: datetime) -> Rebote | None:
        """Para los servidores que mandan el rebote como texto suelto.

        Menos confiable que el informe estandarizado, por eso solo se
        usa cuando aquel no está, y solo si el mensaje viene de un
        demonio de correo: sin esa condición, cualquier respuesta
        automática de vacaciones se leería como un rebote.
        """
        de = (mensaje.get("From") or "").lower()
        if not any(r in de for r in REMITENTES_DE_REBOTE):
            return None

        cuerpo = self._texto_de(mensaje)
        original = self._message_id_original(mensaje)

        remitente_propio = (mensaje.get("To") or "").lower()
        candidatas = [
            d for d in RE_DIRECCION.findall(cuerpo)
            if d.lower() not in remitente_propio
            and not any(r in d.lower() for r in REMITENTES_DE_REBOTE)
        ]
        if not candidatas:
            return None

        estado = RE_ESTADO.search(cuerpo)
        return Rebote(
            destinatario=candidatas[0].strip().lower(),
            motivo=self._resumen(cuerpo),
            ocurrido_en=cuando,
            message_id=original,
            definitivo=estado.group(1) == "5" if estado else True,
        )

    # --- Ayudas ---------------------------------------------------------

    @staticmethod
    def _primer_grupo(patron: re.Pattern, texto: str) -> str:
        hallado = patron.search(texto)
        return hallado.group(1).strip() if hallado else ""

    @staticmethod
    def _parte(mensaje: Message, tipo: str) -> Message | None:
        for parte in mensaje.walk():
            if parte.get_content_type() == tipo:
                return parte
        return None

    @staticmethod
    def _texto_de_informe(informe: Message) -> str:
        """El informe de entrega, como texto con sus campos.

        Hay que escribirlo aparte y no reutilizar _texto_de porque
        Python representa un message/delivery-status como una lista de
        sub-mensajes cuyos campos -- Final-Recipient, Status,
        Diagnostic-Code -- son CABECERAS, no cuerpo. Leerlo como
        cuerpo devuelve la cadena vacia, el rebote parece no tener
        informe y se cae al respaldo de texto suelto, que adivina. Fue
        exactamente lo que pasaba.
        """
        partes = informe.get_payload()
        if not isinstance(partes, list):
            return BuzonIMAP._texto_de(informe)

        lineas = []
        for sub in partes:
            if isinstance(sub, Message):
                lineas.extend(f"{campo}: {valor}" for campo, valor in sub.items())
            else:
                lineas.append(str(sub))
        return "\n".join(lineas)

    @staticmethod
    def _texto_de(parte: Message) -> str:
        """El texto de una parte, sin reventar por una codificación rara."""
        if parte.is_multipart():
            return "\n".join(
                BuzonIMAP._texto_de(sub) for sub in parte.get_payload()
                if isinstance(sub, Message)
            )
        try:
            crudo = parte.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            return ""
        if crudo is None:
            contenido = parte.get_payload()
            return contenido if isinstance(contenido, str) else ""
        juego = parte.get_content_charset() or "utf-8"
        return crudo.decode(juego, errors="replace")

    def _message_id_original(self, mensaje: Message) -> str:
        """El Message-ID del correo que el gimnasio había mandado."""
        for tipo in ("message/rfc822", "text/rfc822-headers"):
            parte = self._parte(mensaje, tipo)
            if parte is None:
                continue
            contenido = parte.get_payload()
            if isinstance(contenido, list) and contenido:
                interno = contenido[0]
                if isinstance(interno, Message) and interno.get("Message-ID"):
                    return interno["Message-ID"].strip()
            texto = self._texto_de(parte)
            hallado = re.search(r"^Message-ID:\s*(<[^>]+>)", texto, re.M | re.I)
            if hallado:
                return hallado.group(1).strip()

        # Algunos servidores lo ponen como referencia en el rebote.
        for cabecera in ("In-Reply-To", "References"):
            valor = mensaje.get(cabecera)
            if valor:
                hallado = re.search(r"<[^>]+>", valor)
                if hallado:
                    return hallado.group(0)
        return ""

    @staticmethod
    def _fecha(mensaje: Message) -> datetime:
        crudo = mensaje.get("Date")
        if crudo:
            try:
                fecha = email.utils.parsedate_to_datetime(crudo)
                return fecha.replace(tzinfo=None) if fecha.tzinfo else fecha
            except (TypeError, ValueError):
                pass
        return datetime.now()

    @staticmethod
    def _resumen(cuerpo: str) -> str:
        """Las líneas del cuerpo que dicen algo, recortadas."""
        utiles = [
            linea.strip() for linea in cuerpo.splitlines()
            if linea.strip() and not linea.startswith((">", "--", "Content-"))
        ]
        return " ".join(utiles)[:400] or "No se pudo entregar."
