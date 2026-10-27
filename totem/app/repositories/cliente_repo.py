"""Repositorio de clientes: todo el SQL de la tabla clientes.

El listado trae además la membresía activa de cada cliente, para que la
vista pueda mostrar plan, estado y vencimiento sin consultar de nuevo.
"""

from app.db import obtener_cursor
from app.models.cliente import Cliente

# Campos que se escriben al crear o actualizar un cliente.
CAMPOS = (
    "nombre",
    "apellido",
    "cedula",
    "fecha_nacimiento",
    "correo",
    "telefono",
    "genero",
    "contacto_emergencia",
    "referencia",
    "seguro_nombre",
    "seguro_numero",
    "id_representante",
)

# Trae la membresía ACTIVA más reciente de cada cliente. LATERAL permite
# usar c.id_cliente dentro de la subconsulta.
_SELECT_BASE = """
    SELECT c.id_cliente, c.nombre, c.apellido, c.cedula, c.fecha_nacimiento,
           c.correo, c.telefono, c.genero, c.contacto_emergencia, c.referencia,
           c.seguro_nombre, c.seguro_numero, c.id_representante, c.fecha_registro,
           r.nombre || ' ' || r.apellido AS representante_nombre,
           (SELECT count(*) FROM clientes h
             WHERE h.id_representante = c.id_cliente) AS menores_a_cargo,
           m.fecha_fin, m.dias_totales, m.dias_restantes,
           p.nombre AS plan_nombre, p.tipo AS plan_tipo
      FROM clientes c
      LEFT JOIN clientes r ON r.id_cliente = c.id_representante
      LEFT JOIN LATERAL (
            SELECT me.fecha_fin, me.dias_totales, me.dias_restantes, me.id_plan
              FROM membresias me
             WHERE me.id_cliente = c.id_cliente
               AND me.estado = 'ACTIVA'
             ORDER BY me.fecha_fin DESC
             LIMIT 1
      ) m ON TRUE
      LEFT JOIN planes_membresia p ON p.id_plan = m.id_plan
"""

# Condición SQL de cada chip de filtro del listado.
_FILTROS = {
    "todos": None,
    "vigentes": "m.fecha_fin >= CURRENT_DATE",
    "por_vencer": "m.fecha_fin BETWEEN CURRENT_DATE AND CURRENT_DATE + 7",
    "vencidos": "(m.fecha_fin < CURRENT_DATE OR m.fecha_fin IS NULL)",
    "menores": "c.id_representante IS NOT NULL",
}


class ClienteRepositorio:

    def _condiciones(self, busqueda: str | None, filtro: str):
        condiciones, parametros = [], []

        if busqueda:
            condiciones.append(
                "(c.nombre ILIKE %s OR c.apellido ILIKE %s "
                " OR (c.nombre || ' ' || c.apellido) ILIKE %s "
                " OR c.cedula LIKE %s OR c.correo ILIKE %s)"
            )
            patron = f"%{busqueda}%"
            parametros += [patron, patron, patron, patron, patron]

        condicion_filtro = _FILTROS.get(filtro)
        if condicion_filtro:
            condiciones.append(condicion_filtro)

        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
        return where, parametros

    def listar(
        self,
        busqueda: str | None = None,
        filtro: str = "todos",
        pagina: int = 1,
        por_pagina: int = 20,
    ) -> list[Cliente]:
        where, parametros = self._condiciones(busqueda, filtro)
        desplazamiento = (max(pagina, 1) - 1) * por_pagina

        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                {_SELECT_BASE}
                {where}
                ORDER BY c.nombre, c.apellido
                LIMIT %s OFFSET %s
                """,
                parametros + [por_pagina, desplazamiento],
            )
            return [Cliente.desde_fila(f) for f in cursor.fetchall()]

    def contar(self, busqueda: str | None = None, filtro: str = "todos") -> int:
        where, parametros = self._condiciones(busqueda, filtro)
        with obtener_cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*) AS total
                  FROM clientes c
                  LEFT JOIN LATERAL (
                        SELECT me.fecha_fin FROM membresias me
                         WHERE me.id_cliente = c.id_cliente AND me.estado = 'ACTIVA'
                         ORDER BY me.fecha_fin DESC LIMIT 1
                  ) m ON TRUE
                {where}
                """,
                parametros,
            )
            return cursor.fetchone()["total"]

    def contar_por_filtro(self) -> dict[str, int]:
        """Conteo de cada chip, para mostrarlo junto a su etiqueta."""
        conteos = {}
        for nombre in _FILTROS:
            conteos[nombre] = self.contar(filtro=nombre)
        return conteos

    def obtener(self, id_cliente: int) -> Cliente | None:
        with obtener_cursor() as cursor:
            cursor.execute(f"{_SELECT_BASE} WHERE c.id_cliente = %s", (id_cliente,))
            fila = cursor.fetchone()
        return Cliente.desde_fila(fila) if fila else None

    def menores_de(self, id_representante: int) -> list[Cliente]:
        with obtener_cursor() as cursor:
            cursor.execute(
                f"{_SELECT_BASE} WHERE c.id_representante = %s "
                "ORDER BY c.fecha_nacimiento",
                (id_representante,),
            )
            return [Cliente.desde_fila(f) for f in cursor.fetchall()]

    def cedula_ocupada(self, cedula: str, excluir_id: int | None = None) -> bool:
        with obtener_cursor() as cursor:
            if excluir_id:
                cursor.execute(
                    "SELECT 1 FROM clientes WHERE cedula = %s AND id_cliente <> %s",
                    (cedula, excluir_id),
                )
            else:
                cursor.execute("SELECT 1 FROM clientes WHERE cedula = %s", (cedula,))
            return cursor.fetchone() is not None

    # --- Escritura ---------------------------------------------------
    # crear() y actualizar() reciben un cursor opcional para poder
    # encadenar varias escrituras en una sola transacción (por ejemplo,
    # el representante y sus menores al dar de alta).

    def crear(self, datos: dict, cursor=None) -> int:
        valores = [datos.get(c) for c in CAMPOS]
        marcadores = ", ".join(["%s"] * len(CAMPOS))
        sql = f"""
            INSERT INTO clientes ({", ".join(CAMPOS)})
            VALUES ({marcadores})
            RETURNING id_cliente
        """
        if cursor is not None:
            cursor.execute(sql, valores)
            return cursor.fetchone()["id_cliente"]

        with obtener_cursor(commit=True) as c:
            c.execute(sql, valores)
            return c.fetchone()["id_cliente"]

    def actualizar(self, id_cliente: int, datos: dict, cursor=None) -> None:
        campos = [c for c in CAMPOS if c in datos]
        if not campos:
            return
        asignaciones = ", ".join(f"{c} = %s" for c in campos)
        valores = [datos[c] for c in campos] + [id_cliente]
        sql = f"UPDATE clientes SET {asignaciones} WHERE id_cliente = %s"

        if cursor is not None:
            cursor.execute(sql, valores)
            return

        with obtener_cursor(commit=True) as c:
            c.execute(sql, valores)
