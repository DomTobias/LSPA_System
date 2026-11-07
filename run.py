"""Ponto de entrada da aplicação LSPA-System.

Uso (Windows):
    venv\\Scripts\\activate
    python run.py

A aplicação ficará disponível em http://127.0.0.1:5000
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config["DEBUG"],
    )
