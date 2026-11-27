"""Un plan atado a un día avisa, pero deja cobrar.

"Promo jueves (2 personas)" se podía cobrar un lunes y nada se
quejaba: el jueves estaba en el nombre del plan y nadie lo revisaba.

Lo que se comprueba es que avise el día equivocado, que NO avise el
día correcto, y que confirmando se pueda cobrar igual. Esa última es
la que importa: un aviso que no se puede saltar es un bloqueo, y el
gimnasio quiere poder honrar la promo otro día.

Se valida por el camino de verdad, el mismo que usa la pantalla. Para
no dejar ventas de prueba en la base, el cobro va siempre sin cliente:
así termina en error de validación antes de guardar nada, y lo que se
mira es si el aviso del día está entre los errores o no.

    python -m pruebas.plan_dia_semana
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crear_app                                   # noqa: E402
from app.db import obtener_cursor                            # noqa: E402
from app.models.catalogo import DIAS_SEMANA                  # noqa: E402
from app.services.cobro_service import CobroService          # noqa: E402
from app.services.validaciones import ErrorValidacion        # noqa: E402

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


app = crear_app()
with app.app_context():
    servicio = CobroService()
    hoy = date.today().weekday()

    with obtener_cursor() as cursor:
        cursor.execute(
            "SELECT id_plan, nombre, dia_semana FROM planes_membresia "
            " WHERE activo = TRUE ORDER BY id_plan LIMIT 1"
        )
        plan = cursor.fetchone()

    if plan is None:
        print("Hace falta un plan activo. Se omite.")
        sys.exit(1 if fallas else 0)

    dia_original = plan["dia_semana"]
    id_plan = plan["id_plan"]

    def poner_dia(dia):
        with obtener_cursor(commit=True) as cursor:
            cursor.execute(
                "UPDATE planes_membresia SET dia_semana = %s WHERE id_plan = %s",
                (dia, id_plan),
            )

    def errores_al_cobrar(confirmar=False):
        """Cobra a propósito sin cliente: devuelve los errores.

        Sin cliente nunca llega a guardar, así que la prueba no deja
        facturas ni membresías detrás.
        """
        formulario = {"forma_cobro": "COMPLETO", "metodo_pago": "EFECTIVO"}
        if confirmar:
            formulario["confirmar_dia"] = "si"
        try:
            servicio.cobrar(
                formulario,
                [{"tipo": "plan", "id_item": id_plan, "cantidad": 1}],
                id_empleado=1,
            )
            return {}
        except ErrorValidacion as error:
            return error.errores

    try:
        print(f"\nHOY ES {DIAS_SEMANA[hoy].upper()}")

        print("\nEL DÍA EQUIVOCADO AVISA")
        otro_dia = (hoy + 1) % 7
        poner_dia(otro_dia)
        errores = errores_al_cobrar()
        revisar("avisa cuando el plan es de otro día",
                "dia_semana" in errores, str(errores))
        revisar("y nombra los dos días, el del plan y el de hoy",
                DIAS_SEMANA[otro_dia] in errores.get("dia_semana", "")
                and DIAS_SEMANA[hoy] in errores.get("dia_semana", ""),
                errores.get("dia_semana", ""))

        print("\nCONFIRMANDO SE PUEDE COBRAR IGUAL")
        # La que importa: el aviso se tiene que poder saltar. Si no,
        # es un bloqueo, y eso no fue lo que se pidió.
        con_confirmacion = errores_al_cobrar(confirmar=True)
        revisar("con la confirmación ya no avisa",
                "dia_semana" not in con_confirmacion, str(con_confirmacion))

        print("\nEL DÍA CORRECTO NO MOLESTA")
        poner_dia(hoy)
        revisar("no avisa cuando es el día del plan",
                "dia_semana" not in errores_al_cobrar())
        poner_dia(None)
        revisar("ni cuando el plan no está atado a ningún día",
                "dia_semana" not in errores_al_cobrar())

        print("\nTODOS LOS DÍAS SE COMPORTAN IGUAL")
        # Sin esto, contar el lunes como 1 en vez de 0 pasaría
        # desapercibido salvo el día exacto en que se corra la prueba.
        for dia in range(7):
            poner_dia(dia)
            errores = errores_al_cobrar()
            deberia = dia != hoy
            revisar(f"{DIAS_SEMANA[dia]}: "
                    + ("avisa" if deberia else "no avisa"),
                    ("dia_semana" in errores) == deberia,
                    str(errores.get("dia_semana", "sin aviso")))
    finally:
        # El plan vuelve como estaba, pase lo que pase.
        poner_dia(dia_original)

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
