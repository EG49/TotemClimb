"""Recordatorio por correo a los inscritos de las clases de mañana.

Lo corre el Programador de tareas de Windows una vez al día. No es
una pantalla: no hay nadie mirando cuando se ejecuta, así que todo
lo que pasa se escribe en la salida y en el registro de la
aplicación.

    python -m scripts.recordar_clases

Opciones:

    --probar          No manda nada. Dice a quién le escribiría.
    --fecha AAAA-MM-DD  Recuerda las clases de ESE día en lugar de
                      las de mañana. Para probar con una fecha que
                      ya tenga inscritos.

Para dejarlo automático en Windows, en el Programador de tareas:

    Programa:    C:\\ruta\\al\\proyecto\\.venv\\Scripts\\python.exe
    Argumentos:  -m scripts.recordar_clases
    Iniciar en:  C:\\ruta\\al\\proyecto

Conviene ponerlo a media tarde, no a medianoche: un recordatorio que
llega a las 00:05 para una clase de las 18:00 se lee al día
siguiente junto con el resto del correo, y para entonces ya pasó.

Devuelve 0 si todo salió bien y 1 si algo falló, que es lo que mira
el Programador de tareas para marcar la ejecución como fallida.
"""

import argparse
import sys
from datetime import date, datetime, timedelta

from app import crear_app
from app.repositories.evento_repo import EventoRepositorio
from app.services.aviso_clase_service import AvisoClaseService, fecha_en_palabras
from app.services.correo_service import (
    CorreoNoConfigurado,
    ServicioCorreo,
    esperar_envios,
)

# El recordatorio no lo manda una persona: se anota a nombre del
# primer ADMIN, que es quien responde por el sistema.
from app.db import obtener_cursor


def _empleado_del_sistema() -> int | None:
    with obtener_cursor() as cursor:
        cursor.execute(
            "SELECT id_empleado FROM empleados "
            "WHERE rol = 'ADMIN' AND activo ORDER BY id_empleado LIMIT 1"
        )
        fila = cursor.fetchone()
    return fila["id_empleado"] if fila else None


def _a_fecha(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _listar_sin_enviar(dia: date) -> int:
    """Modo --probar: dice qué haría, sin mandar un solo correo."""
    eventos = EventoRepositorio()
    servicio = AvisoClaseService()

    print(f"Clases del {fecha_en_palabras(dia)}:")
    print()

    total = 0
    hubo_alguna = False
    for cabecera in eventos.entre(dia, dia):
        evento = eventos.obtener(cabecera.id_evento)
        if evento is None or not evento.nombres_inscritos:
            continue

        hubo_alguna = True
        destinatarios = servicio._destinatarios(evento)
        sin_correo = len(evento.nombres_inscritos) - len(destinatarios)

        print(f"  {evento.titulo}  ({evento.horario})")
        for d in destinatarios:
            print(f"      -> {d['nombre'] or '(sin nombre)'}  {d['correo']}")
        if sin_correo:
            print(f"      ({sin_correo} inscrito(s) sin correo registrado)")
        print()
        total += len(destinatarios)

    if not hubo_alguna:
        print("  No hay clases con inscritos ese dia.")
        return 0

    print(f"Se enviarian {total} correo(s). No se envio ninguno: esto es --probar.")
    return total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Recuerda por correo las clases del dia siguiente."
    )
    parser.add_argument("--probar", action="store_true",
                        help="No manda nada; solo dice a quien le escribiria.")
    parser.add_argument("--fecha", metavar="AAAA-MM-DD",
                        help="Recuerda las clases de ese dia en lugar de las de manana.")
    args = parser.parse_args(argv)

    if args.fecha:
        dia = _a_fecha(args.fecha)
        if dia is None:
            print(f"ERROR: '{args.fecha}' no es una fecha valida. Usa AAAA-MM-DD.")
            return 1
    else:
        dia = date.today() + timedelta(days=1)

    app = crear_app()
    with app.app_context():
        if args.probar:
            _listar_sin_enviar(dia)
            return 0

        if not ServicioCorreo.configurado():
            print("ERROR: el correo no esta configurado.")
            print("Revisa las variables MAIL_ del archivo .env.")
            return 1

        id_empleado = _empleado_del_sistema()
        if id_empleado is None:
            print("ERROR: no hay ningun ADMIN activo a cuyo nombre registrar el envio.")
            return 1

        # recordar_los_de_manana mira el dia siguiente al que se le
        # pasa, asi que se le da el dia anterior al que queremos.
        try:
            resumen = AvisoClaseService().recordar_los_de_manana(
                id_empleado, hoy=dia - timedelta(days=1)
            )
        except CorreoNoConfigurado:
            print("ERROR: el correo no esta configurado.")
            return 1

        print(f"Clases del {fecha_en_palabras(resumen['fecha'])}:")
        for d in resumen["detalle"]:
            extra = f"  ({d['nota']})" if d["nota"] else ""
            print(f"  {d['evento']}: {d['correos']} correo(s){extra}")

        if not resumen["detalle"]:
            print("  No hay clases con inscritos ese dia. Nada que recordar.")
            return 0

        print()
        print(f"{resumen['correos']} correo(s) en camino para "
              f"{resumen['eventos']} clase(s).")
        if resumen["sin_correo"]:
            print(f"{resumen['sin_correo']} inscrito(s) no tienen correo registrado.")
        print("El resultado de cada envio queda en la bitacora.")

        # Los envios salen en un hilo de fondo. Sin esperarlos, el
        # proceso termina y los mata antes de que lleguen a salir.
        # Se esperan SOLO los hilos de correo: el pool de la base y
        # el servidor tienen los suyos, y esperarlos colgaria el
        # script para siempre.
        if not esperar_envios(120):
            print()
            print("AVISO: pasaron 2 minutos y algun correo seguia saliendo.")
            print("Puede haber llegado igual. Revisa la bitacora.")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
