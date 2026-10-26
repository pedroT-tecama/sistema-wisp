"""Conexión con MySQL mediante SQLAlchemy (sección 6.4).

Equivale a configurar el DataSource en Java: se crea una sola vez y
cada solicitud abre su propia sesión, que se cierra al terminar.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise RuntimeError("Falta la variable DB_URL en el archivo .env")

# pool_pre_ping: comprueba la conexión antes de usarla (evita errores tras inactividad)
engine = create_engine(DB_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session():
    """Entrega una sesión por solicitud y la cierra al terminar (sección 6.4)."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
