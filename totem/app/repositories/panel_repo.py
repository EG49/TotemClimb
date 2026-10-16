"""Consultas del Panel general: estadísticas y avisos.

Los avisos son las tres cosas que el personal necesita ver al abrir el
sistema: membresías por vencer, menores que cumplieron 18 y siguen con
representante, y facturas fiadas sin saldar.
"""

from datetime import date

from app.db import obtener_cursor

DIAS_AVISO = 7


class PanelRepositorio:

    def estadisticas(self) -> dict:
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT
                  (SELECT count(DISTINCT id_cliente) FROM membresias
                    WHERE estado = 'ACTIVA' AND fecha_fin >= CURRENT_DATE)
                    AS membresias_activas,
                  (SELECT count(DISTINCT id_cliente) FROM membresias
                    WHERE estado = 'ACTIVA'
                      AND fecha_fin BETWEEN CURRENT_DATE AND CURRENT_DATE + %s)
                    AS vencen_pronto,
                  (SELECT COALESCE(SUM(total), 0) FROM facturas
                    WHERE estado = 'EMITIDA' AND fecha::date = CURRENT_DATE)
                    AS ingreso_hoy,
                  (SELECT count(*) FROM facturas
                    WHERE estado = 'EMITIDA' AND fecha::date = CURRENT_DATE)
                    AS facturas_hoy,
                  (SELECT COALESCE(SUM(saldo_pendiente), 0) FROM facturas
                    WHERE estado = 'PENDIENTE') AS por_cobrar,
                  (SELECT count(*) FROM clientes) AS total_clientes
                """,
                (DIAS_AVISO,),
            )
            return cursor.fetchone()

    def membresias_por_vencer(self, limite: int = 20) -> list[dict]:
        """Vencidas y por vencer, las más urgentes primero."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id_cliente,
                       c.nombre || ' ' || c.apellido AS cliente_nombre,
                       c.cedula, c.telefono,
                       m.fecha_fin,
                       (m.fecha_fin - CURRENT_DATE) AS dias,
                       p.nombre AS plan_nombre
                  FROM membresias m
                  JOIN clientes c ON c.id_cliente = m.id_cliente
                  JOIN planes_membresia p ON p.id_plan = m.id_plan
                 WHERE m.estado = 'ACTIVA'
                   AND m.fecha_fin <= CURRENT_DATE + %s
                   -- Solo la membresía más larga de cada cliente: si ya
                   -- renovó, no debe aparecer como por vencer.
                   AND m.fecha_fin = (
                         SELECT MAX(m2.fecha_fin) FROM membresias m2
                          WHERE m2.id_cliente = m.id_cliente AND m2.estado = 'ACTIVA'
                       )
                 ORDER BY m.fecha_fin
                 LIMIT %s
                """,
                (DIAS_AVISO, limite),
            )
            return cursor.fetchall()

    def mayoria_de_edad(self, limite: int = 20) -> list[dict]:
        """Menores que ya cumplieron 18 y siguen con representante."""
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id_cliente,
                       c.nombre || ' ' || c.apellido AS cliente_nombre,
                       c.fecha_nacimiento,
                       EXTRACT(YEAR FROM age(c.fecha_nacimiento))::int AS edad,
                       r.nombre || ' ' || r.apellido AS representante_nombre
                  FROM clientes c
                  JOIN clientes r ON r.id_cliente = c.id_representante
                 WHERE c.id_representante IS NOT NULL
                   AND c.fecha_nacimiento IS NOT NULL
                   AND age(c.fecha_nacimiento) >= INTERVAL '18 years'
                 ORDER BY c.fecha_nacimiento
                 LIMIT %s
                """,
                (limite,),
            )
            return cursor.fetchall()

    def fiadas_pendientes(self, limite: int = 20) -> list[dict]:
        with obtener_cursor() as cursor:
            cursor.execute(
                """
                SELECT f.id_factura, f.numero_factura, f.fecha, f.total,
                       f.saldo_pendiente,
                       c.id_cliente,
                       c.nombre || ' ' || c.apellido AS cliente_nombre,
                       (CURRENT_DATE - f.fecha::date) AS dias_desde
                  FROM facturas f
                  JOIN clientes c ON c.id_cliente = f.id_cliente
                 WHERE f.estado = 'PENDIENTE'
                 ORDER BY f.fecha
                 LIMIT %s
                """,
                (limite,),
            )
            return cursor.fetchall()
