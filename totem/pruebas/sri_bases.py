"""Pruebas del reparto de la base imponible entre las lineas.

El descuadre de un centavo entre la suma de los detalles y el
total de la factura es motivo de rechazo del SRI, y no aparece en
el caso simple: hay que buscarlo en combinaciones de precios. Por
eso se prueban 30000 facturas al azar del catalogo real.
"""

import sys, random, itertools
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.sri import bases as b

C = Decimal("0.01")
IVA = Decimal("15")
fallas = []
def rev(e, c, d=""):
    print(("  OK     " if c else "  FALLA  ")+e+("" if c else f"  ({d})"))
    if not c: fallas.append(e)

print("\nEL CASO QUE MOTIVA EL MODULO: tres pases de $10")
total = Decimal("30.00")
base = b.base_del_total(total, IVA)
partes = b.repartir(base, [Decimal("10.00")]*3)
rev("la base de la factura es 26.09", base == Decimal("26.09"), str(base))
rev("las lineas suman exactamente la base", sum(partes) == base, f"{sum(partes)} vs {base}")
rev("una linea se lleva el centavo", sorted(partes) == [Decimal("8.69"), Decimal("8.70"), Decimal("8.70")], str(partes))
rev("base + IVA da el total", base + (total-base) == total)

print("\nCATALOGO REAL DEL GIMNASIO")
catalogo = {"Membresia Senior": Decimal("65.00"), "Junior": Decimal("65.00"),
            "Senior 3 meses": Decimal("145.00"), "Duo": Decimal("111.00"),
            "Pase del dia": Decimal("10.00"), "5 pases": Decimal("30.00"),
            "10 pases": Decimal("49.00"), "Agua Cielo": Decimal("0.50"),
            "Sporade": Decimal("0.75"), "Magnesio": Decimal("5.00")}
for n, p in catalogo.items():
    bb = b.base_del_total(p, IVA)
    rev(f"{n} ${p}: base {bb} + IVA {p-bb} = {p}", bb + (p-bb) == p)

print("\nAL AZAR: 30000 facturas")
random.seed(11)
precios = list(catalogo.values())
malas = 0
for _ in range(30000):
    lineas = [random.choice(precios)*random.randint(1,4) for _ in range(random.randint(1,8))]
    t = sum(lineas)
    bf = b.base_del_total(t, IVA)
    pr = b.repartir(bf, lineas)
    if sum(pr) != bf or bf + (t-bf) != t or any(x < 0 for x in pr):
        malas += 1
rev("todas cuadran linea por linea y contra el total", malas == 0, f"{malas} descuadres")

print("\nBORDES")
rev("factura de una sola linea", b.repartir(Decimal("8.70"), [Decimal("10.00")]) == [Decimal("8.70")])
rev("sin lineas y base cero", b.repartir(Decimal("0"), []) == [])
rev("todo en cero (cortesia)", b.repartir(Decimal("0.00"), [Decimal("0"), Decimal("0")]) == [Decimal("0.00")]*2)
rev("un centavo entre dos lineas", sum(b.repartir(Decimal("0.01"), [Decimal("0.50"), Decimal("0.50")])) == Decimal("0.01"))
try:
    b.repartir(Decimal("10"), [Decimal("-1"), Decimal("5")]); rev("rechaza importe negativo", False, "no levanto")
except b.ErrorReparto: rev("rechaza importe negativo", True)
try:
    b.repartir(Decimal("10"), []); rev("rechaza base sin lineas", False, "no levanto")
except b.ErrorReparto: rev("rechaza base sin lineas", True)

print("\nDETERMINISMO")
a1 = b.repartir(Decimal("26.09"), [Decimal("10"), Decimal("10"), Decimal("10")])
a2 = b.repartir(Decimal("26.09"), [Decimal("10"), Decimal("10"), Decimal("10")])
rev("el mismo reparto dos veces da lo mismo", a1 == a2)
rev("el centavo va a la primera de peso igual", a1[0] == Decimal("8.70") and a1[2] == Decimal("8.69"), str(a1))
desigual = b.repartir(b.base_del_total(Decimal("75.50"), IVA), [Decimal("65.00"), Decimal("10.00"), Decimal("0.50")])
rev("con pesos distintos el residuo va al mayor", desigual[0] >= desigual[1] >= desigual[2], str(desigual))

print(f"\n{21+len(catalogo)} comprobaciones")
print("TODO OK" if not fallas else f"{len(fallas)} FALLAS: "+", ".join(fallas))
sys.exit(1 if fallas else 0)
