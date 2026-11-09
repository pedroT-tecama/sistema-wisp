"""Endpoints de la cola de órdenes (sección 6.5: «Órdenes pendientes»; HU-03).

Qué hace:
    Permite al operador seguir la cola desde /docs:
        GET  /ordenes?estado=PENDIENTE -> lista las órdenes de la cola (todas, si no se indica estado)
        POST /ordenes/despachar        -> ejecuta en ese momento una vuelta de la cola,
                                          sin esperar a la siguiente vuelta automática
    El despacho automático lo hace app/tareas.py; esta ruta sirve para verificar
    y para las pruebas funcionales.

Con qué se relaciona:
    - Lo incluye: app/main.py (app.include_router).
    - Usa: app/database.py (get_session), app/models.py (TareaPendienteRed),
      app/schemas.py (OrdenDetalle, DespachoResultado) y el controlador de la
      cola de app/tareas.py (ControladorColaSincronizacion).
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import tareas
from app.database import get_session
from app.models import TareaPendienteRed
from app.schemas import DespachoResultado, OrdenDetalle

# Las rutas de la cola se agrupan como "Órdenes" en /docs.
router = APIRouter(prefix="/ordenes", tags=["Órdenes"])


@router.get("", response_model=list[OrdenDetalle], summary="Consultar la cola de órdenes")
def listar_ordenes(estado: Optional[Literal["PENDIENTE", "PROCESADO", "ANULADO"]] = None,
                   session: Session = Depends(get_session)):
    """Devuelve las órdenes de la cola, de la más reciente a la más antigua; se pueden filtrar por estado."""
    consulta = select(TareaPendienteRed).order_by(TareaPendienteRed.id.desc())
    if estado:
        consulta = consulta.where(TareaPendienteRed.estado == estado)
    return session.scalars(consulta).all()


@router.post("/despachar", response_model=DespachoResultado, summary="Aplicar ahora las órdenes pendientes")
async def despachar_ahora():
    """Ejecuta una vuelta de la cola: aplica en los ruteadores las órdenes pendientes y devuelve el resultado."""
    r = await tareas.controlador.despachar_comandos_cola_tareas()
    return DespachoResultado(lote=r.lote, procesadas=r.procesadas, pendientes=r.pendientes,
                             reactivaciones_por_pago=r.reactivaciones_por_pago)
