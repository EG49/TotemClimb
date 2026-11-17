"""Prueba de contraste de las pantallas, con un navegador de verdad.

Mide el contraste entre cada texto y el fondo sobre el que termina
dibujado, y avisa de lo que no llega al minimo. No revisa la hoja de
estilos: abre las pantallas, lee los colores que el navegador aplico
de verdad y hace la cuenta. Un color heredado, una transparencia o un
color que una regla posterior piso se ven acá y no leyendo el CSS.

El minimo es el de las pautas WCAG 2.1 nivel AA:

  - texto normal          4.5 : 1
  - texto grande          3.0 : 1   (24px, o 19px si es negrita)
  - bordes de controles   3.0 : 1

Tambien revisa que el logo no quede invisible: el archivo del logo
tiene el oso y la palabra TOTEM en blanco sobre fondo transparente,
asi que sobre un fondo claro se pierde. Es lo que pasaba en el login.

Se corre desde la carpeta totem:

    python -m pruebas.contraste

Levanta la aplicacion en su propio puerto y la apaga al terminar.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("\nFalta playwright. Instalelo con:")
    print("  pip install playwright && python -m playwright install chromium")
    sys.exit(0)

PUERTO = int(os.environ.get("PUERTO_CONTRASTE", "5098"))
BASE = f"http://127.0.0.1:{PUERTO}"
USUARIO = os.environ.get("E2E_USUARIO", "admin")
CLAVE = os.environ.get("E2E_CLAVE", "Prueba12345")

MINIMO_NORMAL = 4.5
MINIMO_GRANDE = 3.0

fallos = []
avisos = []
_contador = [0]


def revisar(etiqueta, condicion, detalle=""):
    _contador[0] += 1
    print(("  OK   " if condicion else "  FALLA") + "  " + etiqueta
          + (f"  -> {detalle}" if detalle and not condicion else ""))
    if not condicion:
        fallos.append(etiqueta)


def puerto_libre(puerto):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", puerto)) != 0


def levantar():
    if not puerto_libre(PUERTO):
        print(f"El puerto {PUERTO} ya esta ocupado. Se usa lo que haya ahi.")
        return None
    proceso = subprocess.Popen(
        [sys.executable, "-m", "flask", "--app", "run:app", "run",
         "--port", str(PUERTO)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    for _ in range(50):
        if not puerto_libre(PUERTO):
            return proceso
        if proceso.poll() is not None:
            print("La aplicacion no arranco:")
            print(proceso.stderr.read().decode("utf-8", "replace")[-1500:])
            sys.exit(1)
        time.sleep(0.3)
    print("La aplicacion no respondio a tiempo.")
    sys.exit(1)


# El calculo del contraste corre dentro del navegador: ahi estan los
# colores ya resueltos, con herencia y transparencias aplicadas.
MEDIDOR = r"""
() => {
  const aRGB = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x.trim()));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };

  // Un color con transparencia se mezcla con lo que tiene detras.
  const mezclar = (frente, fondo) => ({
    r: frente.r * frente.a + fondo.r * (1 - frente.a),
    g: frente.g * frente.a + fondo.g * (1 - frente.a),
    b: frente.b * frente.a + fondo.b * (1 - frente.a),
    a: 1,
  });

  const luminancia = (c) => {
    const f = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };

  const razon = (a, b) => {
    const la = luminancia(a), lb = luminancia(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };

  // El fondo efectivo: se sube por los padres hasta encontrar uno
  // opaco, mezclando las capas semitransparentes que haya en medio.
  const fondoDe = (el) => {
    let capas = [], nodo = el, degradado = false;
    while (nodo && nodo !== document.documentElement.parentNode) {
      const e = getComputedStyle(nodo);
      if (e.backgroundImage && e.backgroundImage !== 'none') degradado = true;
      const c = aRGB(e.backgroundColor);
      if (c && c.a > 0) {
        capas.push(c);
        if (c.a === 1) break;
      }
      nodo = nodo.parentElement;
    }
    let fondo = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = capas.length - 1; i >= 0; i--) fondo = mezclar(capas[i], fondo);
    return { fondo, degradado };
  };

  const visible = (el) => {
    const e = getComputedStyle(el);
    if (e.display === 'none' || e.visibility === 'hidden' || e.opacity === '0')
      return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  const resultados = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el)) continue;
    // Solo elementos con texto propio, no contenedores.
    const propio = Array.from(el.childNodes)
      .filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim())
      .join(' ')
      .trim();
    if (!propio) continue;

    const e = getComputedStyle(el);
    const frente = aRGB(e.color);
    if (!frente) continue;
    const { fondo, degradado } = fondoDe(el);
    const texto = mezclar(frente, fondo);

    const px = parseFloat(e.fontSize);
    const peso = parseInt(e.fontWeight) || 400;
    const grande = px >= 24 || (px >= 18.66 && peso >= 700);

    resultados.push({
      etiqueta: el.tagName.toLowerCase(),
      clase: (el.className || '').toString().slice(0, 40),
      texto: propio.slice(0, 45),
      px, peso, grande, degradado,
      color: e.color,
      fondo: `rgb(${Math.round(fondo.r)}, ${Math.round(fondo.g)}, ${Math.round(fondo.b)})`,
      razon: Math.round(razon(texto, fondo) * 100) / 100,
    });
  }
  return resultados;
}
"""

# Mide el fondo detras del logo, para saber si se pierde.
MEDIDOR_LOGO = r"""
(selector) => {
  const img = document.querySelector(selector);
  if (!img) return null;
  const aRGB = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x.trim()));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  let nodo = img;
  while (nodo) {
    const c = aRGB(getComputedStyle(nodo).backgroundColor);
    if (c && c.a === 1) {
      const lum = (0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b) / 255;
      return { fondo: `rgb(${c.r}, ${c.g}, ${c.b})`, luminancia: lum };
    }
    nodo = nodo.parentElement;
  }
  return { fondo: 'blanco (sin fondo propio)', luminancia: 1 };
}
"""


def medir(pagina, nombre):
    """Mide la pantalla y reporta lo que no llega al minimo."""
    resultados = pagina.evaluate(MEDIDOR)
    malos, dudosos = [], []
    for r in resultados:
        minimo = MINIMO_GRANDE if r["grande"] else MINIMO_NORMAL
        if r["razon"] < minimo:
            (dudosos if r["degradado"] else malos).append((r, minimo))

    revisar(
        f"{nombre}: todos los textos llegan al minimo",
        not malos,
        f"{len(malos)} por debajo",
    )
    for r, minimo in malos[:8]:
        print(f"           {r['razon']}:1 (minimo {minimo}) "
              f"<{r['etiqueta']} class=\"{r['clase']}\"> {r['px']:.0f}px")
        print(f"             texto: {r['texto']!r}")
        print(f"             color: {r['color']}  sobre {r['fondo']}")
    if len(malos) > 8:
        print(f"           ... y {len(malos) - 8} mas")

    for r, minimo in dudosos:
        avisos.append(
            f"{nombre}: <{r['etiqueta']} class=\"{r['clase']}\"> da "
            f"{r['razon']}:1 sobre un degradado; medido contra el color "
            "de base, conviene mirarlo a ojo"
        )
    return len(resultados)


def pantallas():
    """Las pantallas a revisar, sacadas de la propia aplicacion.

    Se enumeran del mapa de rutas y no de una lista escrita a mano:
    asi una pantalla nueva entra sola en la revision, que es cuando
    mas falta hace.
    """
    from app import crear_app

    sin_pantalla = {
        # Devuelven datos o archivos, no una pantalla.
        "cobrar.buscar_clientes",
        "facturas.exportar",
        "auth.login",
        "auth.logout",
    }
    rutas = []
    for regla in crear_app().url_map.iter_rules():
        ruta = str(regla)
        if (
            "GET" not in regla.methods
            or "<" in ruta
            or "static" in ruta
            or regla.endpoint in sin_pantalla
        ):
            continue
        rutas.append((ruta, regla.endpoint))
    return sorted(set(rutas))


def no_es_la_pantalla(pagina) -> str:
    """Devuelve por que la pantalla no sirve para medir, o cadena vacia."""
    if "/login" in pagina.url:
        return "pide ingresar de nuevo"
    if pagina.locator(".error-codigo").count():
        codigo = pagina.locator(".error-codigo").first.inner_text().strip()
        return f"muestra la pagina de error {codigo}"
    return ""


def entrar(pagina):
    pagina.goto(f"{BASE}/login")
    pagina.wait_for_load_state("networkidle")
    pagina.fill('input[name="usuario"]', USUARIO)
    pagina.fill('input[name="password"]', CLAVE)
    pagina.locator("form button[type=submit]").last.click()
    pagina.wait_for_load_state("networkidle")


def main():
    proceso = levantar()
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(args=["--no-sandbox"])
            pagina = navegador.new_page(viewport={"width": 1280, "height": 900})

            print("\nEL LOGO SOBRE SU FONDO")
            # El oso y la palabra TOTEM son blancos: sobre un fondo
            # claro el logo desaparece.
            pagina.goto(f"{BASE}/login")
            pagina.wait_for_load_state("networkidle")
            fondo = pagina.evaluate(MEDIDOR_LOGO, ".login-logo img")
            revisar(
                "login: el logo esta sobre un fondo oscuro",
                fondo is not None and fondo["luminancia"] < 0.5,
                f"fondo {fondo['fondo'] if fondo else 'sin logo'}, "
                f"luminancia {fondo['luminancia']:.2f} (hace falta < 0.50)"
                if fondo else "no encontre el logo",
            )

            print("\nPANTALLA DE INGRESO")
            medidos = medir(pagina, "login")

            entrar(pagina)

            fondo = pagina.evaluate(MEDIDOR_LOGO, ".brand-logo-img")
            revisar(
                "barra lateral: el logo esta sobre un fondo oscuro",
                fondo is not None and fondo["luminancia"] < 0.5,
                f"fondo {fondo['fondo'] if fondo else 'sin logo'}" if fondo
                else "no encontre el logo",
            )

            print("\nPANTALLAS DE ADENTRO")
            for ruta, nombre in pantallas():
                pagina.goto(f"{BASE}{ruta}")
                pagina.wait_for_load_state("networkidle")
                # Si la pantalla no es la que se pidio, medirla no
                # dice nada: una ruta equivocada mostraba la pagina de
                # error 404 y la prueba la daba por buena.
                problema = no_es_la_pantalla(pagina)
                if problema:
                    revisar(f"{nombre}: la pantalla abre", False,
                            f"{ruta} -> {problema}")
                    continue
                medidos += medir(pagina, nombre)

            print("\nEN EL TELEFONO")
            telefono = navegador.new_context(
                viewport={"width": 390, "height": 844}
            )
            movil = telefono.new_page()
            entrar(movil)
            movil.goto(f"{BASE}/clientes/")
            movil.wait_for_load_state("networkidle")
            medidos += medir(movil, "clientes en telefono")
            telefono.close()

            navegador.close()
    finally:
        if proceso is not None:
            proceso.terminate()
            try:
                proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proceso.kill()

    if avisos:
        print("\nPARA MIRAR A OJO")
        for aviso in avisos:
            print(f"  - {aviso}")

    print(f"\n{_contador[0]} comprobaciones, sobre {medidos} textos")
    if fallos:
        print(f"{len(fallos)} FALLAS: " + ", ".join(fallos))
        sys.exit(1)
    print("TODO OK")


if __name__ == "__main__":
    main()
