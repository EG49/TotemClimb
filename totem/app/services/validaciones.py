"""Validaciones compartidas entre módulos.

Centralizarlas evita que cada formulario invente sus propias reglas y que
los mensajes de error cambien de una pantalla a otra.
"""

import re
from datetime import date

RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


class ErrorValidacion(Exception):
    """Agrupa los errores de un formulario: {campo: mensaje}."""

    def __init__(self, errores: dict[str, str]):
        self.errores = errores
        super().__init__("; ".join(f"{k}: {v}" for k, v in errores.items()))


def validar_cedula(cedula: str) -> bool:
    """Valida una cédula ecuatoriana con su dígito verificador.

    Reglas: 10 dígitos; los dos primeros son el código de provincia
    (01 a 24, o 30 para ecuatorianos registrados en el exterior); el
    tercero es menor a 6 para personas naturales. El último dígito se
    verifica con el algoritmo módulo 10.
    """
    if not cedula or not cedula.isdigit() or len(cedula) != 10:
        return False

    provincia = int(cedula[:2])
    if not (1 <= provincia <= 24 or provincia == 30):
        return False

    if int(cedula[2]) >= 6:
        return False

    coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    suma = 0
    for digito, coeficiente in zip(cedula[:9], coeficientes):
        producto = int(digito) * coeficiente
        suma += producto - 9 if producto > 9 else producto

    verificador = (10 - (suma % 10)) % 10
    return verificador == int(cedula[9])


def validar_correo(correo: str) -> bool:
    return bool(RE_CORREO.match(correo.strip()))


def validar_celular(celular: str) -> bool:
    """Celular ecuatoriano: 10 dígitos que empiezan en 09."""
    limpio = solo_digitos(celular)
    return len(limpio) == 10 and limpio.startswith("09")


def solo_digitos(texto: str) -> str:
    """Quita espacios, guiones y paréntesis de un número."""
    return re.sub(r"\D", "", texto or "")


def validar_fecha_nacimiento(fecha: date) -> str | None:
    """Devuelve el mensaje de error, o None si la fecha es razonable."""
    hoy = date.today()
    if fecha > hoy:
        return "La fecha de nacimiento no puede ser futura."
    if fecha.year < hoy.year - 120:
        return "Revisa la fecha de nacimiento, parece equivocada."
    return None


def limpiar(valor: str | None) -> str | None:
    """Normaliza un campo opcional: espacios fuera, vacío se vuelve None."""
    if valor is None:
        return None
    valor = valor.strip()
    return valor or None
