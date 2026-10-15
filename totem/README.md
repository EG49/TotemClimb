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

## Lo que sigue

Módulos pendientes, en el orden sugerido: clientes, productos y planes,
cobrar, facturas, contabilidad y calendario. Las maquetas HTML de cada uno
ya están hechas y sirven de referencia visual.
