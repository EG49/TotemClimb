"""Servicio de Contabilidad: arma el reporte de un período."""

from calendar import monthrange
from datetime import date, datetime, timedelta

from app.repositories.contabilidad_repo import ContabilidadRepositorio

DIA = "dia"
MES = "mes"
PERSONALIZADO = "personalizado"


def rango_del_periodo(periodo: str, desde=None, hasta=None) -> tuple[date, date, str]:
    """Traduce el selector de período a un rango concreto de fechas."""
    hoy = date.today()

    if periodo == MES:
        inicio = hoy.replace(day=1)
        fin = hoy.replace(day=monthrange(hoy.year, hoy.month)[1])
        etiqueta = inicio.strftime("%B de %Y").capitalize()
    elif periodo == PERSONALIZADO:
        inicio = _a_fecha(desde) or hoy - timedelta(days=30)
        fin = _a_fecha(hasta) or hoy
        if fin < inicio:
            inicio, fin = fin, inicio
        etiqueta = f"{inicio.strftime('%d/%m/%Y')} – {fin.strftime('%d/%m/%Y')}"
    else:
        inicio = fin = _a_fecha(desde) or hoy
        etiqueta = "Hoy" if inicio == hoy else inicio.strftime("%d/%m/%Y")

    return inicio, fin, etiqueta


def _a_fecha(texto):
    if not texto:
        return None
    try:
        return datetime.strptime(str(texto), "%Y-%m-%d").date()
    except ValueError:
        return None


class ContabilidadService:

    def __init__(self):
        self.repositorio = ContabilidadRepositorio()

    def reporte(self, desde: date, hasta: date, id_cliente: int | None = None) -> dict:
        r = self.repositorio
        resumen = r.resumen(desde, hasta, id_cliente)

        metodos = r.por_metodo_pago(desde, hasta, id_cliente)
        categorias = r.por_categoria(desde, hasta, id_cliente)

        return {
            "resumen": resumen,
            "metodos": self._con_porcentaje(metodos),
            "categorias": self._con_porcentaje(categorias),
            "mas_vendidos": r.mas_vendidos(desde, hasta, id_cliente),
            "por_dia": r.por_dia(desde, hasta, id_cliente),
            "vendedores": self._con_porcentaje(r.por_vendedor(desde, hasta, id_cliente)),
        }

    def _con_porcentaje(self, filas: list[dict]) -> list[dict]:
        """Agrega a cada fila su peso sobre el total, para las barras."""
        total = sum(f["monto"] for f in filas) or 1
        for fila in filas:
            fila["porcentaje"] = round(float(fila["monto"]) / float(total) * 100, 1)
        return filas
