"""Lo que pasa cuando un correo no llega.

Enviar un correo no dice nada sobre si llego. El servidor lo acepta,
y minutos despues devuelve el aviso de que esa direccion no existe.
Ese aviso es lo unico que confirma de verdad un correo malo.

Dos partes:

  * leer el rebote: sacarle a quien no le llego, por que, y de que
    mensaje era. Esto es lo fragil, porque cada servidor manda el
    rebote a su manera.
  * marcar lo que corresponde: la factura queda señalada y el cliente
    tambien, para que alguien le pregunte el correo bueno.

Lo que mas importa comprobar es que **no se marque de mas**. Marcar
al cliente equivocado significa que alguien le va a pedir el correo a
una persona cuyo correo esta perfecto, y peor, que el correo del que
si rebotó se queda sin marcar. Por eso hay tantos casos de "esto NO
es un rebote" como de "esto si lo es".

Los mensajes son rebotes reales, con los dominios cambiados.
"""

import email
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app  # noqa: E402
from app.db import obtener_cursor  # noqa: E402
from app.services.rebote_service import ReboteService  # noqa: E402
from app.services.rebotes.buzon_imap import BuzonIMAP  # noqa: E402
from app.services.rebotes.fuente import FuenteDeRebotes, Rebote  # noqa: E402

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


def leer(crudo: str):
    return BuzonIMAP()._leer(email.message_from_string(crudo.strip()))


# --- Rebotes de verdad, tal como los manda cada servidor ---------------

GMAIL = """From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>
To: recibos@totemclimbgym.com
Subject: Delivery Status Notification (Failure)
Date: Tue, 18 Nov 2026 14:23:01 -0500
Content-Type: multipart/report; report-type=delivery-status; boundary="xx"

--xx
Content-Type: text/plain; charset=UTF-8

Address not found. Your message wasn't delivered to anita.lopez@gmaail.com
because the address couldn't be found.

--xx
Content-Type: message/delivery-status

Reporting-MTA: dns; googlemail.com

Final-Recipient: rfc822; anita.lopez@gmaail.com
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550-5.1.1 The email account that you tried to reach does not exist.

--xx
Content-Type: message/rfc822

From: Totem Climb Gym <recibos@totemclimbgym.com>
To: anita.lopez@gmaail.com
Subject: Su comprobante F-000123
Message-ID: <abc123@totemclimbgym.com>

(el mensaje original)
--xx--
"""

BUZON_LLENO = """From: postmaster@correo-de-ana.ec
To: recibos@totemclimbgym.com
Subject: Undelivered Mail Returned to Sender
Date: Tue, 18 Nov 2026 15:00:00 -0500
Content-Type: multipart/report; report-type=delivery-status; boundary="yy"

--yy
Content-Type: message/delivery-status

Final-Recipient: rfc822; ana@correo-de-ana.ec
Action: delayed
Status: 4.2.2
Diagnostic-Code: smtp; 452 4.2.2 Mailbox full

--yy
Content-Type: text/rfc822-headers

Message-ID: <def456@totemclimbgym.com>
Subject: Su comprobante F-000124
--yy--
"""

SIN_ORIGINAL = """From: Mail Delivery System <MAILER-DAEMON@correo.ec>
To: recibos@totemclimbgym.com
Subject: Undeliverable
Date: Tue, 18 Nov 2026 16:00:00 -0500
Content-Type: multipart/report; report-type=delivery-status; boundary="zz"

--zz
Content-Type: message/delivery-status

Final-Recipient: rfc822; pedro@empresa-rara.ec
Action: failed
Status: 5.0.0

--zz--
"""

TEXTO_SUELTO = """From: MAILER-DAEMON@viejo-servidor.ec
To: recibos@totemclimbgym.com
Subject: Returned mail: see transcript for details
Date: Tue, 18 Nov 2026 17:00:00 -0500
Content-Type: text/plain

The original message was received at Tue, 18 Nov 2026 17:00:00
----- The following addresses had permanent fatal errors -----
<luis@dominio-viejo.ec>
----- Transcript of session follows -----
550 5.1.1 <luis@dominio-viejo.ec>... User unknown
"""

# Estos NO son rebotes. Si se leyeran como tales, se marcaria a un
# cliente cuyo correo funciona perfectamente.
VACACIONES = """From: ana@gmail.com
To: recibos@totemclimbgym.com
Subject: Fuera de la oficina
Date: Tue, 18 Nov 2026 18:00:00 -0500
Content-Type: text/plain

Estoy de vacaciones hasta el 2 de diciembre. Escribame a
otro-correo@gmail.com si es urgente.
"""

RESPUESTA = """From: carlos@hotmail.com
To: recibos@totemclimbgym.com
Subject: Re: Su comprobante F-000125
Date: Tue, 18 Nov 2026 19:00:00 -0500
Content-Type: text/plain

Gracias, recibido. Una consulta sobre mi membresia...
"""


print("\nSE LEE BIEN UN REBOTE DE GMAIL")
r = leer(GMAIL)
revisar("es un rebote", r is not None)
if r:
    revisar("a quien no le llego", r.destinatario == "anita.lopez@gmaail.com",
            r.destinatario)
    revisar("de que mensaje era", r.message_id == "<abc123@totemclimbgym.com>",
            r.message_id)
    revisar("por que", "does not exist" in r.motivo, r.motivo[:60])
    revisar("es definitivo (5.x.x)", r.definitivo)

print("\nUN BUZON LLENO NO ES UN CORREO MAL ESCRITO")
# 4.x.x es temporal: el correo esta bien, el problema se arregla solo.
# Marcar al cliente por esto seria pedirle que corrija algo correcto.
r = leer(BUZON_LLENO)
revisar("se lee", r is not None)
if r:
    revisar("NO es definitivo (4.x.x)", not r.definitivo)
    revisar("igual se sabe de que mensaje era",
            r.message_id == "<def456@totemclimbgym.com>", r.message_id)

print("\nSE ARREGLA CON LO QUE HAYA")
r = leer(SIN_ORIGINAL)
revisar("sin el mensaje original, igual se lee", r is not None)
if r:
    revisar("queda sin Message-ID", r.message_id == "", r.message_id)
    revisar("pero con la direccion", r.destinatario == "pedro@empresa-rara.ec")
    revisar("y con un motivo", bool(r.motivo), r.motivo)

r = leer(TEXTO_SUELTO)
revisar("un rebote sin estructura tambien se lee", r is not None)
if r:
    revisar("saca la direccion del texto",
            r.destinatario == "luis@dominio-viejo.ec", r.destinatario)
    revisar("y ve que es permanente", r.definitivo)

print("\nLO QUE NO ES UN REBOTE NO SE TOMA COMO TAL")
revisar("un aviso de vacaciones no es un rebote", leer(VACACIONES) is None,
        "contiene una direccion, pero no viene de un demonio de correo")
revisar("una respuesta del cliente tampoco", leer(RESPUESTA) is None)


# --- Marcado en la base ------------------------------------------------

class FuenteFalsa(FuenteDeRebotes):
    """Devuelve los rebotes que se le pongan, sin tocar ningun buzon."""

    def __init__(self, lista):
        self.lista = lista

    def configurada(self):
        return True

    def rebotes(self, desde):
        return [r for r in self.lista if r.ocurrido_en >= desde]


app = crear_app()
with app.app_context():
    with obtener_cursor() as cursor:
        cursor.execute(
            "SELECT f.id_factura, f.numero_factura, f.id_cliente "
            "  FROM facturas f WHERE f.id_cliente IS NOT NULL "
            " ORDER BY f.id_factura DESC LIMIT 1"
        )
        fila = cursor.fetchone()

    if fila is None:
        print("\nHace falta una factura con cliente. Se omite el resto.")
        sys.exit(1 if fallas else 0)

    id_factura = fila["id_factura"]
    id_cliente = fila["id_cliente"]
    ahora = datetime.now()

    def limpiar():
        with obtener_cursor(commit=True) as cursor:
            cursor.execute("DELETE FROM envios_correo WHERE destinatario "
                           "LIKE '%@prueba-rebotes.ec'")
            cursor.execute("UPDATE clientes SET correo_rebotado_en = NULL, "
                           "correo_rebote_motivo = NULL WHERE id_cliente = %s",
                           (id_cliente,))
            cursor.execute("UPDATE rebotes_revision SET revisado_hasta = %s",
                           (ahora - timedelta(days=2),))

    def estado_envio(message_id):
        with obtener_cursor() as cursor:
            cursor.execute("SELECT estado, motivo FROM envios_correo "
                           " WHERE message_id = %s", (message_id,))
            f = cursor.fetchone()
            return dict(f) if f else None

    def cliente_marcado():
        with obtener_cursor() as cursor:
            cursor.execute("SELECT correo_rebotado_en FROM clientes "
                           " WHERE id_cliente = %s", (id_cliente,))
            return cursor.fetchone()["correo_rebotado_en"] is not None

    print("\nEL REBOTE SE CASA CON SU FACTURA")
    limpiar()
    ReboteService.registrar_envio(
        destinatario="ana@prueba-rebotes.ec",
        message_id="<prueba-1@totem.ec>",
        asunto="Su comprobante",
        id_factura=id_factura,
        id_cliente=id_cliente,
    )
    servicio = ReboteService(FuenteFalsa([Rebote(
        destinatario="ana@prueba-rebotes.ec",
        motivo="550 5.1.1 User unknown",
        ocurrido_en=ahora,
        message_id="<prueba-1@totem.ec>",
    )]))
    resumen = servicio.revisar()
    revisar("se leyo el rebote", resumen["leidos"] == 1, resumen)
    revisar("se caso con su envio", resumen["casados"] == 1, resumen)
    envio = estado_envio("<prueba-1@totem.ec>")
    revisar("el envio queda REBOTADO", envio and envio["estado"] == "REBOTADO",
            envio)
    revisar("con el motivo guardado", envio and "User unknown" in envio["motivo"])
    revisar("y el cliente queda señalado", cliente_marcado())

    print("\nEL MISMO REBOTE DOS VECES NO CUENTA DOS VECES")
    # El buzon se relee con margen, asi que los rebotes vuelven a
    # aparecer. Si cada pasada los contara de nuevo, el resumen diario
    # mentiria y la bitacora se llenaria de repetidos.
    resumen = servicio.revisar()
    revisar("la segunda pasada no lo vuelve a casar",
            resumen["casados"] == 0, resumen)

    print("\nUN REBOTE TEMPORAL NO SEÑALA AL CLIENTE")
    limpiar()
    ReboteService.registrar_envio(
        destinatario="ana@prueba-rebotes.ec",
        message_id="<prueba-2@totem.ec>",
        id_factura=id_factura, id_cliente=id_cliente,
    )
    resumen = ReboteService(FuenteFalsa([Rebote(
        destinatario="ana@prueba-rebotes.ec",
        motivo="452 4.2.2 Mailbox full",
        ocurrido_en=ahora,
        message_id="<prueba-2@totem.ec>",
        definitivo=False,
    )])).revisar()
    revisar("el envio igual queda marcado",
            (estado_envio("<prueba-2@totem.ec>") or {}).get("estado") == "REBOTADO")
    revisar("pero el cliente NO", not cliente_marcado(),
            "su correo esta bien; el buzon se vacia solo")

    print("\nSIN MESSAGE-ID SE BUSCA POR DIRECCION")
    limpiar()
    ReboteService.registrar_envio(
        destinatario="pedro@prueba-rebotes.ec",
        message_id="<prueba-3@totem.ec>",
        id_factura=id_factura, id_cliente=id_cliente,
    )
    resumen = ReboteService(FuenteFalsa([Rebote(
        destinatario="pedro@prueba-rebotes.ec",
        motivo="550 User unknown",
        ocurrido_en=ahora,
        message_id="",
    )])).revisar()
    revisar("se encuentra igual", resumen["casados"] == 1, resumen)

    print("\nUN REBOTE DE UN CORREO QUE NO MANDAMOS NO INVENTA NADA")
    limpiar()
    resumen = ReboteService(FuenteFalsa([Rebote(
        destinatario="desconocido@prueba-rebotes.ec",
        motivo="550 User unknown",
        ocurrido_en=ahora,
        message_id="<no-existe@totem.ec>",
    )])).revisar()
    revisar("queda como suelto, sin marcar a nadie",
            resumen["sueltos"] == 1 and resumen["casados"] == 0, resumen)
    revisar("y ningun cliente queda señalado", not cliente_marcado())

    print("\nUN ENVIO VIEJO NO SE CASA CON UN REBOTE DE HOY")
    # Sin la ventana de dias, un rebote sin Message-ID se casaria con
    # cualquier envio a esa direccion, por viejo que fuera.
    limpiar()
    with obtener_cursor(commit=True) as cursor:
        cursor.execute(
            "INSERT INTO envios_correo (id_factura, id_cliente, destinatario, "
            "  message_id, enviado_en) VALUES (%s, %s, %s, %s, %s)",
            (id_factura, id_cliente, "viejo@prueba-rebotes.ec",
             "<prueba-viejo@totem.ec>", ahora - timedelta(days=60)),
        )
    resumen = ReboteService(FuenteFalsa([Rebote(
        destinatario="viejo@prueba-rebotes.ec",
        motivo="550 User unknown",
        ocurrido_en=ahora,
        message_id="",
    )])).revisar()
    revisar("no se casa con el envio de hace dos meses",
            resumen["casados"] == 0, resumen)

    print("\nSIN BUZON CONFIGURADO NO REVIENTA")
    class SinConfigurar(FuenteFalsa):
        def configurada(self):
            return False

    resumen = ReboteService(SinConfigurar([])).revisar()
    revisar("lo dice y no hace nada", resumen["configurado"] is False, resumen)

    limpiar()

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
