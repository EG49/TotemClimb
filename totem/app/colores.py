"""Colores legibles para texto sobre un fondo del mismo tono.

El calendario pinta cada evento con el color de su categoría: ese
color de fondo, aclarado, y ese mismo color para el texto. Con un
color claro el texto queda ilegible —el aviso de cumpleaños daba
3.05:1, muy por debajo del 4.5:1 que hace falta—, y no se puede
resolver eligiendo a mano: las categorías las crea el gimnasio y
puede agregar las que quiera.

Así que el texto se oscurece solo hasta que se lee, conservando el
tono. El fondo no se toca: lo que identifica a la categoría de un
vistazo es el color del recuadro, no el de las letras.
"""

MINIMO = 4.5

# Cuánto del color se mezcla con el blanco para el fondo. Es el "22"
# del final del color en la plantilla: 0x22 = 34, sobre 255.
TRANSPARENCIA_FONDO = 34 / 255

# Sobre qué se apoya ese fondo semitransparente. No es el blanco: en
# el calendario, los días del mes vecino tienen su propio gris
# (rgba(204,204,204,0.14) en .celda.fuera), y el recuadro del evento
# se mezcla encima. Asumiendo blanco, el contraste calculado sale
# mejor que el real y los avisos de esos días quedaban en 4.42:1,
# apenas por debajo. Se parte del fondo más oscuro sobre el que la
# marca puede caer, así el cálculo vale para todos los casos.
FONDO_BASE = tuple(round(255 - 0.14 * (255 - 204)) for _ in range(3))


def _a_rgb(color: str) -> tuple[int, int, int] | None:
    color = (color or "").strip().lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    if len(color) != 6:
        return None
    try:
        return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _luminancia(rgb) -> float:
    def canal(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def contraste(uno, otro) -> float:
    a, b = _luminancia(uno), _luminancia(otro)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def sobre_blanco(rgb, parte: float, base=None) -> tuple[float, float, float]:
    """El color mezclado con el fondo de abajo, que es lo que se ve.

    Se sigue llamando así porque ese fondo casi siempre es blanco; el
    parámetro ``base`` existe para los casos en que no lo es.
    """
    debajo = FONDO_BASE if base is None else base
    return tuple(c * parte + d * (1 - parte) for c, d in zip(rgb, debajo))


def legible(color: str, por_omision: str = "#2B3210") -> str:
    """Devuelve ese color oscurecido lo necesario para poder leerlo.

    Se lo oscurece de a poco, conservando el tono, hasta llegar al
    mínimo contra el fondo que produce ese mismo color aclarado. Si
    ni el negro alcanzara —no pasa con fondos claros, pero por si
    acaso— devuelve el color de texto de siempre.
    """
    rgb = _a_rgb(color)
    if rgb is None:
        return por_omision

    fondo = sobre_blanco(rgb, TRANSPARENCIA_FONDO)

    candidato = list(rgb)
    for _ in range(60):
        # Se mide el color YA redondeado a enteros, que es el que se
        # va a usar. Midiendo el de decimales, el redondeo posterior
        # baja un poco el contraste y hay colores que terminan en
        # 4.48:1 habiendo "pasado" la comprobacion.
        entero = tuple(round(c) for c in candidato)
        if contraste(entero, fondo) >= MINIMO:
            return "#%02X%02X%02X" % entero
        candidato = [c * 0.92 for c in candidato]

    return por_omision
