"""Repositorio de la facturación electrónica: numeración y estado.

Lo delicado de este archivo es la reserva del secuencial. Dos reglas
que no se pueden romper:

  1. El mismo número no puede salir dos veces en un punto de emisión.
     Lo emitido no se deshace.
  2. Si el cobro falla, el número tiene que volver, porque un hueco
     en la numeración hay que explicárselo al SRI.

Las dos salen de reservar el número DENTRO de la transacción del
cobro, bloqueando la fila del punto de emisión:

  - el bloqueo hace que dos cajas cobrando a la vez se ordenen, y la
    segunda vea el número de la primera ya tomado;
  - y si la transacción se deshace, el UPDATE se deshace con ella y
    el número queda libre.

Por eso `reservar_secuencial` recibe el cursor desde el servicio y no
abre el suyo: con un cursor propio tendría su propia transacción, se
confirmaría por su cuenta y un cobro fallido dejaría el hueco igual.
"""

from app.db import obtener_cursor

FACTURA = "01"
NOTA_DE_CREDITO = "04"

MAXIMO = 999999999

# Los estados por los que pasa un comprobante.
PENDIENTE = "PENDIENTE"        # todavía no se envió (sin internet, p. ej.)
FIRMADA = "FIRMADA"
ENVIADA = "ENVIADA"
AUTORIZADA = "AUTORIZADA"
DEVUELTA = "DEVUELTA"          # el SRI la rechazó en recepción
NO_AUTORIZADA = "NO_AUTORIZADA"

# Las que el reintento vuelve a tomar.
SIN_RESOLVER = (PENDIENTE, FIRMADA, ENVIADA)


class ErrorSecuencial(RuntimeError):
    """No se pudo reservar un número para el comprobante."""


class SriRepositorio:

    def reservar_secuencial(
        self,
        cursor,
        establecimiento: str,
        punto_emision: str,
        tipo_comprobante: str = FACTURA,
    ) -> int:
        """Toma el siguiente número del punto de emisión.

        Recibe el cursor del cobro a propósito: ver la cabecera del
        módulo. El número queda tomado solo si el cobro se confirma.
        """
        # UPDATE ... RETURNING bloquea la fila y devuelve el valor ya
        # incrementado en una sola ida a la base. No hace falta un
        # SELECT FOR UPDATE antes: el UPDATE ya toma el bloqueo, y
        # hacerlo en dos pasos abre una ventana entre leer y escribir.
        cursor.execute(
            """
            UPDATE sri_secuenciales
               SET ultimo_secuencial = ultimo_secuencial + 1,
                   fecha_actualizacion = CURRENT_TIMESTAMP
             WHERE establecimiento  = %s
               AND punto_emision    = %s
               AND tipo_comprobante = %s
            RETURNING ultimo_secuencial
            """,
            (establecimiento, punto_emision, tipo_comprobante),
        )
        fila = cursor.fetchone()
        if fila is None:
            raise ErrorSecuencial(
                f"no hay numeración para el punto {establecimiento}-"
                f"{punto_emision} tipo {tipo_comprobante}. Corra "
                "Sql/alter-sri-secuenciales.sql, o agregue la fila si "
                "el punto de emisión es otro."
            )
        secuencial = fila["ultimo_secuencial"]
        if secuencial > MAXIMO:
            raise ErrorSecuencial(
                f"el punto {establecimiento}-{punto_emision} llegó al "
                f"máximo de {MAXIMO}. Hay que pedirle otro punto de "
                "emisión al SRI."
            )
        return secuencial

    def ultimo_secuencial(
        self,
        establecimiento: str,
        punto_emision: str,
        tipo_comprobante: str = FACTURA,
    ) -> int | None:
        """El último número entregado. Para mostrar, no para emitir."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT ultimo_secuencial
                  FROM sri_secuenciales
                 WHERE establecimiento  = %s
                   AND punto_emision    = %s
                   AND tipo_comprobante = %s
                """,
                (establecimiento, punto_emision, tipo_comprobante),
            )
            fila = cursor.fetchone()
        return fila["ultimo_secuencial"] if fila else None

    # --- Estado del comprobante ----------------------------------

    def guardar_emision(
        self,
        cursor,
        id_factura: int,
        establecimiento: str,
        punto_emision: str,
        secuencial: int,
        clave_acceso: str,
        xml: str | None = None,
        estado: str = PENDIENTE,
    ) -> None:
        """Deja asentado qué número y qué clave le tocaron a la factura.

        Va en la misma transacción que la reserva: el número reservado
        y la factura que lo usa se guardan juntos o no se guarda
        ninguno de los dos.
        """
        cursor.execute(
            """
            UPDATE facturas
               SET sri_establecimiento = %s,
                   sri_punto_emision   = %s,
                   sri_secuencial      = %s,
                   sri_clave_acceso    = %s,
                   sri_xml             = COALESCE(%s, sri_xml),
                   sri_estado          = %s
             WHERE id_factura = %s
            """,
            (establecimiento, punto_emision, secuencial, clave_acceso,
             xml, estado, id_factura),
        )

    def guardar_estado(
        self,
        id_factura: int,
        estado: str,
        mensaje: str | None = None,
        autorizacion: str | None = None,
        fecha_autorizacion=None,
        xml: str | None = None,
        sumar_intento: bool = False,
    ) -> None:
        """Anota en qué quedó el envío. Abre su propia transacción.

        A diferencia de la reserva, esto se guarda aunque el resto
        falle: saber que el SRI rechazó un comprobante es información
        que no se puede perder.
        """
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE facturas
                   SET sri_estado  = %s,
                       sri_mensaje = %s,
                       sri_autorizacion = COALESCE(%s, sri_autorizacion),
                       sri_fecha_autorizacion =
                           COALESCE(%s, sri_fecha_autorizacion),
                       sri_xml = COALESCE(%s, sri_xml),
                       sri_intentos = sri_intentos + %s
                 WHERE id_factura = %s
                """,
                (estado, mensaje, autorizacion, fecha_autorizacion, xml,
                 1 if sumar_intento else 0, id_factura),
            )

    def pendientes(self, limite: int = 50) -> list[dict]:
        """Las facturas que quedaron sin resolver ante el SRI.

        Es lo que mira el reintento: comprobantes que se emitieron
        pero no llegaron a autorizarse, normalmente porque se cayó el
        internet en medio del cobro.
        """
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT id_factura, numero_factura, sri_estado,
                       sri_clave_acceso, sri_secuencial, sri_intentos,
                       sri_xml, fecha
                  FROM facturas
                 WHERE sri_estado = ANY(%s)
                   AND estado <> 'ANULADA'
                 ORDER BY fecha
                 LIMIT %s
                """,
                (list(SIN_RESOLVER), limite),
            )
            return [dict(fila) for fila in cursor.fetchall()]
