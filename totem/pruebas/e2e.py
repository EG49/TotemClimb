"""Pruebas de punta a punta con un navegador real.

Las otras pruebas del proyecto llaman a los servicios o al cliente de
pruebas de Flask. Eso verifica la logica, pero no que la pantalla
funcione: un boton mal cableado, un formulario que no envia un campo
o un script roto pasan desapercibidos.

Estas manejan Chromium de verdad: escriben en los campos, hacen clic
y leen lo que queda en pantalla. Cubren los recorridos que de
romperse costarian dinero -cobrar, registrar un gasto, agendar- y el
comportamiento en telefono.

    python -m pruebas.e2e

Requisitos:

    pip install playwright
    python -m playwright install chromium

La aplicacion se levanta sola en un puerto aparte y se apaga al
terminar. Usa la base del .env, asi que apuntalo a una base de
desarrollo: las pruebas escriben.
"""

import os
import re
import signal
import socket
import subprocess
import sys
import time
from datetime import date

from playwright.sync_api import sync_playwright

PUERTO = int(os.environ.get("PUERTO_E2E", "5099"))
BASE = f"http://127.0.0.1:{PUERTO}"
USUARIO = os.environ.get("E2E_USUARIO", "admin")
CLAVE = os.environ.get("E2E_CLAVE", "Prueba12345")

ANCHO_TELEFONO = {"width": 390, "height": 844}

fallos = []
_contador = [0]


def revisar(etiqueta, condicion, detalle=""):
    _contador[0] += 1
    print(("  OK   " if condicion else "  FALLA") + "  " + etiqueta
          + (f"  -> {detalle}" if detalle and not condicion else ""))
    if not condicion:
        fallos.append(etiqueta)


def seccion(titulo):
    print(f"\n{titulo}")


# ---------------------------------------------------------------
#  Servidor
# ---------------------------------------------------------------

def puerto_libre(puerto):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", puerto)) != 0


def levantar():
    if not puerto_libre(PUERTO):
        print(f"El puerto {PUERTO} ya esta ocupado. Se usa lo que haya ahi.")
        return None
    proc = subprocess.Popen(
        [sys.executable, "-m", "flask", "--app", "run:app", "run", "--port", str(PUERTO)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    for _ in range(50):
        if not puerto_libre(PUERTO):
            return proc
        if proc.poll() is not None:
            print("La aplicacion no arranco:")
            print(proc.stderr.read().decode("utf-8", "replace")[-1500:])
            sys.exit(1)
        time.sleep(0.3)
    print("La aplicacion no respondio a tiempo.")
    sys.exit(1)


def apagar(proc):
    if proc is None:
        return
    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    proc.wait(timeout=10)


# ---------------------------------------------------------------
#  Ayudas
# ---------------------------------------------------------------

def entrar(pagina, usuario=USUARIO, clave=CLAVE):
    """Inicia sesion. Si ya habia una abierta, no hace nada.

    La sesion vive en el contexto del navegador, asi que una segunda
    llamada encuentra /login redirigido al panel y sin formulario.
    """
    pagina.goto(f"{BASE}/login")
    pagina.wait_for_load_state("networkidle")
    if pagina.locator('input[name="usuario"]').count() == 0:
        return
    pagina.fill('input[name="usuario"]', usuario)
    pagina.fill('input[name="password"]', clave)
    pagina.locator("form button[type=submit]").last.click()
    pagina.wait_for_load_state("networkidle")


def salir(pagina):
    pagina.goto(f"{BASE}/logout")
    pagina.wait_for_load_state("networkidle")


def enviar(pagina, etiqueta):
    """Pulsa el boton de envio del formulario, por su texto.

    Nunca "el primer button[type=submit]": el de la barra lateral es
    "Cerrar sesion" y va antes en el documento, asi que un selector
    por posicion cierra la sesion en lugar de guardar.
    """
    pagina.locator(f"button[type=submit]:has-text('{etiqueta}')").first.click()
    pagina.wait_for_load_state("networkidle")


def texto(pagina):
    return pagina.inner_text("body")


def gasto_del_balance(pagina):
    """El total de gastos del balance, leido de su tarjeta.

    No se busca por expresion regular sobre toda la pagina: el rotulo
    y la cifra estan en lineas distintas, y la palabra "gastos"
    aparece media docena de veces en esa pantalla.
    """
    tarjeta = pagina.locator(".summary-card", has_text="Gastos").first
    valor = tarjeta.locator(".summary-value").first.inner_text()
    try:
        return float(valor.replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def sufijo():
    return str(int(time.time() * 1000))[-7:]


# ---------------------------------------------------------------
#  Recorridos
# ---------------------------------------------------------------

def probar_acceso(navegador):
    seccion("ACCESO")
    # Contexto propio: el intento fallido suma al bloqueo por
    # intentos, y no tiene por que afectar al resto.
    ctx = navegador.new_context(viewport={"width": 1280, "height": 900})
    pagina = ctx.new_page()

    entrar(pagina, clave="claveQueNoEs")
    revisar("una clave equivocada no deja entrar",
            "/login" in pagina.url, pagina.url)
    revisar("y lo dice en pantalla",
            re.search(r"incorrect|no.*v[áa]lid|error", texto(pagina), re.I) is not None)

    entrar(pagina)
    pagina.wait_for_load_state("networkidle")
    revisar("la clave correcta entra al panel",
            pagina.url.rstrip("/") == BASE, pagina.url)
    revisar("el panel saluda", "Hola," in texto(pagina))

    ctx.close()


def probar_cobro(ctx):
    """El recorrido que de romperse cuesta dinero."""
    seccion("COBRAR UNA MEMBRESIA")
    pagina = ctx.new_page()
    entrar(pagina)

    marca = sufijo()
    nombre = f"Prueba{marca}"

    # --- alta de cliente ---
    pagina.goto(f"{BASE}/clientes/nuevo")
    pagina.fill('input[name="nombre"]', nombre)
    pagina.fill('input[name="apellido"]', "E2E")
    pagina.fill('input[name="telefono"]', "0991112223")
    enviar(pagina, "Guardar")
    revisar("se crea el cliente", "class=\"error\"" not in pagina.content(),
            " | ".join(pagina.locator(".error").all_inner_texts())[:120])

    # --- cobro ---
    pagina.goto(f"{BASE}/cobrar/")
    pagina.wait_for_selector("#buscar-cliente", timeout=15000)
    pagina.fill("#buscar-cliente", nombre)
    pagina.wait_for_selector(".picker-opt[data-id]", timeout=8000)
    pagina.locator(".picker-opt[data-id]").first.click()

    # Se elige la Membresia Senior, que vale 65 con IVA incluido.
    valor = pagina.evaluate(
        "() => [...document.querySelectorAll('#sel-item option')]"
        ".filter(o => o.textContent.includes('Membresía Senior'))"
        ".map(o => o.value)[0]")
    revisar("la Membresia Senior esta en el catalogo", bool(valor), str(valor))
    pagina.select_option("#sel-item", valor)
    pagina.click("button:has-text('Agregar')")
    pagina.wait_for_timeout(400)

    # Lo que ve quien cobra. Es la cifra que le pide al cliente, asi
    # que tiene que ser exactamente la que se factura.
    previo_total = pagina.text_content("#t-total").strip()
    previo_base = pagina.text_content("#t-base").strip()
    previo_iva = pagina.text_content("#t-iva").strip()

    revisar("el total en pantalla es el precio de lista",
            previo_total == "$65.00", previo_total)
    revisar("NO se suma el IVA encima (no debe decir $74.75)",
            previo_total != "$74.75", previo_total)
    revisar("muestra la base imponible", previo_base == "$56.52", previo_base)
    revisar("y el IVA extraido", previo_iva == "$8.48", previo_iva)
    revisar("base + IVA = total en pantalla",
            round(float(previo_base[1:]) + float(previo_iva[1:]), 2)
            == float(previo_total[1:]),
            f"{previo_base} + {previo_iva} != {previo_total}")

    pagina.click("#btn-cobrar")
    pagina.wait_for_load_state("networkidle")
    revisar("la factura se emite", "/cobrar/comprobante/" in pagina.url, pagina.url)

    comprobante = texto(pagina)
    revisar("el comprobante nombra al cliente", nombre in comprobante)

    # LA COMPROBACION QUE IMPORTA: la pantalla de cobro y la factura
    # tienen que decir lo mismo. Si no, quien cobra pide una cifra y
    # el sistema registra otra.
    m = re.search(r"Total\s*\$?([\d.,]+)", comprobante)
    facturado = m.group(1) if m else None
    revisar("lo facturado es lo que mostraba la pantalla",
            facturado is not None
            and abs(float(facturado.replace(",", "")) - float(previo_total[1:])) < 0.005,
            f"pantalla {previo_total} vs factura {facturado}")

    # --- queda reflejado ---
    pagina.goto(f"{BASE}/clientes/?q={nombre}")
    pagina.wait_for_load_state("networkidle")
    lista = texto(pagina)
    revisar("el cliente aparece con su membresia", nombre in lista)
    revisar("y queda vigente", re.search(r"vigente", lista, re.I) is not None)

    pagina.close()
    return nombre


def probar_gasto_y_balance(ctx):
    seccion("GASTO Y BALANCE")
    pagina = ctx.new_page()
    entrar(pagina)

    concepto = f"PruebaE2E{sufijo()}"

    pagina.goto(f"{BASE}/contabilidad/balance")
    pagina.wait_for_load_state("networkidle")
    gasto_antes = gasto_del_balance(pagina)

    pagina.goto(f"{BASE}/gastos/nuevo")
    pagina.fill('input[name="concepto"]', concepto)
    pagina.fill('input[name="monto"]', "123.45")
    pagina.fill('input[name="fecha"]', date.today().isoformat())
    pagina.select_option('select[name="segmento"]', "GENERAL")
    pagina.check('input[name="facturado"]')
    enviar(pagina, "Registrar gasto")
    revisar("se registra el gasto", concepto in texto(pagina),
            "no aparece en la lista")

    pagina.goto(f"{BASE}/contabilidad/balance")
    pagina.wait_for_load_state("networkidle")
    gasto_despues = gasto_del_balance(pagina)

    revisar("el balance recoge el gasto",
            gasto_antes is not None and gasto_despues is not None
            and abs((gasto_despues - gasto_antes) - 123.45) < 0.02,
            f"antes={gasto_antes} despues={gasto_despues}")

    # Anular lo devuelve a donde estaba: un gasto anulado no resta.
    pagina.goto(f"{BASE}/gastos/?q={concepto}")
    pagina.wait_for_load_state("networkidle")
    pagina.locator("button", has_text="Anular").first.click()
    pagina.fill("#motivo", "Gasto de prueba automatica")
    pagina.locator("#form-anular button[type='submit']").click()
    pagina.wait_for_load_state("networkidle")

    pagina.goto(f"{BASE}/contabilidad/balance")
    pagina.wait_for_load_state("networkidle")
    gasto_final = gasto_del_balance(pagina)
    revisar("un gasto anulado deja de restar",
            gasto_final is not None and abs(gasto_final - gasto_antes) < 0.02,
            f"esperaba {gasto_antes}, dio {gasto_final}")

    pagina.close()


def probar_permisos(navegador, usuario_vendedor, clave_vendedor):
    seccion("PERMISOS DEL VENDEDOR")
    # Contexto limpio: con la sesion del admin heredada, estas
    # comprobaciones pasarian sin probar nada.
    ctx = navegador.new_context(viewport={"width": 1280, "height": 900})
    pagina = ctx.new_page()
    entrar(pagina, usuario_vendedor, clave_vendedor)
    pagina.wait_for_load_state("networkidle")
    revisar("el vendedor entra", "Hola," in texto(pagina), pagina.url)

    for ruta, nombre in [("/gastos/", "Gastos"),
                         ("/contabilidad/balance", "Balance"),
                         ("/empleados/", "Empleados"),
                         ("/configuracion", "Configuracion")]:
        pagina.goto(BASE + ruta)
        pagina.wait_for_load_state("networkidle")
        revisar(f"no entra a {nombre}", ruta.rstrip("/") not in pagina.url
                or "no tiene permiso" in texto(pagina).lower(), pagina.url)

    pagina.goto(BASE + "/")
    pagina.wait_for_load_state("networkidle")
    enlaces = pagina.locator("nav a, .sidebar a").all_inner_texts()
    revisar("no se le ofrece el enlace de Gastos",
            not any("Gasto" in t for t in enlaces), str(enlaces))
    ctx.close()


def probar_telefono(navegador):
    """Lo del punto 14: en un telefono no se desliza de lado."""
    seccion("EN TELEFONO")
    ctx = navegador.new_context(viewport=ANCHO_TELEFONO, has_touch=True,
                                is_mobile=True)
    pagina = ctx.new_page()
    entrar(pagina)

    for ruta in ["/", "/clientes/", "/facturas/", "/gastos/", "/posibles/",
                 "/contabilidad/", "/contabilidad/balance", "/calendario/"]:
        pagina.goto(BASE + ruta)
        pagina.wait_for_load_state("networkidle")
        desborde = pagina.evaluate(
            "() => document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth")
        revisar(f"{ruta} no obliga a deslizar de lado", desborde <= 1,
                f"se desborda {desborde}px")

    # La tabla de clientes: tarjetas desplegables.
    pagina.goto(f"{BASE}/clientes/")
    pagina.wait_for_load_state("networkidle")

    filas = pagina.locator("tr.fila-desplegable")
    revisar("las filas se vuelven desplegables", filas.count() > 0,
            f"{filas.count()} filas")

    primera = filas.first
    oculto = primera.locator(".celda-detalle").first
    revisar("el detalle arranca oculto", not oculto.is_visible())

    # El estado tiene que verse SIN desplegar: es lo primero que se mira.
    insignia = primera.locator(".celda-insignia")
    if insignia.count():
        revisar("el estado se ve sin desplegar", insignia.first.is_visible())

    primera.click()
    pagina.wait_for_timeout(300)
    revisar("al tocar la fila se despliega", oculto.is_visible())
    revisar("y queda marcada como abierta",
            primera.get_attribute("aria-expanded") == "true")

    detalle = oculto.inner_text()
    revisar("el detalle trae su rotulo", len(detalle.strip()) > 0, repr(detalle))

    primera.click()
    pagina.wait_for_timeout(300)
    revisar("al tocarla otra vez se cierra", not oculto.is_visible())

    # Un boton dentro de la fila tiene que funcionar, no desplegar.
    # Se busca uno habilitado: "Renovar" aparece deshabilitado cuando
    # el cliente no tiene nada que renovar.
    boton = primera.locator("a[href], button:not([disabled])").first
    if boton.count():
        antes = pagina.url
        boton.click()
        pagina.wait_for_load_state("networkidle")
        revisar("un boton de la fila navega en vez de desplegar",
                pagina.url != antes, pagina.url)

    # El menu lateral se abre con el boton.
    pagina.goto(f"{BASE}/")
    pagina.wait_for_load_state("networkidle")
    barra = pagina.locator(".sidebar")
    revisar("la barra lateral arranca fuera de la vista",
            barra.evaluate("e => e.getBoundingClientRect().left") < -50,
            str(barra.evaluate("e => e.getBoundingClientRect().left")))
    pagina.locator(".btn-menu").first.click()
    pagina.wait_for_timeout(400)
    revisar("el boton del menu la abre",
            barra.evaluate("e => e.getBoundingClientRect().left") > -10)

    ctx.close()


def probar_escritorio_intacto(navegador):
    """Lo de arriba no debe haber cambiado nada en pantalla ancha."""
    seccion("EN ESCRITORIO NO CAMBIA NADA")
    ctx = navegador.new_context(viewport={"width": 1280, "height": 900})
    pagina = ctx.new_page()
    entrar(pagina)

    pagina.goto(f"{BASE}/clientes/")
    pagina.wait_for_load_state("networkidle")
    revisar("la cabecera de la tabla se ve",
            pagina.locator("thead th").first.is_visible())
    revisar("las columnas de detalle se ven",
            pagina.locator(".celda-detalle").first.is_visible())
    revisar("no hay flechas de desplegar a la vista",
            not pagina.locator(".flecha-fila").first.is_visible())

    fila = pagina.locator("tr.fila-desplegable").first
    fila.click(position={"x": 300, "y": 10})
    pagina.wait_for_timeout(200)
    revisar("un clic en la fila no la despliega",
            "abierta" not in (fila.get_attribute("class") or ""))
    ctx.close()


# ---------------------------------------------------------------

def main():
    proc = levantar()
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(args=["--no-sandbox"])
            ctx = navegador.new_context(viewport={"width": 1280, "height": 900})

            probar_acceso(navegador)
            probar_cobro(ctx)
            probar_gasto_y_balance(ctx)

            vendedor = os.environ.get("E2E_VENDEDOR")
            if vendedor:
                probar_permisos(navegador, vendedor, os.environ.get("E2E_VENDEDOR_CLAVE", CLAVE))
            else:
                print("\nPERMISOS: se omite (define E2E_VENDEDOR para probarlos)")

            ctx.close()
            probar_telefono(navegador)
            probar_escritorio_intacto(navegador)
            navegador.close()
    finally:
        apagar(proc)

    print()
    print(f"{_contador[0]} comprobaciones")
    print("TODO OK" if not fallos else f"{len(fallos)} FALLAS: " + ", ".join(fallos))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
