"""Punto de entrada para desarrollo.

En producción NO se usa este servidor: se levanta con gunicorn, por
ejemplo:  gunicorn -w 3 -b 127.0.0.1:8000 "run:app"
"""

from app import crear_app

app = crear_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
