"""Prueba del color de texto legible sobre un fondo del mismo tono.

El calendario pinta cada evento con el color de su categoria, usado a
la vez de fondo aclarado y de texto. Con un color claro el texto
queda ilegible, y no se puede resolver eligiendo colores a mano:
las categorias las crea el gimnasio.

Se prueba contra TODOS los colores, no contra unos pocos elegidos:
si alguno quedara por debajo del minimo, aparece aca y no en la
pantalla de alguien.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.colores import (  # noqa: E402
    MINIMO, TRANSPARENCIA_FONDO, _a_rgb, contraste, legible, sobre_blanco,
)

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


def razon_de(color):
    """El contraste que da ese color ya corregido, sobre su fondo."""
    fondo = sobre_blanco(_a_rgb(color), TRANSPARENCIA_FONDO)
    return contraste(_a_rgb(legible(color)), fondo)


print("\nLOS COLORES QUE USA HOY EL GIMNASIO")
for color, nombre in (
    ("#3395A0", "turquesa de marca"),
    ("#C2DD58", "lima"),
    ("#2B3210", "verde oscuro"),
):
    razon = razon_de(color)
    revisar(f"{nombre} ({color}): {razon:.2f}:1", razon >= MINIMO, f"{razon:.2f}")

print("\nUN COLOR YA OSCURO NO SE TOCA")
revisar("el verde oscuro queda igual", legible("#2B3210") == "#2B3210",
        legible("#2B3210"))

print("\nLOS CASOS DIFICILES")
for color, nombre in (
    ("#FFFFFF", "blanco"),
    ("#FFFF00", "amarillo"),
    ("#00FF00", "verde brillante"),
    ("#FFC0CB", "rosa claro"),
):
    razon = razon_de(color)
    revisar(f"{nombre} ({color}): {razon:.2f}:1", razon >= MINIMO, f"{razon:.2f}")

print("\nTODOS LOS COLORES POSIBLES")
# De a 17 por canal: 4913 colores repartidos por todo el espectro.
peor = (None, 99.0)
malos = 0
for r in range(0, 256, 17):
    for g in range(0, 256, 17):
        for b in range(0, 256, 17):
            color = "#%02X%02X%02X" % (r, g, b)
            razon = razon_de(color)
            if razon < MINIMO:
                malos += 1
            if razon < peor[1]:
                peor = (color, razon)
revisar("ninguno queda por debajo del minimo", malos == 0,
        f"{malos} colores fallan, el peor {peor[0]} con {peor[1]:.2f}:1")
print(f"         el mas justo fue {peor[0]} con {peor[1]:.2f}:1")

print("\nUN COLOR QUE NO SE ENTIENDE NO ROMPE NADA")
for valor in ("", "raro", "#12", None, "#GGGGGG"):
    revisar(f"{valor!r} cae al color de siempre",
            legible(valor) == "#2B3210", legible(valor))

print("\nSE ADMITE LA FORMA CORTA")
revisar("#3A0 se entiende igual que #33AA00",
        legible("#3A0") == legible("#33AA00"),
        f"{legible('#3A0')} vs {legible('#33AA00')}")

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
