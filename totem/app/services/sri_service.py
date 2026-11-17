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

Qué pasa si falta configuración
-------------------------------
Si no están los datos del emisor o el certificado, el sistema no
emite y no se rompe: cobra como siempre y deja la factura sin
comprobante electrónico. Es el estado del gimnasio hasta que termine
de habilitarse, y no puede impedir vender.
"""

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

    def configurado(self) -> bool:
        """Si hay con qué emitir. Sin esto, el cobro sigue igual."""
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

        emisor = self.emisor()
        ambiente = self.ambiente()
        hoy = date.today()

        secuencial = self.repo.reservar_secuencial(
            cursor, emisor.establecimiento, emisor.punto_emision, FACTURA
        )

        # El código numérico se guarda dentro de la clave de acceso,
        # así que la clave se puede volver a armar igual desde la
        # factura. Se usa el secuencial: no tiene que ser secreto, y
        # uno al azar daría una clave distinta en cada reintento.
        codigo = str(secuencial).zfill(8)[-8:]

        clave = ca.generar(
            fecha_emision=hoy,
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

    def emitir(self, id_factura: int) -> str:
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
            xml = self._armar_xml(datos, clave)
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
            self.repo.guardar_estado(
                id_factura, DEVUELTA, mensajes, sumar_intento=True
            )
            return DEVUELTA

        self.repo.guardar_estado(id_factura, ENVIADA, None, sumar_intento=True)
        return self.consultar(id_factura, clave)

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
                       c.nombre, c.apellido, c.cedula, c.correo
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
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
                           AS codigo
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

    def _armar_xml(self, datos: dict, clave: str) -> str:
        emisor = self.emisor()

        nombre = f"{datos['nombre']} {datos['apellido']}".strip()
        comprador = fx.Comprador(
            identificacion=(datos.get("cedula") or "").strip() or None,
            nombre=nombre,
            correo=(datos.get("correo") or "").strip() or None,
        )

        lineas = [
            fx.LineaXML(
                codigo=str(linea["codigo"]),
                descripcion=linea["nombre"],
                cantidad=int(linea["cantidad"]),
                precio_unitario_con_iva=Decimal(linea["precio_unitario"]),
            )
            for linea in datos["detalle"]
        ]

        # "Por cobrar" se factura igual: la factura se emite cuando se
        # entrega el servicio, no cuando entra la plata. El método de
        # pago queda como efectivo hasta que se cobre.
        metodo = (datos.get("metodo_pago") or "EFECTIVO").upper()
        if metodo not in fx.FORMA_PAGO:
            metodo = "EFECTIVO"

        fecha = datos["fecha"]
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
