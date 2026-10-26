"""Conexión con la base de datos MySQL (sección 6.4).

Qué hace:
    Lee la dirección de la base de datos (DB_URL) del archivo .env y prepara
    la conexión. Cada solicitud que llega al sistema recibe su propia sesión
    de base de datos, que se cierra al terminar la solicitud.

Con qué se relaciona:
    - Archivo .env               : contiene DB_URL (usuario wisp_app, base wisp_db).
    - app/main.py                : usa "engine" en la ruta /salud/db.
    - app/routers/abonados.py    : usa "get_session" para entregar una sesión a cada solicitud.
    - app/services/...           : reciben esa sesión para leer y guardar datos.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise RuntimeError("Falta la variable DB_URL en el archivo .env")

# Motor de conexión. pool_pre_ping comprueba que la conexión siga viva antes de
# usarla, para evitar errores cuando MySQL cierra conexiones inactivas.
engine = create_engine(DB_URL, pool_pre_ping=True)

# Fábrica de sesiones: cada llamada a SessionLocal() abre una sesión nueva.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    """Entrega una sesión de base de datos a una solicitud y la cierra al terminar.

    FastAPI la llama automáticamente en cada solicitud que la declara con
    Depends(get_session) (ver app/routers/abonados.py).
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
