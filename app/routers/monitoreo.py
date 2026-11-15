"""Endpoints del monitoreo de conectividad (HU-04, HU-05).

Qué hace:
    Permite al operador seguir el monitoreo desde /docs:
        GET  /monitoreo/ruteadores          -> estado de cada ruteador (CHECK_OK o NODO_CAIDO)
        GET  /monitoreo/alertas?abiertas=1  -> alertas registradas (solo las abiertas, si se indica)
        POST /monitoreo/evaluar             -> ejecuta en ese momento una vuelta del monitoreo,
                                               sin esperar a la siguiente vuelta automática
    El monitoreo automático lo hace app/tareas.py; esta ruta sirve para verificar
    y para las pruebas funcionales.

Con qué se relaciona:
    - Lo incluye: app/main.py (app.include_router).
    - Usa: app/database.py (get_session), app/models.py (RouterNode, RegistroAlerta),
      app/schemas.py (RuteadorEstado, AlertaDetalle, EvaluacionResultado) y el motor
      de monitoreo de app/tareas.py (MotorTelemetriaProactiva).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import tareas
from app.database import get_session
from app.models import RegistroAlerta, RouterNode
from app.schemas import AlertaDetalle, EvaluacionResultado, RuteadorEstado

# Las rutas del monitoreo se agrupan como "Monitoreo" en /docs.
router = APIRouter(prefix="/monitoreo", tags=["Monitoreo"])


@router.get("/ruteadores", response_model=list[RuteadorEstado], summary="Estado de los ruteadores")
def listar_ruteadores(session: Session = Depends(get_session)):
    """Devuelve cada ruteador con su bandera OSPF y su estado según el monitoreo."""
    return session.scalars(select(RouterNode).order_by(RouterNode.id)).all()


@router.get("/alertas", response_model=list[AlertaDetalle], summary="Consultar las alertas")
def listar_alertas(abiertas: bool = False, session: Session = Depends(get_session)):
    """Devuelve las alertas, de la más reciente a la más antigua; con abiertas=true, solo las no resueltas."""
    consulta = select(RegistroAlerta).order_by(RegistroAlerta.id_alerta.desc())
    if abiertas:
        consulta = consulta.where(RegistroAlerta.fecha_resolucion.is_(None))
    return session.scalars(consulta).all()


@router.post("/evaluar", response_model=EvaluacionResultado, summary="Evaluar ahora la conectividad")
async def evaluar_ahora():
    """Ejecuta una vuelta del monitoreo: lee la tabla de rutas de cada cabecera y actualiza los ruteadores."""
    r = await tareas.monitor.ejecutar_monitoreo_distrital()
    return EvaluacionResultado(vuelta=r.vuelta, caidos=r.caidos, restablecidos=r.restablecidos,
                               cabeceras_sin_respuesta=r.cabeceras_sin_respuesta)
