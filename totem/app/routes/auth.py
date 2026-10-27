"""Rutas de inicio y cierre de sesión."""

import time

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.security import cerrar_sesion, empleado_actual, iniciar_sesion
from app.services.auth_service import (
    AuthService,
    CredencialesInvalidas,
    EmpleadoInactivo,
)

bp = Blueprint("auth", __name__)

# Control de intentos fallidos por usuario. Al correr en una sola máquina
# con un proceso, guardarlo en memoria alcanza; si algún día se levantan
# varios procesos, esto debe moverse a la base o a Redis.
_intentos: dict[str, list[float]] = {}


def _esta_bloqueado(usuario: str) -> int:
    """Devuelve los segundos que faltan para poder reintentar, o 0."""
    ventana = current_app.config["BLOQUEO_LOGIN_SEGUNDOS"]
    maximo = current_app.config["MAX_INTENTOS_LOGIN"]
    ahora = time.time()

    recientes = [t for t in _intentos.get(usuario, []) if ahora - t < ventana]
    _intentos[usuario] = recientes

    if len(recientes) >= maximo:
        return int(ventana - (ahora - recientes[0]))
    return 0


def _anotar_fallo(usuario: str) -> None:
    _intentos.setdefault(usuario, []).append(time.time())


def _limpiar_intentos(usuario: str) -> None:
    _intentos.pop(usuario, None)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if empleado_actual() is not None:
        return redirect(url_for("main.panel"))

    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        password = request.form.get("password", "")

        if not usuario or not password:
            flash("Escribe tu usuario y contraseña.", "error")
            return render_template("login.html", usuario=usuario)

        faltan = _esta_bloqueado(usuario)
        if faltan:
            minutos = max(1, faltan // 60)
            flash(
                f"Demasiados intentos fallidos. Espera {minutos} minuto(s) "
                "antes de volver a intentar.",
                "error",
            )
            return render_template("login.html", usuario=usuario)

        try:
            empleado = AuthService().autenticar(usuario, password)
        except CredencialesInvalidas:
            _anotar_fallo(usuario)
            # Mismo mensaje para usuario inexistente y contraseña errada,
            # para no revelar qué usuarios existen.
            flash("Usuario o contraseña incorrectos.", "error")
            return render_template("login.html", usuario=usuario)
        except EmpleadoInactivo:
            flash(
                "Tu usuario está desactivado. Habla con el administrador.",
                "error",
            )
            return render_template("login.html", usuario=usuario)

        _limpiar_intentos(usuario)
        iniciar_sesion(empleado)
        return redirect(url_for("main.panel"))

    return render_template("login.html", usuario="")


@bp.route("/logout", methods=["POST"])
def logout():
    cerrar_sesion()
    return redirect(url_for("auth.login"))
