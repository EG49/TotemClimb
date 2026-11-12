"""Correos de clases y eventos: confirmación, recordatorio y avisos.

Tres momentos, un mismo correo con distinto encabezado:

  * **Al agendar** — confirmación de que el lugar quedó reservado.
  * **El día anterior** — recordatorio. Lo dispara una tarea
    programada, no una persona.
  * **Cuando hace falta** — el admin escribe a todos los inscritos
    desde la pantalla del evento: cambió la hora, se suspende, lo que
    sea.

Decisiones que conviene entender:

  * **El correo nunca frena el agendado.** Si el envío falla, el
    posible cliente ya quedó registrado y la inscripción también. Lo
    único que se pierde es el correo, y eso queda en la bitácora.
  * **Un mensaje por persona.** De eso se encarga ServicioCorreo.
  * **El mapa va como enlace**, nunca como iframe: los clientes de
    correo los borran.
  * **Sin coach asignado el correo igual sale**, diciendo "por
    confirmar". Es mejor que no mandar nada: lo que la persona
    necesita saber es el día y la hora.
"""

from datetime import date, datetime, timedelta

from app.repositories.evento_repo import EventoRepositorio
from app.repositories.factura_repo import ConfiguracionRepositorio
from app.services.configuracion_service import ConfiguracionService
from app.services.correo_service import CorreoNoConfigurado, ServicioCorreo

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)

COACH_SIN_ASIGNAR = "Por confirmar"


def fecha_en_palabras(dia: date) -> str:
    """'jueves 13 de noviembre'. En un correo se lee mejor que 13/11."""
    return f"{DIAS[dia.weekday()]} {dia.day} de {MESES[dia.month - 1]}"


class AvisoClaseService:

    def __init__(self, eventos=None, correo=None, configuracion=None):
        self.eventos = eventos or EventoRepositorio()
        self.correo = correo or ServicioCorreo()
        self.configuracion = configuracion or ConfiguracionService()

    # --- Armado -------------------------------------------------------

    def _contexto(self, evento, modo: str, mensaje: str = "") -> dict:
        gym = self.configuracion.datos_del_gym()

        hora_fin = None
        if evento.hora_fin and not evento.es_todo_el_dia:
            hora_fin = evento.hora_fin.strftime("%H:%M")

        return {
            "evento": evento,
            "modo": modo,
            "mensaje": mensaje,
            "gym": gym,
            "fecha_texto": fecha_en_palabras(evento.fecha),
            "hora_texto": (
                "Todo el día" if evento.es_todo_el_dia
                else evento.hora_inicio.strftime("%H:%M")
            ),
            "hora_fin_texto": None if evento.es_todo_el_dia else hora_fin,
            "titulo_correo": evento.titulo,
        }

    @staticmethod
    def _destinatarios(evento) -> list[dict]:
        """Inscritos con correo. Clientes y posibles por igual."""
        return [
            {
                "correo": i["correo"],
                "nombre": i.get("nombre_pila") or "",
                "coach": i.get("coach_nombre"),
            }
            for i in evento.nombres_inscritos
            if (i.get("correo") or "").strip()
        ]

    # --- Envíos -------------------------------------------------------

    def confirmar_inscripcion(
        self, id_evento: int, correo: str, nombre: str, id_empleado: int,
        coach: str | None = None,
    ) -> bool:
        """Confirma a UNA persona recién agendada. No levanta excepciones.

        Devuelve si el envío quedó en marcha. Se traga los errores a
        propósito: esto se llama justo después de agendar, y un correo
        mal configurado no puede hacer fracasar un agendado que ya
        está guardado.
        """
        try:
            evento = self.eventos.obtener(id_evento)
            if evento is None:
                return False

            contexto = self._contexto(evento, "confirmacion")
            contexto["coach_texto"] = coach or COACH_SIN_ASIGNAR

            self.correo.enviar_aviso(
                destinatarios=[{"correo": correo, "nombre": nombre}],
                asunto=f"Confirmado: {evento.titulo} — Totem Climb Gym",
                plantilla="clase",
                contexto=contexto,
                id_empleado=id_empleado,
                id_evento=id_evento,
            )
            return True
        except (CorreoNoConfigurado, ValueError):
            # Sin configuración de correo, o sin dirección: no es un
            # fallo del agendado.
            return False
        except Exception:  # noqa: BLE001
            from flask import current_app
            current_app.logger.exception(
                "No se pudo preparar la confirmación del evento %s", id_evento
            )
            return False

    def avisar_a_inscritos(
        self, id_evento: int, mensaje: str, id_empleado: int
    ) -> int:
        """Escribe a todos los inscritos. Devuelve a cuántos.

        Esta sí levanta excepciones: la pide una persona desde una
        pantalla y tiene que enterarse si no salió.
        """
        evento = self.eventos.obtener(id_evento)
        if evento is None:
            raise ValueError("Ese evento ya no existe.")

        destinatarios = self._destinatarios(evento)
        if not destinatarios:
            raise ValueError(
                "Ninguno de los inscritos tiene un correo registrado."
            )

        contexto = self._contexto(evento, "aviso", mensaje)
        contexto["coach_texto"] = None  # en un aviso general no aplica

        return self.correo.enviar_aviso(
            destinatarios=destinatarios,
            asunto=f"{evento.titulo} — Totem Climb Gym",
            plantilla="clase",
            contexto=contexto,
            id_empleado=id_empleado,
            id_evento=id_evento,
        )

    def recordar_los_de_manana(self, id_empleado: int, hoy: date | None = None) -> dict:
        """Recordatorio a los inscritos de las clases de mañana.

        La llama la tarea programada, una vez por día. Devuelve un
        resumen para que el script pueda informar qué hizo.
        """
        hoy = hoy or date.today()
        manana = hoy + timedelta(days=1)

        resumen = {"fecha": manana, "eventos": 0, "correos": 0, "sin_correo": 0,
                   "detalle": []}

        for cabecera in self.eventos.entre(manana, manana):
            evento = self.eventos.obtener(cabecera.id_evento)
            if evento is None or not evento.nombres_inscritos:
                continue

            destinatarios = self._destinatarios(evento)
            sin_correo = len(evento.nombres_inscritos) - len(destinatarios)
            resumen["sin_correo"] += sin_correo

            if not destinatarios:
                resumen["detalle"].append(
                    {"evento": evento.titulo, "correos": 0,
                     "nota": "nadie tiene correo"}
                )
                continue

            contexto = self._contexto(evento, "recordatorio")
            # Si todos los inscritos comparten coach, se nombra; si no,
            # se omite en lugar de decirle a alguien el coach de otro.
            coaches = {d["coach"] for d in destinatarios}
            contexto["coach_texto"] = (
                coaches.pop() if len(coaches) == 1 else None
            ) or (COACH_SIN_ASIGNAR if len(coaches) <= 1 else None)

            enviados = self.correo.enviar_aviso(
                destinatarios=destinatarios,
                asunto=f"Mañana: {evento.titulo} — Totem Climb Gym",
                plantilla="clase",
                contexto=contexto,
                id_empleado=id_empleado,
                id_evento=evento.id_evento,
            )
            resumen["eventos"] += 1
            resumen["correos"] += enviados
            resumen["detalle"].append(
                {"evento": evento.titulo, "correos": enviados,
                 "nota": f"{sin_correo} sin correo" if sin_correo else ""}
            )

        return resumen
