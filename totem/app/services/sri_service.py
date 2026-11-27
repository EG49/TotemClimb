"""Emisión de comprobantes electrónicos al SRI.

Cómo encaja con el cobro
------------------------
El cobro NO espera al SRI. Esa es la regla que ordena todo lo demás,
y no es una decisión de comodidad: si el gimnasio se queda sin
internet, la venta tiene que poder registrarse igual y el cliente
irse con su pase. El esquema offline del SRI está pensado para eso.

Entonces el cobro hace dos cosas distintas en dos momentos:

  1. DENTRO de su transacción, reserva el secuencial y calcula la
     clave de acceso, y la factura queda en PENDIENTE. Esto es
     instantáneo y no toca la red. Si el cobro se deshace, el número
     vuelve con él (ver sri_repo).

  2. DESPUÉS de confirmar, lanza el envío en segundo plano. Si sale
     bien, la factura queda AUTORIZADA; si no, queda en PENDIENTE y
     la toma el reintento. En ninguno de los dos casos la pantalla
     de cobro se queda esperando.

Los estados
-----------
    PENDIENTE  → se emitió pero todavía no se envió (sin internet)
    FIRMADA    → el XML está firmado y guardado, falta enviarlo
    ENVIADA    → el SRI la recibió, falta saber si autoriza
    AUTORIZADA → listo
    DEVUELTA   → el SRI la rechazó en recepción (estructura o datos)
    NO_AUTORIZADA → llegó pero no la autorizó

PENDIENTE, FIRMADA y ENVIADA las vuelve a tomar el reintento. Las
otras tres ya no: una AUTORIZADA está lista y las dos rechazadas
necesitan que alguien mire el mensaje del SRI.

Qué se factura y qué no
-----------------------
Al SRI van SOLO las membresías y los pases. Los productos —aguas,
bebidas, magnesio— no se facturan uno por uno al cobrar: el gimnasio
los factura aparte y en bloque, a mano.

Eso tiene tres consecuencias que conviene tener presentes:

  - En una venta mixta (membresía + aguas), la factura electrónica
    lleva SOLO la membresía. El total del comprobante es menor que
    el de la venta, y es lo correcto.
  - Una venta de puros productos no genera comprobante ni gasta
    número: un secuencial reservado y nunca usado deja un hueco en
    la numeración que hay que explicarle al SRI.
  - La caja y lo facturado al SRI no cuadran entre sí por diseño.
    scripts/sri_sin_facturar.py lista lo que quedó fuera, que es lo
    que hace falta para armar la factura en bloque.

Si esa regla cambia, se cambia acá y en _armar_xml, no repartida por
el sistema.

Qué pasa si falta configuración
-------------------------------
Si no están los datos del emisor o el certificado, el sistema no
emite y no se rompe: cobra como siempre y deja la factura sin
comprobante electrónico. Es el estado del gimnasio hasta que termine
de habilitarse, y no puede impedir vender.
"""

import re
import threading
from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

from flask import current_app

from app.db import obtener_cursor
from app.repositories.sri_repo import (
    AUTORIZADA, DEVUELTA, ENVIADA, FACTURA, FIRMADA, NO_AUTORIZADA,
    PENDIENTE, SriRepositorio,
)
from app.services.sri import clave_acceso as ca
from app.services.sri import factura_xml as fx
from app.services.sri.firma import ErrorFirma, firmar

AMBIENTE_PRUEBAS = ca.AMBIENTE_PRUEBAS
AMBIENTE_PRODUCCION = ca.AMBIENTE_PRODUCCION

RECEPCION = {
    AMBIENTE_PRUEBAS: "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/"
                      "RecepcionComprobantesOffline",
    AMBIENTE_PRODUCCION: "https://cel.sri.gob.ec/comprobantes-electronicos-ws/"
                         "RecepcionComprobantesOffline",
}
AUTORIZACION = {
    AMBIENTE_PRUEBAS: "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/"
                      "AutorizacionComprobantesOffline",
    AMBIENTE_PRODUCCION: "https://cel.sri.gob.ec/comprobantes-electronicos-ws/"
                         "AutorizacionComprobantesOffline",
}

TIEMPO_LIMITE = 45

# Los hilos lanzados, para poder esperarlos en las pruebas y al
# apagar. Mismo problema que en correo_service: un hilo demonio que
# queda a medias deja la factura en un estado que nadie reintenta
# hasta la próxima vuelta.
_envios: list[threading.Thread] = []
_candado = threading.Lock()


class SriNoConfigurado(RuntimeError):
    """Faltan los datos del emisor o el certificado."""


def esperar_envios(segundos: float = 60) -> None:
    """Espera a los envíos en curso. Para las pruebas y el apagado."""
    with _candado:
        pendientes = list(_envios)
    for hilo in pendientes:
        hilo.join(timeout=segundos)
    with _candado:
        _envios[:] = [h for h in _envios if h.is_alive()]


class ServicioSri:

    def __init__(self):
        self.repo = SriRepositorio()

    # --- Configuración -------------------------------------------

    def _opcion(self, nombre: str, por_omision: str = "") -> str:
        return (current_app.config.get(nombre) or por_omision).strip()

    def ambiente(self) -> str:
        valor = self._opcion("SRI_AMBIENTE", AMBIENTE_PRUEBAS)
        return valor if valor in (AMBIENTE_PRUEBAS, AMBIENTE_PRODUCCION) else AMBIENTE_PRUEBAS

    def emite_este_sistema(self) -> bool:
        """¿Le toca a este sistema emitir, o lo hace otro?

        Cuando los comprobantes los emite Contífico a partir del Excel
        diario, este sistema no debe mandar nada al SRI. No es que no
        pueda: es que no debe. Dos emisores sobre la misma venta dejan
        dos comprobantes autorizados.
        """
        return (self._opcion("FACTURACION_ELECTRONICA", "sri") or "sri").lower() == "sri"

    def configurado(self) -> bool:
        """Si hay con qué emitir. Sin esto, el cobro sigue igual."""
        if not self.emite_este_sistema():
            return False
        return all(
            self._opcion(nombre)
            for nombre in ("SRI_RUC", "SRI_RAZON_SOCIAL", "SRI_DIR_MATRIZ",
                           "SRI_ESTABLECIMIENTO", "SRI_PUNTO_EMISION",
                           "SRI_P12_RUTA", "SRI_P12_CLAVE")
        )

    def emisor(self) -> fx.Emisor:
        if not self.configurado():
            raise SriNoConfigurado(
                "Faltan datos del emisor o el certificado en el .env."
            )
        matriz = self._opcion("SRI_DIR_MATRIZ")
        return fx.Emisor(
            ruc=self._opcion("SRI_RUC"),
            razon_social=self._opcion("SRI_RAZON_SOCIAL"),
            nombre_comercial=self._opcion("SRI_NOMBRE_COMERCIAL") or None,
            direccion_matriz=matriz,
            # Si no se definió la del establecimiento, es la matriz:
            # el gimnasio tiene un solo local.
            direccion_establecimiento=(
                self._opcion("SRI_DIR_ESTABLECIMIENTO") or matriz
            ),
            establecimiento=self._opcion("SRI_ESTABLECIMIENTO"),
            punto_emision=self._opcion("SRI_PUNTO_EMISION"),
            obligado_contabilidad=self._opcion(
                "SRI_OBLIGADO_CONTABILIDAD"
            ).upper() in ("SI", "1", "TRUE"),
            contribuyente_rimpe=self._opcion(
                "SRI_CONTRIBUYENTE_RIMPE"
            ).upper() in ("SI", "1", "TRUE"),
            ruc_proveedor_sistema=self._opcion("SRI_RUC_PROVEEDOR") or None,
        )

    # --- Paso 1: dentro de la transacción del cobro ---------------

    def reservar(self, cursor, id_factura: int) -> str | None:
        """Reserva número y clave de acceso para una factura recién creada.

        Se llama DENTRO de la transacción del cobro. Devuelve la clave
        de acceso, o None si el sistema todavía no emite.

        No toca la red ni firma nada: eso viene después, afuera de la
        transacción.
        """
        if not self.configurado():
            return None

        # Si la venta no lleva membresía ni pase, no hay factura
        # electrónica y no se gasta un número: un secuencial reservado
        # y nunca usado es un hueco que hay que explicarle al SRI.
        if not self._tiene_algo_que_facturar(cursor, id_factura):
            return None

        emisor = self.emisor()
        ambiente = self.ambiente()

        # La fecha sale de la factura y NO de date.today(). El SRI
        # exige que los primeros ocho dígitos de la clave de acceso
        # sean la misma fecha que declara el XML, y el XML lleva la
        # fecha de la venta.
        #
        # El día del cobro las dos coinciden, así que esto nunca se
        # notó. Pero al reemitir una factura de otro día -- que es
        # cuando mas falta hace -- la clave salia con la fecha de hoy
        # y el XML con la de la venta, y el SRI devolvia el error 58:
        # "La fecha de emision no consta como parte de la clave de
        # acceso". Tomando las dos del mismo lugar no pueden
        # discrepar.
        cursor.execute(
            "SELECT fecha FROM facturas WHERE id_factura = %s", (id_factura,)
        )
        fila = cursor.fetchone()
        fecha_factura = fila["fecha"] if fila else None
        if hasattr(fecha_factura, "date"):
            fecha_factura = fecha_factura.date()
        if fecha_factura is None:
            fecha_factura = date.today()

        secuencial = self.repo.reservar_secuencial(
            cursor, emisor.establecimiento, emisor.punto_emision, FACTURA
        )

        # El código numérico se guarda dentro de la clave de acceso,
        # así que la clave se puede volver a armar igual desde la
        # factura. Se usa el secuencial: no tiene que ser secreto, y
        # uno al azar daría una clave distinta en cada reintento.
        codigo = str(secuencial).zfill(8)[-8:]

        clave = ca.generar(
            fecha_emision=fecha_factura,
            tipo_comprobante=ca.FACTURA,
            ruc=emisor.ruc,
            ambiente=ambiente,
            establecimiento=emisor.establecimiento,
            punto_emision=emisor.punto_emision,
            secuencial=secuencial,
            codigo_numerico=codigo,
        )
        self.repo.guardar_emision(
            cursor, id_factura, emisor.establecimiento, emisor.punto_emision,
            secuencial, clave, estado=PENDIENTE,
        )
        return clave

    @staticmethod
    def _tiene_algo_que_facturar(cursor, id_factura: int) -> bool:
        """Si la venta lleva alguna membresía o pase.

        Se consulta con el cursor del cobro porque corre dentro de su
        transacción, donde el detalle recién insertado todavía no es
        visible desde afuera.
        """
        cursor.execute(
            """
            SELECT 1 FROM detalle_factura
             WHERE id_factura = %s AND id_plan IS NOT NULL
             LIMIT 1
            """,
            (id_factura,),
        )
        return cursor.fetchone() is not None

    # --- Paso 2: después de confirmar, fuera de la transacción ----

    def emitir_en_segundo_plano(self, id_factura: int) -> None:
        """Lanza el envío sin bloquear la pantalla de cobro."""
        if not self.configurado():
            return
        app = current_app._get_current_object()

        def tarea():
            with app.app_context():
                try:
                    self.emitir(id_factura)
                except Exception as error:  # noqa: BLE001
                    # Que falle el envío no puede tumbar nada: la
                    # factura queda PENDIENTE y la toma el reintento.
                    app.logger.warning(
                        "SRI: falló el envío de la factura %s: %s",
                        id_factura, error,
                    )

        hilo = threading.Thread(target=tarea, daemon=True)
        with _candado:
            _envios.append(hilo)
            _envios[:] = [h for h in _envios if h.is_alive() or h is hilo]
        hilo.start()

    def emitir(self, id_factura: int, consumidor_final: bool = False) -> str:
        """Arma, firma, envía y consulta. Devuelve el estado final."""
        datos = self._datos_de_la_factura(id_factura)
        if datos is None:
            raise ValueError(f"no existe la factura {id_factura}")
        if not datos["sri_clave_acceso"]:
            raise ValueError(
                f"la factura {id_factura} no tiene clave de acceso: no se "
                "reservó al cobrar"
            )

        clave = datos["sri_clave_acceso"].strip()

        xml_firmado = datos.get("sri_xml")
        if not xml_firmado:
            xml = self._armar_xml(datos, clave, consumidor_final)
            try:
                xml_firmado = firmar(
                    xml,
                    self._opcion("SRI_P12_RUTA"),
                    self._opcion("SRI_P12_CLAVE"),
                )
            except ErrorFirma as error:
                self.repo.guardar_estado(
                    id_factura, PENDIENTE, f"No se pudo firmar: {error}",
                    sumar_intento=True,
                )
                raise
            # Se guarda firmado antes de enviarlo: si el envío falla,
            # el reintento no vuelve a firmar ni cambia el documento.
            self.repo.guardar_estado(id_factura, FIRMADA, None, xml=xml_firmado)

        ambiente = self.ambiente()

        try:
            respuesta = self._soap(
                RECEPCION[ambiente],
                '<ec:validarComprobante xmlns:ec="http://ec.gob.sri.ws.recepcion">'
                f"<xml>{self._base64(xml_firmado)}</xml>"
                "</ec:validarComprobante>",
            )
        except Exception as error:  # noqa: BLE001
            self.repo.guardar_estado(
                id_factura, FIRMADA, f"No se pudo llegar al SRI: {error}",
                sumar_intento=True,
            )
            raise

        estado_recepcion, mensajes = self._leer_recepcion(respuesta)
        if estado_recepcion == "DEVUELTA":
            # El error 45 no es un rechazo: es el SRI diciendo que ese
            # comprobante YA LO TIENE, recibido en un intento
            # anterior. Pasa cuando el primer envio llego pero la
            # respuesta no volvio, y se reintenta con la misma clave
            # -- que es justo lo que este sistema hace a proposito,
            # para no duplicar comprobantes.
            #
            # Tomarlo como rechazo es peligroso, no solo incomodo: la
            # factura aparece rechazada, alguien pulsa Reemitir, y se
            # emite un SEGUNDO comprobante para una venta que ya
            # podria tener el suyo autorizado en el SRI. Dos
            # comprobantes validos para una sola venta es un problema
            # tributario de verdad.
            #
            # Lo correcto es preguntar por el que ya esta alla.
            if self._ya_lo_tiene_el_sri(mensajes):
                self.repo.guardar_estado(
                    id_factura, ENVIADA, mensajes, sumar_intento=True
                )
                return self.consultar(id_factura, clave)

            self.repo.guardar_estado(
                id_factura, DEVUELTA, mensajes, sumar_intento=True
            )
            return DEVUELTA

        self.repo.guardar_estado(id_factura, ENVIADA, None, sumar_intento=True)
        return self.consultar(id_factura, clave)

    # El SRI lo devuelve como un rechazo mas, con este identificador.
    ERROR_YA_REGISTRADO = "45"

    @classmethod
    def _ya_lo_tiene_el_sri(cls, mensajes: str) -> bool:
        """¿La recepción falló porque ese comprobante ya está allá?

        Se mira el identificador y tambien el texto: el identificador
        es lo formal, pero si algun dia el SRI lo cambia, el texto
        sigue diciendo lo mismo.
        """
        texto = (mensajes or "").upper()
        # Con limite de palabra: "identificador: 450", si alguna vez
        # existiera, no es el 45.
        return bool(
            re.search(rf"IDENTIFICADOR:\s*{cls.ERROR_YA_REGISTRADO}\b", texto)
            or "SECUENCIAL REGISTRADO" in texto
        )

    def consultar(self, id_factura: int, clave: str) -> str:
        """Le pregunta al SRI en qué quedó un comprobante ya enviado."""
        ambiente = self.ambiente()
        respuesta = self._soap(
            AUTORIZACION[ambiente],
            '<ec:autorizacionComprobante '
            'xmlns:ec="http://ec.gob.sri.ws.autorizacion">'
            f"<claveAccesoComprobante>{clave}</claveAccesoComprobante>"
            "</ec:autorizacionComprobante>",
        )
        estado, numero, fecha, mensajes = self._leer_autorizacion(respuesta)

        if estado == "AUTORIZADO":
            self.repo.guardar_estado(
                id_factura, AUTORIZADA, None,
                autorizacion=numero, fecha_autorizacion=fecha,
                xml=respuesta,
            )
            return AUTORIZADA

        if estado in ("NO AUTORIZADO", "RECHAZADA"):
            self.repo.guardar_estado(id_factura, NO_AUTORIZADA, mensajes)
            return NO_AUTORIZADA

        # EN PROCESO, o sin respuesta: queda para el reintento.
        self.repo.guardar_estado(
            id_factura, ENVIADA, mensajes or "El SRI todavía no resolvió."
        )
        return ENVIADA

    # --- Volver a emitir una rechazada ---------------------------

    # Con IVA incluido. Son 50 y no 200: los 200 son el tope del
    # regimen Negocio Popular (RIMPE), y para el regimen general son
    # 50 desde el Decreto Ejecutivo 586 de noviembre de 2022. El SRI
    # lo devuelve con el error 69.
    TOPE_CONSUMIDOR_FINAL = Decimal("50.00")

    def reemitir(self, id_factura: int,
                 consumidor_final: bool = False,
                 id_empleado: int | None = None) -> str:
        """Emite de nuevo una factura que el SRI rechazó.

        Hace falta porque una factura rechazada no se arregla
        reintentando: el SRI devolvería el mismo error. Hay que
        corregir el dato y emitir un comprobante NUEVO, con otro
        número y otra clave de acceso.

        El número anterior queda gastado. Es correcto: ese
        comprobante existió y el SRI lo rechazó, así que el hueco en
        la numeración tiene explicación.

        `consumidor_final` emite sin identificar al comprador. Es la
        salida para una cédula que el SRI no acepta y que no se puede
        corregir, y solo vale hasta USD 50.
        """
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT numero_factura, estado, total, sri_estado,
                       sri_clave_acceso, sri_mensaje
                  FROM facturas WHERE id_factura = %s
                """,
                (id_factura,),
            )
            factura = cursor.fetchone()

        if factura is None:
            raise ValueError(f"no existe la factura {id_factura}")
        if factura["estado"] == "ANULADA":
            raise ValueError("la factura está anulada: no se reemite")
        if factura["sri_estado"] not in (NO_AUTORIZADA, DEVUELTA):
            estado = factura["sri_estado"] or "sin comprobante"
            raise ValueError(
                f"la factura está en {estado} y solo se reemiten las "
                "rechazadas. Para las que siguen en camino use el "
                "reintento."
            )
        if consumidor_final and Decimal(factura["total"]) > self.TOPE_CONSUMIDOR_FINAL:
            raise ValueError(
                f"son ${factura['total']}, y una factura a consumidor "
                f"final no puede pasar de ${self.TOPE_CONSUMIDOR_FINAL}. "
                "Hay que corregir la identificación del cliente."
            )

        # El intento fallido queda en la BITACORA y no en el mensaje
        # de la factura: al emitir de nuevo, el mensaje se pisa con el
        # resultado nuevo y el rastro se perdería. La bitácora es el
        # registro que no se pisa, y es donde hay que mirar si alguna
        # vez hay que explicar un hueco en la numeración.
        anterior = (factura["sri_mensaje"] or "").strip()
        motivo = anterior.splitlines()[0] if anterior else "sin mensaje"
        try:
            from app.services.bitacora_service import BitacoraService

            BitacoraService().registrar(
                id_empleado or 0,
                "COMPROBANTE_REEMITIDO",
                "FACTURA",
                id_factura,
                {
                    "numero": factura["numero_factura"],
                    "clave_anterior": factura["sri_clave_acceso"],
                    "estado_anterior": factura["sri_estado"],
                    "motivo": motivo,
                    "consumidor_final": consumidor_final,
                },
            )
        except Exception as error:  # noqa: BLE001
            # Que no se pueda anotar no puede impedir emitir: al
            # cliente le falta su factura.
            current_app.logger.warning(
                "No se pudo anotar la reemisión de %s: %s",
                factura["numero_factura"], error,
            )
        historia = (
            f"[reemitida] el comprobante {factura['sri_clave_acceso']} "
            f"quedó {factura['sri_estado']}: {motivo}"
        )

        with obtener_cursor(commit=True) as cursor:
            # Se limpia el comprobante viejo para que el nuevo pueda
            # tomar su lugar: la clave de acceso es única.
            cursor.execute(
                """
                UPDATE facturas
                   SET sri_clave_acceso = NULL, sri_secuencial = NULL,
                       sri_establecimiento = NULL, sri_punto_emision = NULL,
                       sri_xml = NULL, sri_autorizacion = NULL,
                       sri_fecha_autorizacion = NULL,
                       sri_estado = NULL, sri_mensaje = %s
                 WHERE id_factura = %s
                """,
                (historia, id_factura),
            )
            clave = self.reservar(cursor, id_factura)

        if clave is None:
            raise ValueError(
                "no se pudo reservar un comprobante nuevo. Revise con: "
                "python -m scripts.sri_estado"
            )
        return self.emitir(id_factura, consumidor_final=consumidor_final)

    def reintentar_pendientes(self, limite: int = 25) -> dict:
        """Retoma lo que quedó sin resolver. Lo llama la tarea diaria."""
        if not self.configurado():
            return {"revisadas": 0, "autorizadas": 0, "sin_resolver": 0}

        resumen = {"revisadas": 0, "autorizadas": 0, "sin_resolver": 0}
        for factura in self.repo.pendientes(limite):
            resumen["revisadas"] += 1
            try:
                if factura["sri_estado"] == ENVIADA:
                    estado = self.consultar(
                        factura["id_factura"], factura["sri_clave_acceso"]
                    )
                else:
                    estado = self.emitir(factura["id_factura"])
            except Exception:  # noqa: BLE001
                resumen["sin_resolver"] += 1
                continue
            if estado == AUTORIZADA:
                resumen["autorizadas"] += 1
            else:
                resumen["sin_resolver"] += 1
        return resumen

    # --- Armado --------------------------------------------------

    def _datos_de_la_factura(self, id_factura: int) -> dict | None:
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT f.id_factura, f.fecha, f.metodo_pago, f.total,
                       f.iva_porcentaje, f.sri_clave_acceso, f.sri_secuencial,
                       f.sri_xml, f.sri_estado,
                       c.nombre, c.apellido, c.cedula, c.correo,
                       c.id_representante,
                       r.nombre   AS rep_nombre,
                       r.apellido AS rep_apellido,
                       r.cedula   AS rep_cedula,
                       r.correo   AS rep_correo
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                  LEFT JOIN clientes r ON r.id_cliente = c.id_representante
                 WHERE f.id_factura = %s
                """,
                (id_factura,),
            )
            fila = cursor.fetchone()
            if fila is None:
                return None
            datos = dict(fila)

            cursor.execute(
                """
                SELECT d.cantidad, d.precio_unitario, d.subtotal,
                       COALESCE(p.nombre, pm.nombre) AS nombre,
                       COALESCE(p.id_producto::text, 'P' || pm.id_plan::text)
                           AS codigo,
                       d.id_plan IS NOT NULL AS va_al_sri
                  FROM detalle_factura d
                  LEFT JOIN productos p ON p.id_producto = d.id_producto
                  LEFT JOIN planes_membresia pm ON pm.id_plan = d.id_plan
                 WHERE d.id_factura = %s
                 ORDER BY d.id_detalle
                """,
                (id_factura,),
            )
            datos["detalle"] = [dict(f) for f in cursor.fetchall()]
        return datos

    @staticmethod
    def _comprador_de(datos: dict) -> tuple[str, str | None, str | None]:
        """A quién se le factura: nombre, identificación y correo.

        Si el cliente es un menor a cargo, la factura va a nombre de
        su representante. Es quien paga, quien firmó el deslinde, y
        quien tiene cédula: los menores se registran con los datos del
        adulto y casi nunca tienen la suya cargada.

        Sin esto, la membresía de un menor salía a consumidor final
        -- por no tener cédula -- y el SRI la rechazaba con el error
        69 en cuanto pasaba de USD 50, que es el caso de la Junior.

        La membresía sigue siendo del menor en el sistema; lo único
        que cambia es a nombre de quién sale el comprobante.
        """
        if datos.get("id_representante") and (datos.get("rep_cedula") or "").strip():
            nombre = f"{datos.get('rep_nombre') or ''} " \
                     f"{datos.get('rep_apellido') or ''}".strip()
            return (
                nombre,
                (datos.get("rep_cedula") or "").strip() or None,
                (datos.get("rep_correo") or datos.get("correo") or "").strip()
                or None,
            )

        nombre = f"{datos.get('nombre') or ''} {datos.get('apellido') or ''}".strip()
        return (
            nombre,
            (datos.get("cedula") or "").strip() or None,
            (datos.get("correo") or "").strip() or None,
        )

    def _armar_xml(self, datos: dict, clave: str,
                   consumidor_final: bool = False) -> str:
        emisor = self.emisor()

        nombre, cedula, correo = self._comprador_de(datos)
        if consumidor_final:
            # Sin identificación: el comprador no se declara. Es la
            # salida cuando el SRI rechaza la cédula del cliente y no
            # hay forma de corregirla.
            comprador = fx.Comprador(correo=correo)
        else:
            comprador = fx.Comprador(
                identificacion=cedula, nombre=nombre, correo=correo,
            )

        # Solo membresías y pases. Los productos se facturan aparte y
        # en bloque, no uno por uno al cobrar. Ver la cabecera.
        lineas = [
            fx.LineaXML(
                codigo=str(linea["codigo"]),
                descripcion=linea["nombre"],
                cantidad=int(linea["cantidad"]),
                precio_unitario_con_iva=Decimal(linea["precio_unitario"]),
            )
            for linea in datos["detalle"]
            if linea["va_al_sri"]
        ]
        if not lineas:
            raise ValueError(
                "esta venta no tiene membresías ni pases: no corresponde "
                "emitirle factura electrónica"
            )

        # "Por cobrar" se factura igual: la factura se emite cuando se
        # entrega el servicio, no cuando entra la plata. El método de
        # pago queda como efectivo hasta que se cobre.
        metodo = (datos.get("metodo_pago") or "EFECTIVO").upper()
        if metodo not in fx.FORMA_PAGO:
            metodo = "EFECTIVO"

        fecha = datos["fecha"]
        # OJO: el total del XML lo calcula factura_xml a partir de
        # estas líneas, así que es el de la parte facturada y NO el
        # de la venta. Es lo buscado: la venta puede incluir productos
        # que no van en esta factura.
        return fx.generar(
            emisor=emisor,
            comprador=comprador,
            lineas=lineas,
            clave_acceso=clave,
            secuencial=datos["sri_secuencial"],
            fecha_emision=fecha.date() if hasattr(fecha, "date") else fecha,
            iva_porcentaje=Decimal(datos["iva_porcentaje"]),
            ambiente=self.ambiente(),
            metodo_pago=metodo,
        )

    # --- Red -----------------------------------------------------

    @staticmethod
    def _base64(texto: str) -> str:
        import base64

        return base64.b64encode(texto.encode("utf-8")).decode("ascii")

    @staticmethod
    def _soap(url: str, cuerpo: str) -> str:
        import urllib.request

        sobre = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv='
            '"http://schemas.xmlsoap.org/soap/envelope/">'
            f"<soapenv:Header/><soapenv:Body>{cuerpo}</soapenv:Body>"
            "</soapenv:Envelope>"
        )
        peticion = urllib.request.Request(
            url,
            data=sobre.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8",
                     "SOAPAction": ""},
        )
        with urllib.request.urlopen(peticion, timeout=TIEMPO_LIMITE) as r:
            return r.read().decode("utf-8", errors="replace")

    @staticmethod
    def _mensajes(nodo) -> str:
        partes = []
        for mensaje in nodo.iter("mensaje"):
            trozos = [
                f"{etiqueta}: {valor.strip()}"
                for etiqueta in ("identificador", "mensaje",
                                 "informacionAdicional")
                if (valor := mensaje.findtext(etiqueta))
            ]
            if trozos:
                partes.append(" | ".join(trozos))
            elif (mensaje.text or "").strip():
                partes.append(mensaje.text.strip())
        return "\n".join(partes)

    def _leer_recepcion(self, respuesta: str) -> tuple[str, str]:
        raiz = ET.fromstring(respuesta.encode("utf-8"))
        # `if nodo is None` y no `nodo or ...`: un elemento de XML sin
        # hijos es falso en Python, asi que el `or` descartaba el
        # estado que SI venia y daba por buena una factura DEVUELTA.
        nodo = next(raiz.iter("estado"), None)
        estado = (nodo.text or "") if nodo is not None else ""
        return estado.strip().upper(), self._mensajes(raiz)

    def _leer_autorizacion(self, respuesta: str):
        raiz = ET.fromstring(respuesta.encode("utf-8"))
        nodo = next(raiz.iter("autorizacion"), None)
        if nodo is None:
            return "", None, None, "El SRI no tiene ese comprobante todavía."

        estado = (nodo.findtext("estado") or "").strip().upper()
        numero = (nodo.findtext("numeroAutorizacion") or "").strip() or None
        texto_fecha = (nodo.findtext("fechaAutorizacion") or "").strip()
        fecha = None
        if texto_fecha:
            try:
                fecha = datetime.fromisoformat(texto_fecha)
            except ValueError:
                fecha = None
        return estado, numero, fecha, self._mensajes(nodo)


# ─────────────────────────────────────────────────────────────────
#  Facturas en bloque de productos
# ─────────────────────────────────────────────────────────────────
# Comparten casi todo con las facturas de venta: la misma numeración,
# la misma firma, los mismos envíos. Lo único distinto es de dónde
# salen las líneas y que siempre van a consumidor final.
#
# Se agregan como métodos de ServicioSri para no duplicar el camino
# de firma y envío, que es el que costó hacer bien.

def _reservar_bloque(self, cursor, id_bloque: int) -> str | None:
    """Número y clave de acceso para una factura en bloque."""
    if not self.configurado():
        return None

    emisor = self.emisor()
    secuencial = self.repo.reservar_secuencial(
        cursor, emisor.establecimiento, emisor.punto_emision, FACTURA
    )
    clave = ca.generar(
        fecha_emision=date.today(),
        tipo_comprobante=ca.FACTURA,
        ruc=emisor.ruc,
        ambiente=self.ambiente(),
        establecimiento=emisor.establecimiento,
        punto_emision=emisor.punto_emision,
        secuencial=secuencial,
        codigo_numerico=str(secuencial).zfill(8)[-8:],
    )
    cursor.execute(
        """
        UPDATE facturas_bloque
           SET sri_establecimiento = %s, sri_punto_emision = %s,
               sri_secuencial = %s, sri_clave_acceso = %s,
               sri_estado = 'PENDIENTE'
         WHERE id_bloque = %s
        """,
        (emisor.establecimiento, emisor.punto_emision, secuencial, clave,
         id_bloque),
    )
    return clave


def _emitir_bloque(self, id_bloque: int) -> str:
    """Firma y manda al SRI una factura en bloque ya creada."""
    from decimal import Decimal as _Decimal

    with obtener_cursor() as cursor:
        cursor.execute(
            """
            SELECT id_bloque, desde, hasta, fecha_emision, iva_porcentaje,
                   sri_clave_acceso, sri_secuencial, sri_xml
              FROM facturas_bloque WHERE id_bloque = %s
            """,
            (id_bloque,),
        )
        bloque = cursor.fetchone()
        if bloque is None:
            raise ValueError(f"no existe la factura en bloque {id_bloque}")
        bloque = dict(bloque)

        cursor.execute(
            """
            SELECT d.cantidad, d.precio_unitario, p.nombre,
                   p.id_producto::text AS codigo
              FROM detalle_bloque d
              JOIN productos p ON p.id_producto = d.id_producto
             WHERE d.id_bloque = %s
             ORDER BY d.id_detalle_bloque
            """,
            (id_bloque,),
        )
        detalle = [dict(f) for f in cursor.fetchall()]

    clave = (bloque["sri_clave_acceso"] or "").strip()
    if not clave:
        raise ValueError(
            f"la factura en bloque {id_bloque} no tiene clave de acceso"
        )

    xml_firmado = bloque.get("sri_xml")
    if not xml_firmado:
        xml = fx.generar(
            emisor=self.emisor(),
            # Siempre a consumidor final: son ventas de muchas
            # personas distintas juntas en un comprobante.
            comprador=fx.Comprador(),
            lineas=[
                fx.LineaXML(
                    codigo=str(linea["codigo"]),
                    descripcion=linea["nombre"],
                    cantidad=int(linea["cantidad"]),
                    precio_unitario_con_iva=_Decimal(linea["precio_unitario"]),
                )
                for linea in detalle
            ],
            clave_acceso=clave,
            secuencial=bloque["sri_secuencial"],
            fecha_emision=date.today(),
            iva_porcentaje=_Decimal(bloque["iva_porcentaje"]),
            ambiente=self.ambiente(),
            metodo_pago="EFECTIVO",
        )
        try:
            xml_firmado = firmar(
                xml, self._opcion("SRI_P12_RUTA"), self._opcion("SRI_P12_CLAVE")
            )
        except ErrorFirma as error:
            self._estado_bloque(id_bloque, PENDIENTE,
                                f"No se pudo firmar: {error}")
            raise
        self._estado_bloque(id_bloque, FIRMADA, None, xml=xml_firmado)

    ambiente = self.ambiente()
    try:
        respuesta = self._soap(
            RECEPCION[ambiente],
            '<ec:validarComprobante xmlns:ec="http://ec.gob.sri.ws.recepcion">'
            f"<xml>{self._base64(xml_firmado)}</xml>"
            "</ec:validarComprobante>",
        )
    except Exception as error:  # noqa: BLE001
        self._estado_bloque(id_bloque, FIRMADA,
                            f"No se pudo llegar al SRI: {error}")
        raise

    estado, mensajes = self._leer_recepcion(respuesta)
    if estado == "DEVUELTA":
        self._estado_bloque(id_bloque, DEVUELTA, mensajes)
        return DEVUELTA

    self._estado_bloque(id_bloque, ENVIADA, None)

    respuesta = self._soap(
        AUTORIZACION[ambiente],
        '<ec:autorizacionComprobante '
        'xmlns:ec="http://ec.gob.sri.ws.autorizacion">'
        f"<claveAccesoComprobante>{clave}</claveAccesoComprobante>"
        "</ec:autorizacionComprobante>",
    )
    estado, numero, fecha, mensajes = self._leer_autorizacion(respuesta)

    if estado == "AUTORIZADO":
        self._estado_bloque(id_bloque, AUTORIZADA, None, autorizacion=numero,
                            fecha_autorizacion=fecha, xml=respuesta)
        return AUTORIZADA
    if estado in ("NO AUTORIZADO", "RECHAZADA"):
        self._estado_bloque(id_bloque, NO_AUTORIZADA, mensajes)
        return NO_AUTORIZADA

    self._estado_bloque(id_bloque, ENVIADA,
                        mensajes or "El SRI todavía no resolvió.")
    return ENVIADA


def _estado_bloque(self, id_bloque, estado, mensaje, autorizacion=None,
                   fecha_autorizacion=None, xml=None) -> None:
    with obtener_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE facturas_bloque
               SET sri_estado = %s, sri_mensaje = %s,
                   sri_autorizacion = COALESCE(%s, sri_autorizacion),
                   sri_fecha_autorizacion =
                       COALESCE(%s, sri_fecha_autorizacion),
                   sri_xml = COALESCE(%s, sri_xml),
                   sri_intentos = sri_intentos + 1
             WHERE id_bloque = %s
            """,
            (estado, mensaje, autorizacion, fecha_autorizacion, xml,
             id_bloque),
        )


ServicioSri.reservar_bloque = _reservar_bloque
ServicioSri.emitir_bloque = _emitir_bloque
ServicioSri._estado_bloque = _estado_bloque
