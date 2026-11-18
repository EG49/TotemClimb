"""Prueba de scripts/sri_emitir_factura.py.

Reproduce el caso real: una venta cobrada cuando el sistema todavia
no estaba configurado para emitir queda sin comprobante, porque el
numero se reserva en el momento del cobro y ese momento ya paso.
Despues se configura y hay que poder emitirla igual.

La configuracion se pone en el entorno ANTES de importar la app, y
no en app.config, porque el script crea su propia aplicacion. Es la
misma razon por la que hay que reiniciar el sistema despues de
editar el .env.

Todo lo que escribe queda deshecho al terminar.
"""
import sys, io, contextlib, os
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0, "/home/claude/totemclimb/totem")

# ANTES de importar la app: el script crea la suya y la configuracion
# sale del entorno, que config.py lee al importarse. Es exactamente
# lo que le pasa a quien edita el .env sin reiniciar.
PUNTO = "006"
P12 = Path("/tmp/prueba_emitir.p12")
from pruebas.ayudas_sri import CLAVE_P12, SriDeMentira, certificado_de_prueba
certificado_de_prueba(P12)
os.environ.update({
    "SRI_AMBIENTE": "1", "SRI_RUC": "1790012345001",
    "SRI_RAZON_SOCIAL": "TOTEM", "SRI_DIR_MATRIZ": "Av 123",
    "SRI_DIR_ESTABLECIMIENTO": "Av 123", "SRI_ESTABLECIMIENTO": "001",
    "SRI_PUNTO_EMISION": PUNTO, "SRI_P12_RUTA": str(P12),
    "SRI_P12_CLAVE": CLAVE_P12,
})

from app import crear_app
from app.db import obtener_cursor
from app.services import sri_service
from app.services.cobro_service import CobroService
fallas = []
def rev(e,c,d=""):
    print(("  OK     " if c else "  FALLA  ")+e+("" if c else f"  ({d})"))
    if not c: fallas.append(e)

app = crear_app()
with TemporaryDirectory() as carpeta, app.app_context():
    with obtener_cursor(commit=True) as c:
        c.execute("DELETE FROM sri_secuenciales WHERE punto_emision=%s",(PUNTO,))
        c.execute("INSERT INTO sri_secuenciales VALUES ('001',%s,'01',0)",(PUNTO,))
        c.execute("SELECT id_cliente FROM clientes WHERE cedula IS NOT NULL LIMIT 1")
        cli=c.fetchone()["id_cliente"]
        # Una membresia: al SRI van solo membresias y pases.
        c.execute("SELECT id_plan FROM planes_membresia WHERE activo LIMIT 1")
        plan=c.fetchone()["id_plan"]
        c.execute("SELECT id_empleado FROM empleados LIMIT 1")
        emp=c.fetchone()["id_empleado"]

    # Un cobro SIN el SRI configurado: queda sin comprobante, como los
    # que quedaron antes de llenar el .env.
    guardado = app.config["SRI_RUC"]
    app.config["SRI_RUC"] = None
    servicio = CobroService()
    idf,_ = servicio.cobrar({"id_cliente":str(cli),"metodo_pago":"EFECTIVO"},
                            [{"tipo":"plan","id_item":plan,"cantidad":1}], emp)
    with obtener_cursor() as c:
        c.execute("SELECT numero_factura, sri_estado FROM facturas WHERE id_factura=%s",(idf,))
        f=c.fetchone()
    rev("una factura cobrada sin SRI queda sin comprobante", f["sri_estado"] is None, str(f["sri_estado"]))
    numero = f["numero_factura"]

    # Ahora el sistema ya esta configurado, y se emite esa factura.
    app.config["SRI_RUC"] = guardado
    falso = SriDeMentira(); sri_service.ServicioSri._soap = staticmethod(falso)

    sys.argv = ["x", numero]
    from scripts import sri_emitir_factura
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        try: sri_emitir_factura.main()
        except SystemExit: pass
    texto = salida.getvalue()
    print(texto.strip()[:300])
    rev("el script la emite y queda AUTORIZADA", "AUTORIZADA" in texto, texto[-120:])

    with obtener_cursor() as c:
        c.execute("SELECT sri_estado, sri_secuencial, sri_autorizacion FROM facturas WHERE id_factura=%s",(idf,))
        f=c.fetchone()
    rev("la base lo refleja", f["sri_estado"]=="AUTORIZADA", str(f["sri_estado"]))
    rev("con su numero", f["sri_secuencial"]==1, str(f["sri_secuencial"]))

    # Y no la emite dos veces.
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        try: sri_emitir_factura.main()
        except SystemExit: pass
    rev("se niega a emitirla dos veces", "YA tiene comprobante" in salida.getvalue(),
        salida.getvalue()[-100:])

    with obtener_cursor(commit=True) as c:
        c.execute("DELETE FROM detalle_factura WHERE id_factura=%s",(idf,))
        c.execute("DELETE FROM membresias WHERE id_factura=%s",(idf,))
        c.execute("DELETE FROM facturas WHERE id_factura=%s",(idf,))
        c.execute("DELETE FROM sri_secuenciales WHERE punto_emision=%s",(PUNTO,))

print("TODO OK" if not fallas else f"{len(fallas)} FALLAS")
sys.exit(1 if fallas else 0)
