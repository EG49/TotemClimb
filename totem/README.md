# Totem Climb Gym — Sistema de membresías y facturación

Aplicación web local en Flask + PostgreSQL, organizada por capas.

## Puesta en marcha

### 1. Dependencias

```bash
python -m venv .venv
source .venv/bin/activate        # en Windows:  .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Base de datos

```bash
createdb totem
psql -d totem -f totem-schema-final.sql
```

### 3. Configuración

```bash
cp .env.example .env
```

Edita `.env` con los datos de tu PostgreSQL y genera una clave real:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Contraseña del administrador

El script SQL crea el usuario `admin` con un marcador que **no** permite
entrar. Hay que establecer la contraseña real:

```bash
python -m scripts.crear_admin
```

Para crear vendedores:

```bash
python -m scripts.crear_admin --usuario camila --rol VENDEDOR \
       --nombre Camila --apellido Rojas
```

Ese script solo hace falta la primera vez. Una vez que hay un
administrador con contraseña, el resto de los empleados se crean desde
la pantalla **Empleados**, sin tocar la terminal.

### 5. El logo

Copia `totem-logo.png` (el mismo de las maquetas) en:

```
app/static/img/totem-logo.png
```

### 6. Levantar la aplicación

```bash
python run.py          # desarrollo, en http://localhost:5000
```

En producción no se usa ese servidor:

```bash
gunicorn -w 3 -b 127.0.0.1:8000 "run:app"
```

## Estructura

```
totem/
├── run.py                  Punto de entrada
├── config.py               Configuración desde variables de entorno
├── app/
│   ├── __init__.py         Fábrica de la aplicación
│   ├── db.py               Pool de conexiones a PostgreSQL
│   ├── security.py         Sesión y control de acceso por rol
│   ├── models/             Objetos de dominio, sin lógica
│   ├── repositories/       Todo el SQL vive aquí
│   ├── services/           Reglas de negocio
│   ├── routes/             Blueprints de Flask (la interfaz)
│   ├── templates/          Plantillas Jinja2
│   └── static/             CSS, imágenes
└── scripts/                Utilidades de línea de comandos
```

La separación es la que define el proyecto: una vista nunca escribe SQL,
un repositorio nunca decide reglas de negocio, y un servicio no sabe que
existe HTTP. Para agregar un módulo se sigue siempre el mismo camino:
modelo, repositorio, servicio, ruta y plantilla.

## Roles

| | VENDEDOR | ADMIN |
|---|---|---|
| Trabajo diario (clientes, cobros, calendario) | Sí | Sí |
| Bitácora de movimientos | No | Sí |
| Cambiar el IVA | No | Sí |
| Crear y editar empleados | No | Sí |

El decorador `@login_requerido` protege las vistas normales y
`@admin_requerido` las del administrador.

## Seguridad

- Contraseñas con hash **bcrypt**; el texto plano no se guarda nunca.
- Mismo mensaje de error para usuario inexistente y contraseña errada,
  y verificación de igual duración en ambos casos, para no revelar qué
  usuarios existen.
- Bloqueo tras 5 intentos fallidos durante 5 minutos (configurable).
- Cookies de sesión `HttpOnly` y `SameSite=Lax`. Al pasar a HTTPS, hay
  que poner `SESSION_COOKIE_SECURE=True` en el `.env`.
- El hash nunca sale de la capa de servicios hacia las vistas.

El control de intentos fallidos vive en memoria del proceso. Si algún día
se levantan varios procesos de gunicorn, hay que moverlo a la base de
datos o a Redis.

## Módulo de clientes

Pantallas: listado con buscador y filtros, alta, edición y perfil del
menor a cargo.

Reglas implementadas:

- La cédula es opcional, pero si se registra se valida con el dígito
  verificador ecuatoriano y no puede repetirse.
- A un titular se le exige al menos un celular o un correo. A un menor no,
  porque se contacta a través de su representante.
- Los menores a cargo se crean como clientes ligados al representante, en
  la misma transacción: si falla uno, no queda el representante a medias.
- El estado de la membresía (vigente, por vencer, vencido) se calcula al
  vuelo desde la fecha de fin. "Por vencer" son los próximos 7 días.
- La edad y el aviso de mayoría de edad se calculan desde la fecha de
  nacimiento, sin guardar nada extra.
- Cada alta y cada edición quedan en la bitácora, con los valores de antes
  y después de cada campo que cambió.

Pendiente en este módulo: agendar la clase de prueba desde el alta del
cliente. Depende del módulo de Calendario, que todavía no existe.

## Módulo de catálogo (productos y planes)

Una sola pantalla con dos pestañas: **Catálogo** para los artículos que se
venden (nombre y precio) y **Planes de membresía** para los planes con
vigencia. El alta es un formulario único con un toggle Producto / Membresía.

Reglas implementadas:

- Los precios no pueden ser negativos y aceptan coma o punto decimal.
- Un plan tipo Pases debe indicar cuántas entradas incluye; los planes
  mensuales no guardan ese dato aunque se envíe.
- Los nombres no se repiten, sin importar mayúsculas.
- Nada se borra: lo que deja de venderse se desactiva. Desaparece de la
  lista al cobrar, pero las facturas anteriores siguen intactas. Por eso
  este módulo agrega la columna `productos.activo`.

## Módulo de cobro

Pantalla de Cobrar con buscador de cliente, lista única de productos y
planes, totales en vivo y comprobante al final.

Reglas implementadas:

- **Los totales se recalculan siempre en el servidor** con los precios de
  la base. Lo que manda el navegador solo dice qué ítems y en qué
  cantidad; un precio enviado desde el cliente se ignora.
- Si cualquier ítem tiene `permite_descuento = false`, el descuento se
  bloquea para la factura completa.
- Un plan con `permite_pareja` pide una segunda persona y genera dos
  membresías enlazadas entre sí, desde una sola factura y un solo cobro.
- **Renovación anticipada:** si el cliente todavía tiene vigencia, la
  nueva membresía empieza el día en que termina la anterior, para que no
  pierda los días que ya pagó.
- Los pases copian sus entradas del plan a `dias_totales` y
  `dias_restantes`.
- Fiar deja la factura en `PENDIENTE` con su saldo; el monto recibido al
  momento se guarda como el primer abono en `pagos_fiado`.
- El IVA se lee de `configuracion` y se guarda en cada factura, así un
  cambio futuro no altera las facturas anteriores.
- Todo el cobro ocurre en una sola transacción: factura, detalle,
  membresías y abono, o nada.

La numeración usa la secuencia `seq_numero_factura`, para que dos cobros
simultáneos nunca reciban el mismo número.

## Módulo de facturas

Historial con filtros combinables (cliente o número, rango de fechas,
estado, tipo y método), dos vistas (por factura y agrupado por cliente),
tarjetas de resumen del período y exportación a CSV.

Reglas implementadas:

- **Una factura nunca se borra.** Se anula con un motivo obligatorio y
  queda en el historial marcada como anulada.
- **Anular cancela las membresías que la factura generó** y refresca la
  vigencia de los clientes afectados: si la venta no valió, la vigencia
  tampoco.
- Un abono baja el saldo de una factura fiada. Cuando llega a cero, pasa
  de `PENDIENTE` a `EMITIDA` y recién ahí cuenta como ingreso.
- No se puede abonar de más, ni abonar a una factura pagada o anulada,
  ni anular dos veces.
- El resumen no suma las anuladas, y el saldo fiado se muestra aparte,
  porque todavía no es ingreso.
- El CSV sale con BOM para que Excel respete las tildes al abrirlo.

Este módulo no necesita cambios en la base de datos.

## Módulo de contabilidad

Reporte agregado del período, distinto de Facturas, que lista
transacción por transacción.

- Período Día, Mes o Personalizado, con filtro opcional por cliente.
- Desgloses con barras por método de pago, categoría y vendedor, más lo
  más vendido y la serie día a día.
- Un botón oculta todos los montos de la pantalla a la vez, para
  consultarla sin que alguien lea por encima del hombro.
- **Solo las facturas EMITIDA cuentan como ingreso.** Las anuladas no
  valen y las fiadas todavía no se cobraron; ambas se muestran aparte.

## Módulo de calendario

Vistas Semana, Mes y Año, con panel del día seleccionado.

- **Los cumpleaños no se guardan:** se calculan desde la fecha de
  nacimiento de cada cliente cada vez que se pinta el calendario.
- Salen los cumpleaños de los **clientes activos** y los de los
  **empleados activos**, con colores distintos: turquesa para los
  clientes, verde lima para el equipo.
- De los clientes solo aparecen los **activos**: con membresía vigente o
  vencida hace menos de 30 días. Sin ese filtro el calendario se llena
  de gente que dejó de venir hace meses. El plazo se cambia en
  `DIAS_GRACIA_CUMPLE`, en `app/repositories/evento_repo.py`; ponerlo en
  0 deja solo a los que tienen vigencia hoy.
- Un evento no puede terminar antes de empezar. "Todo el día" se guarda
  de 00:00 a 23:59 y se indica en el título.
- **El cupo se valida dentro de la transacción**, bloqueando la fila del
  evento, para que dos inscripciones simultáneas no lo pasen.
- Un cliente no se inscribe dos veces al mismo evento.
- La **agenda por cliente** muestra qué tiene agendado cada uno, con
  quién lo inscribió y cuándo.

## Clase de prueba desde el alta

Al registrar un cliente se le puede agendar una clase de prueba: unirse
a una ya creada o reservar un horario nuevo. Ocurre en la misma
transacción que el alta, así que si la clase se llenó mientras llenaban
el formulario, no queda ni el cliente ni la inscripción a medias.

## Panel general

- Accesos rápidos a Cobrar y Nuevo cliente.
- Estadísticas, con el ingreso del día oculto por defecto tras un ícono
  de ojo.
- **Panel de Avisos** con los tres asuntos que requieren atención:
  membresías vencidas o por vencer, menores que cumplieron 18 y siguen
  con representante, y facturas fiadas sin saldar. Se filtran por tipo y
  cada uno lleva su acción directa.
- Calendario del mes y los próximos eventos.

## Módulo de empleados

Pantalla solo para el ADMIN. Es donde se da de alta a quien va a usar el
sistema y donde se le quita el acceso cuando deja de trabajar.

- **Un empleado nunca se borra.** Su `id_empleado` está referenciado por
  las facturas, los abonos, las inscripciones y la bitácora: borrarlo
  dejaría el historial sin decir quién hizo cada cosa. Lo que se hace es
  desactivarlo: deja de poder entrar y su rastro se conserva.
- **Nadie puede desactivarse a sí mismo** ni quitarse el rol de
  administrador: se quedaría fuera en mitad de la sesión.
- **Siempre tiene que quedar un administrador activo.** El sistema no
  deja desactivar ni degradar al último que queda.
- La contraseña se guarda cifrada con bcrypt. Ni el administrador puede
  verla después, solo reemplazarla.
- La fecha de nacimiento es opcional y solo sirve para que el cumpleaños
  salga en el calendario.
- Cada ficha muestra la **actividad** del empleado: cuántas facturas
  emitió, cuánto facturó, cuántos abonos recibió y cuándo fue su última
  acción.
- Altas, ediciones, cambios de contraseña y cambios de estado quedan en
  la bitácora.

## Configuración

Pantalla solo para el ADMIN donde se cambia el IVA. El valor anterior y
el nuevo quedan en la bitácora. Las facturas ya emitidas conservan la
tasa con la que se cobraron.

## Estado del proyecto

Todos los módulos planificados están construidos. Lo que queda abierto
no depende del código:

- **Un empleado por persona, no por turno:** si más adelante hacen falta
  horarios o asistencia del personal, eso es una tabla aparte; la de
  empleados es solo de acceso al sistema.

- **Integración con el biométrico:** falta confirmar el modelo exacto del
  dispositivo para elegir la librería (pyzk o ISAPI de Hikvision).
- **Facturación electrónica del SRI:** fuera de alcance por decisión de
  presupuesto; los comprobantes son recibos internos.
