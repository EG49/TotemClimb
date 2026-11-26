"""El sistema no arranca sin una SECRET_KEY propia.

Esa clave firma la cookie de sesion. La cookie dice "empleado 1, rol
ADMIN" y va firmada, no cifrada: cualquiera puede leerla, pero sin la
clave no puede fabricar una. Con la clave, si: se escribe el rol que
se quiera, se firma correctamente, y el servidor la acepta. No hace
falta ninguna contrasena.

Por eso la verificacion corta el arranque. Un sistema andando con una
clave conocida se ve exactamente igual que uno seguro -- no hay nada
que mirar, ningun error, ninguna pantalla rara. Si no corta al
arrancar, no se entera nadie nunca.

Lo que mas importa probar es que rechace lo que PARECE una clave:
la de desarrollo que estuvo escrita en el repositorio, la de
.env.example que se copia tal cual, y las cortas. Una clave vacia la
nota cualquiera; las otras tres son las que de verdad terminan en
produccion.
"""

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from config import (  # noqa: E402
    CLAVES_QUEMADAS, LARGO_MINIMO, revisar_secret_key,
)

fallas = []


def revisar(etiqueta, condicion, detalle=""):
    print(("  OK     " if condicion else "  FALLA  ") + etiqueta
          + ("" if condicion else f"  ({detalle})"))
    if not condicion:
        fallas.append(etiqueta)


print("\nSE RECHAZA LO QUE NO PROTEGE NADA")

revisar("sin definir", revisar_secret_key(None) is not None)
revisar("vacia", revisar_secret_key("") is not None)
revisar("solo espacios", revisar_secret_key("      ") is not None)

# Estas tres son las peligrosas: funcionan, el sistema arranca, y
# quien haya visto el repositorio entra como administrador.
revisar("la clave de desarrollo que estaba en config.py",
        revisar_secret_key("clave-solo-para-desarrollo") is not None)
revisar("la de .env.example copiada tal cual",
        revisar_secret_key("cambia-esto-por-una-clave-larga-y-aleatoria")
        is not None)
for quemada in CLAVES_QUEMADAS:
    revisar(f"«{quemada}»", revisar_secret_key(quemada) is not None)

revisar("sin importar mayusculas",
        revisar_secret_key("Clave-Solo-Para-Desarrollo") is not None,
        "cambiar una mayuscula no la vuelve secreta")
revisar("ni espacios alrededor",
        revisar_secret_key("  clave-solo-para-desarrollo  ") is not None)

print("\nY LAS DEMASIADO CORTAS")
revisar("una palabra", revisar_secret_key("gimnasio") is not None)
revisar(f"justo por debajo del minimo ({LARGO_MINIMO - 1})",
        revisar_secret_key("a" * (LARGO_MINIMO - 1)) is not None)

print("\nSE ACEPTA UNA CLAVE DE VERDAD")
generada = secrets.token_hex(32)
revisar("la que genera el comando que damos",
        revisar_secret_key(generada) is None, revisar_secret_key(generada))
revisar("justo en el minimo", revisar_secret_key("b" * LARGO_MINIMO) is None)
revisar("una larga con simbolos",
        revisar_secret_key("x9!Kd2#mQ7$pL4@wZ8&nR5*tY3^vB6%cF1") is None)

print("\nEL MENSAJE DICE QUE HACER")
# Un error que no dice como arreglarlo obliga a leer el codigo.
for caso, nombre in [(None, "sin definir"),
                     ("clave-solo-para-desarrollo", "clave de ejemplo"),
                     ("corta", "muy corta")]:
    problema = revisar_secret_key(caso)
    revisar(f"explica el problema cuando esta {nombre}",
            bool(problema) and len(problema) > 10, problema)

texto = config.EXPLICACION_SECRET_KEY
revisar("trae el comando para generarla", "secrets.token_hex(32)" in texto)
revisar("dice donde ponerla", ".env" in texto)
revisar("avisa que es una por maquina",
        "gimnasio" in texto and "distinta" in texto)
revisar("y que cambiarla no pierde datos", "No se pierde" in texto)

print("\nLA APLICACION NO ARRANCA SIN ELLA")
# La prueba de verdad: que crear_app() se niegue, no solo que la
# funcion devuelva un texto.
from app import SecretKeyInvalida, crear_app  # noqa: E402

anterior = config.Config.SECRET_KEY
try:
    for valor, nombre in [(None, "sin clave"),
                          ("clave-solo-para-desarrollo", "con la de ejemplo"),
                          ("corta", "con una corta")]:
        config.Config.SECRET_KEY = valor
        try:
            crear_app()
            revisar(f"se niega a arrancar {nombre}", False,
                    "ARRANCO -- las sesiones serian falsificables")
        except SecretKeyInvalida:
            revisar(f"se niega a arrancar {nombre}", True)
        except Exception as error:  # noqa: BLE001
            revisar(f"se niega a arrancar {nombre}", False,
                    f"fallo con otro error: {type(error).__name__}")
finally:
    config.Config.SECRET_KEY = anterior

print("\nY NO QUEDA NINGUNA CLAVE ESCRITA EN EL CODIGO")
# Lo que originalmente estaba mal: un valor por defecto que funciona.
fuente = (Path(__file__).resolve().parent.parent / "config.py").read_text(
    encoding="utf-8"
)
linea = [l for l in fuente.splitlines() if "SECRET_KEY = os.getenv" in l]
revisar("config.py lee SECRET_KEY sin valor por defecto",
        bool(linea) and "," not in linea[0].split("os.getenv")[1],
        linea[0].strip() if linea else "no se encontro la linea")

print(f"\n{'TODO OK' if not fallas else str(len(fallas)) + ' FALLAS: ' + ', '.join(fallas)}")
sys.exit(1 if fallas else 0)
