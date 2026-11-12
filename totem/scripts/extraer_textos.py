"""Extrae de las plantillas los textos de ayuda de los formularios.

Marcadores (placeholder), pistas y notas de seccion, ordenados por
pantalla y con el numero de linea para poder encontrarlos.

Genera el cuerpo de docs/textos-de-formularios.txt. Se extrae en
lugar de escribirse a mano para que no se desactualice en silencio
cuando alguien agrega un campo.

    python -m scripts.extraer_textos > textos.txt
"""
import pathlib
import re
import sys
import textwrap

# Relativo a este archivo, para poder correrlo desde donde sea.
RAIZ = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates"

# Nombre legible de cada pantalla, en el orden en que se usan.
PANTALLAS = [
    ("panel.html", "Panel de inicio"),
    ("clientes/lista.html", "Clientes (lista)"),
    ("clientes/formulario.html", "Cliente (alta y edicion)"),
    ("clientes/menor.html", "Menor a cargo"),
    ("cobrar/cobrar.html", "Cobrar"),
    ("facturas/lista.html", "Facturas"),
    ("contabilidad/reporte.html", "Contabilidad"),
    ("contabilidad/balance.html", "Balance general"),
    ("gastos/lista.html", "Gastos (lista)"),
    ("gastos/formulario.html", "Gasto (alta y correccion)"),
    ("posibles/lista.html", "Posibles clientes (lista)"),
    ("posibles/formulario.html", "Posible cliente (agendar)"),
    ("calendario/ver.html", "Calendario"),
    ("calendario/evento.html", "Evento"),
    ("calendario/agenda.html", "Agenda"),
    ("catalogo/formulario.html", "Catalogo (alta de item)"),
    ("empleados/lista.html", "Empleados (lista)"),
    ("empleados/formulario.html", "Empleado (alta y edicion)"),
    ("configuracion.html", "Configuracion"),
]


def envuelto(texto, sangria, ancho=62):
    """Parte el texto para que ninguna linea pase de ~78 caracteres.

    Notepad no envuelve: una linea larga obliga a desplazarse de
    lado, y esta lista se lee de corrido.
    """
    lineas = textwrap.wrap(texto, width=ancho) or [""]
    salida = []
    for i, l in enumerate(lineas):
        comilla_ini = '"' if i == 0 else " "
        comilla_fin = '"' if i == len(lineas) - 1 else ""
        salida.append(f"{sangria}{comilla_ini}{l}{comilla_fin}")
    return salida


def limpiar(t):
    """Quita el marcado de Jinja y los espacios de mas."""
    t = re.sub(r"\{\{.*?\}\}", "«dato»", t, flags=re.S)
    t = re.sub(r"\{%.*?%\}", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    return " ".join(t.split())


def campo_de(linea, lineas, i):
    """Busca el name= o id= del campo al que pertenece el texto."""
    for j in range(i, max(-1, i - 6), -1):
        m = re.search(r'(?:name|id)\s*=\s*"([a-z_0-9]+)"', lineas[j])
        if m:
            return m.group(1)
        m = re.search(r"campo\(\s*'([a-z_0-9]+)'", lineas[j])
        if m:
            return m.group(1)
    return ""


def etiqueta_de(lineas, i):
    """La etiqueta visible mas cercana hacia arriba."""
    for j in range(i, max(-1, i - 8), -1):
        m = re.search(r"<label[^>]*>([^<]{2,60})</label>", lineas[j])
        if m:
            return limpiar(m.group(1))
        m = re.search(r"campo\(\s*'[a-z_0-9]+'\s*,\s*'([^']{2,60})'", lineas[j])
        if m:
            return m.group(1)
    return ""


def extraer(ruta):
    p = RAIZ / ruta
    if not p.exists():
        return []
    lineas = p.read_text(encoding="utf-8").split("\n")
    hallazgos = []
    for i, linea in enumerate(lineas):
        for m in re.finditer(r'placeholder\s*=\s*"([^"]+)"', linea):
            hallazgos.append(("MARCADOR", i + 1, campo_de(linea, lineas, i),
                              etiqueta_de(lineas, i), limpiar(m.group(1))))
        for m in re.finditer(r"marcador\s*=\s*'([^']+)'", linea):
            hallazgos.append(("MARCADOR", i + 1, campo_de(linea, lineas, i),
                              etiqueta_de(lineas, i), limpiar(m.group(1))))
        for m in re.finditer(r'marcador\s*=\s*"([^"]+)"', linea):
            hallazgos.append(("MARCADOR", i + 1, campo_de(linea, lineas, i),
                              etiqueta_de(lineas, i), limpiar(m.group(1))))
        for m in re.finditer(r'class="pista"[^>]*>(.*?)</div>', linea, re.S):
            t = limpiar(m.group(1))
            if t:
                hallazgos.append(("PISTA", i + 1, campo_de(linea, lineas, i),
                                  etiqueta_de(lineas, i), t))
        for m in re.finditer(r'class="seccion-nota"[^>]*>(.*?)</div>', linea, re.S):
            t = limpiar(m.group(1))
            if t:
                hallazgos.append(("NOTA", i + 1, "", "", t))
    return hallazgos


# Las pistas y notas suelen abarcar varias lineas; se juntan antes.
def texto_plano(ruta):
    p = RAIZ / ruta
    return p.read_text(encoding="utf-8") if p.exists() else ""


def multilinea(ruta, clase):
    s = texto_plano(ruta)
    salida = []
    for m in re.finditer(rf'class="{clase}"[^>]*>(.*?)</div>', s, re.S):
        t = limpiar(m.group(1))
        if t:
            linea = s[: m.start()].count("\n") + 1
            salida.append((linea, t))
    return salida


def main():
    salida = []
    for ruta, titulo in PANTALLAS:
        # Se descarta la definicion del macro: su placeholder es la
        # variable, no un texto que se pueda cambiar.
        hallazgos = [h for h in extraer(ruta)
                     if h[0] == "MARCADOR" and "«dato»" not in h[4]]
        pistas = multilinea(ruta, "pista")
        notas = multilinea(ruta, "seccion-nota")
        if not (hallazgos or pistas or notas):
            continue

        salida.append("")
        salida.append("=" * 63)
        salida.append(f" {titulo.upper()}")
        salida.append(f" {ruta}")
        salida.append("=" * 63)

        if hallazgos:
            salida.append("")
            salida.append("  MARCADORES (el texto gris dentro del campo vacio)")
            salida.append("")
            for _, linea, campo, etiqueta, texto in hallazgos:
                nombre = etiqueta or campo or "?"
                salida.append(f"    linea {linea:>4}  [{campo or '-'}] {nombre}")
                salida.extend(envuelto(texto, "               "))
                salida.append("")

        if pistas:
            salida.append("  PISTAS (la explicacion gris debajo del campo)")
            salida.append("")
            for linea, texto in pistas:
                salida.append(f"    linea {linea:>4}")
                salida.extend(envuelto(texto, "               "))
                salida.append("")

        if notas:
            salida.append("  NOTAS DE SECCION (la bajada debajo de un titulo)")
            salida.append("")
            for linea, texto in notas:
                salida.append(f"    linea {linea:>4}")
                salida.extend(envuelto(texto, "               "))
                salida.append("")

    print("\n".join(salida))


if __name__ == "__main__":
    main()
