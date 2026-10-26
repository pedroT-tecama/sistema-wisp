"""Preparación común de las pruebas unitarias (sección 6.7).

Qué hace:
    - Conecta las pruebas SIEMPRE a la base de pruebas wisp_test (DB_URL_TEST),
      nunca a la base de operación wisp_db. Si DB_URL_TEST no apunta a wisp_test,
      las pruebas no se ejecutan.
    - "session": abre una transacción para cada prueba y la deshace al terminar.
      Así ninguna prueba deja datos guardados y cada una empieza con la base vacía.
    - "red": crea los datos mínimos para registrar abonados: dos distritos de
      prueba, un ruteador en cada uno y un plan.

Con qué se relaciona:
    - pytest lo carga automáticamente antes de ejecutar tests/test_abonados.py.
    - Usa app/models.py para crear los datos de prueba.
    - Lee DB_URL_TEST del archivo .env.
"""
import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import PerfilTarifa, RouterMaster, RouterNode

load_dotenv()
DB_URL_TEST = os.getenv("DB_URL_TEST")
if not DB_URL_TEST or "wisp_test" not in DB_URL_TEST:
    raise RuntimeError("Las pruebas requieren DB_URL_TEST apuntando a la base wisp_test (archivo .env).")

engine = create_engine(DB_URL_TEST)


@pytest.fixture
def session():
    """Sesión de base de datos para una prueba; todo lo que la prueba guarda se deshace al final."""
    conexion = engine.connect()
    transaccion = conexion.begin()
    # Los commit que hace el servicio quedan dentro de esta transacción y se deshacen al terminar.
    sesion = Session(bind=conexion, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield sesion
    sesion.close()
    transaccion.rollback()
    conexion.close()


@pytest.fixture
def red(session):
    """Datos mínimos de red: dos distritos con un ruteador cada uno y un plan.

    Devuelve los id para usarlos en las pruebas: router_a, router_b y plan.
    """
    distrito_a = RouterMaster(nombre_distrito="Distrito Prueba A", ddns_url="10.0.0.1", puerto_base=8001)
    distrito_b = RouterMaster(nombre_distrito="Distrito Prueba B", ddns_url="10.0.1.1", puerto_base=8001)
    session.add_all([distrito_a, distrito_b])
    session.flush()
    router_a = RouterNode(master_id=distrito_a.id, nombre_equipo="Router A", tipo_nodo="ROUTER",
                          ip_gestion_ospf="10.0.0.2", puerto_socket=8002)
    router_b = RouterNode(master_id=distrito_b.id, nombre_equipo="Router B", tipo_nodo="ROUTER",
                          ip_gestion_ospf="10.0.1.2", puerto_socket=8002)
    plan = PerfilTarifa(nombre_plan="Plan Prueba", precio_mensual=50, rate_upload="4M", rate_download="7M")
    session.add_all([router_a, router_b, plan])
    session.flush()
    return {"router_a": router_a.id, "router_b": router_b.id, "plan": plan.id}
