"""Repositorio de gastos. Todo el SQL de gastos vive acá."""

from datetime import date

from app.db import obtener_cursor
from app.models.gasto import ANULADO, REGISTRADO, Gasto

# Campos que escribe el formulario. El estado y el motivo de
# anulación no están: los maneja anular(), no el alta ni la edición.
CAMPOS = (
    "fecha",
    "monto",
    "segmento",
    "concepto",
    "facturado",
    "descripcion",
    "metodo_pago",
)

_SELECT = """
    SELECT g.id_gasto, g.fecha, g.monto, g.segmento, g.concepto,
           g.facturado, g.descripcion, g.metodo_pago, g.id_empleado,
           g.estado, g.motivo_anulacion, g.fecha_registro,
           e.nombre || ' ' || e.apellido AS empleado_nombre
      FROM gastos g
      JOIN empleados e ON e.id_empleado = g.id_empleado
"""


class GastoRepositorio:

    # --- Lectura ------------------------------------------------------

    def listar(
        self,
        desde: date,
        hasta: date,
        segmento: str = "todos",
        facturado: str = "todos",
        estado: str = "activos",
        q: str = "",
        pagina: int = 1,
        por_pagina: int = 50,
    ) -> tuple[list[Gasto], int]:
        """Devuelve la página pedida y el total de gastos que cumplen el filtro."""
        condiciones = ["g.fecha BETWEEN %s AND %s"]
        valores: list = [desde, hasta]

        if segmento != "todos":
            condiciones.append("g.segmento = %s")
            valores.append(segmento)

        if facturado == "si":
            condiciones.append("g.facturado = TRUE")
        elif facturado == "no":
            condiciones.append("g.facturado = FALSE")

        if estado == "activos":
            condiciones.append("g.estado = %s")
            valores.append(REGISTRADO)
        elif estado == "anulados":
            condiciones.append("g.estado = %s")
            valores.append(ANULADO)

        if q:
            condiciones.append(
                "(g.concepto ILIKE %s OR g.descripcion ILIKE %s)"
            )
            valores.extend([f"%{q}%", f"%{q}%"])

        where = " WHERE " + " AND ".join(condiciones)

        with obtener_cursor() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) AS n FROM gastos g {where}", valores
            )
            total = cursor.fetchone()["n"]

            cursor.execute(
                f"""
                {_SELECT}
                {where}
                 ORDER BY g.fecha DESC, g.id_gasto DESC
                 LIMIT %s OFFSET %s
                """,
                valores + [por_pagina, max(0, (pagina - 1) * por_pagina)],
            )
            gastos = [Gasto.desde_fila(f) for f in cursor.fetchall()]

        return gastos, total

    def obtener(self, id_gasto: int) -> Gasto | None:
        with obtener_cursor() as cursor:
            cursor.execute(f"{_SELECT} WHERE g.id_gasto = %s", (id_gasto,))
            fila = cursor.fetchone()
        return Gasto.desde_fila(fila) if fila else None

    def resumen(self, desde: date, hasta: date) -> dict:
        """Totales del período. Los anulados no suman en ningún lado."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(SUM(monto), 0) AS total,
                       COUNT(*) AS n,
                       COALESCE(SUM(monto) FILTER (WHERE facturado), 0) AS facturado,
                       COALESCE(SUM(monto) FILTER (WHERE NOT facturado), 0) AS sin_factura,
                       COALESCE(SUM(monto) FILTER (WHERE segmento = 'JUNIOR'), 0) AS junior,
                       COALESCE(SUM(monto) FILTER (WHERE segmento = 'SENIOR'), 0) AS senior,
                       COALESCE(SUM(monto) FILTER (WHERE segmento = 'GENERAL'), 0) AS general
                  FROM gastos
                 WHERE estado = %s AND fecha BETWEEN %s AND %s
                """,
                (REGISTRADO, desde, hasta),
            )
            return dict(cursor.fetchone())

    def por_concepto(self, desde: date, hasta: date) -> list[dict]:
        """Agrupa el gasto del período por concepto, de mayor a menor."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT concepto,
                       SUM(monto) AS monto,
                       COUNT(*) AS veces,
                       SUM(monto) FILTER (WHERE facturado) AS facturado
                  FROM gastos
                 WHERE estado = %s AND fecha BETWEEN %s AND %s
                 GROUP BY concepto
                 ORDER BY SUM(monto) DESC
                """,
                (REGISTRADO, desde, hasta),
            )
            return [dict(f) for f in cursor.fetchall()]

    def conceptos_usados(self, limite: int = 40) -> list[str]:
        """Conceptos ya usados, los más frecuentes primero.

        Alimenta las sugerencias del formulario: escribir el mismo
        concepto de dos formas distintas parte el balance en dos
        filas, así que conviene empujar a reusar los existentes.
        """
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT concepto
                  FROM gastos
                 GROUP BY concepto
                 ORDER BY COUNT(*) DESC, max(fecha) DESC
                 LIMIT %s
                """,
                (limite,),
            )
            return [f["concepto"] for f in cursor.fetchall()]

    def concepto_canonico(self, texto: str) -> str | None:
        """La escritura ya usada para ese concepto, ignorando mayúsculas.

        Si alguien carga "MAGNESIO" y en la base ya hay "Magnesio", el
        balance tendría dos filas del mismo gasto. Devolver la forma
        existente hace que gane la primera escritura, sin tener que
        imponer un formato que arruinaría nombres como "Pago SRI".
        """
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT concepto
                  FROM gastos
                 WHERE lower(concepto) = lower(%s)
                 GROUP BY concepto
                 ORDER BY COUNT(*) DESC
                 LIMIT 1
                """,
                (texto,),
            )
            fila = cursor.fetchone()
        return fila["concepto"] if fila else None

    def recurrentes_del_mes_anterior(self, desde: date) -> list[dict]:
        """Gastos del mes previo al período, para ofrecer repetirlos.

        Se mira el mes anterior porque los gastos fijos (arriendo,
        luz, sueldos) se repiten mes a mes con el mismo concepto. Se
        devuelve el último monto de cada concepto como referencia,
        no como valor definitivo.
        """
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (concepto)
                       concepto, monto, segmento, facturado, metodo_pago
                  FROM gastos
                 WHERE estado = %s
                   AND fecha >= (date_trunc('month', %s::date) - interval '1 month')
                   AND fecha <  date_trunc('month', %s::date)
                 ORDER BY concepto, fecha DESC
                """,
                (REGISTRADO, desde, desde),
            )
            return [dict(f) for f in cursor.fetchall()]

    # --- Escritura ----------------------------------------------------

    def crear(self, datos: dict, id_empleado: int, cursor=None) -> int:
        sql = f"""
            INSERT INTO gastos ({", ".join(CAMPOS)}, id_empleado)
            VALUES ({", ".join(["%s"] * len(CAMPOS))}, %s)
            RETURNING id_gasto
        """
        valores = [datos[c] for c in CAMPOS] + [id_empleado]

        if cursor is not None:
            cursor.execute(sql, valores)
            return cursor.fetchone()["id_gasto"]

        with obtener_cursor(commit=True) as propio:
            propio.execute(sql, valores)
            return propio.fetchone()["id_gasto"]

    def actualizar(self, id_gasto: int, datos: dict, cursor=None) -> None:
        sql = f"""
            UPDATE gastos
               SET {", ".join(f"{c} = %s" for c in CAMPOS)}
             WHERE id_gasto = %s
        """
        valores = [datos[c] for c in CAMPOS] + [id_gasto]

        if cursor is not None:
            cursor.execute(sql, valores)
            return

        with obtener_cursor(commit=True) as propio:
            propio.execute(sql, valores)

    def anular(self, id_gasto: int, motivo: str, cursor=None) -> None:
        """Marca el gasto como anulado. No se borra: queda en el historial."""
        sql = """
            UPDATE gastos
               SET estado = %s, motivo_anulacion = %s
             WHERE id_gasto = %s AND estado <> %s
        """
        valores = (ANULADO, motivo, id_gasto, ANULADO)

        if cursor is not None:
            cursor.execute(sql, valores)
            return

        with obtener_cursor(commit=True) as propio:
            propio.execute(sql, valores)
