"""Endpoints de consulta de los enlaces troncales y de sus lecturas de señal (HU-05).

Qué hace:
    Entrega a la interfaz web (app/web) los datos que necesita para graficar la
    señal de cada enlace inalámbrico. Solo consulta la base de datos; no se
    conecta a las antenas ni modifica nada.
        GET /enlaces                         -> enlaces troncales con su umbral de señal
        GET /enlaces/{id}/lecturas?ultimas=20 -> últimas N lecturas del enlace (tiempo real)
        GET /enlaces/{id}/lecturas?horas=6    -> lecturas de las últimas N horas (historial)
    Las lecturas las guarda el monitoreo en cada vuelta (app/monitoreo.py,
    evaluar_senal_enlaces); esta ruta solo las lee.

Con qué se relaciona:
    - Lo incluye: app/main.py (app.include_router).
    - Lo llama: app/web/panel.js (pestaña Enlaces).
    - Usa: app/database.py (get_session) y app/models.py (EnlaceBackhaulPTP, LecturaSenalEnlace).
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import EnlaceBackhaulPTP, LecturaSenalEnlace

# Las rutas se agrupan como "Enlaces" en /docs.
router = APIRouter(prefix="/enlaces", tags=["Enlaces"])


class EnlaceResumen(BaseModel):
    """Datos del enlace que muestra la interfaz web: nombre, antena receptora y umbral (dBm)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre_enlace: str
    ip_antena_destino: str
    rssi_minimo_esperado: int
    frecuencia_operacion: Optional[str]


class Lectura(BaseModel):
    """Una lectura de señal: fecha y hora, y RSSI en dBm."""

    model_config = ConfigDict(from_attributes=True)
    fecha_hora: datetime
    rssi_medido: int


class LecturasEnlace(BaseModel):
    """El enlace con sus lecturas, de la más antigua a la más reciente."""

    enlace: EnlaceResumen
    lecturas: list[Lectura]


@router.get("", response_model=list[EnlaceResumen], summary="Enlaces troncales")
def listar_enlaces(session: Session = Depends(get_session)):
    """Devuelve los enlaces troncales registrados, ordenados por nombre."""
    return session.scalars(select(EnlaceBackhaulPTP).order_by(EnlaceBackhaulPTP.nombre_enlace)).all()


@router.get("/{enlace_id}/lecturas", response_model=LecturasEnlace, summary="Lecturas de señal de un enlace")
def lecturas_enlace(enlace_id: int,
                    ultimas: Optional[int] = Query(default=None, ge=1, le=500, description="Últimas N lecturas"),
                    horas: Optional[int] = Query(default=None, ge=1, le=720, description="Lecturas de las últimas N horas"),
                    session: Session = Depends(get_session)):
    """Devuelve las lecturas del enlace: las últimas N o las de las últimas N horas (por defecto, las últimas 20).

    Responde 404 si el enlace no existe.
    """
    enlace = session.get(EnlaceBackhaulPTP, enlace_id)
    if enlace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No existe el enlace con id {enlace_id}.")
    consulta = select(LecturaSenalEnlace).where(LecturaSenalEnlace.enlace_id == enlace_id)
    if horas:
        desde = datetime.now() - timedelta(hours=horas)
        consulta = consulta.where(LecturaSenalEnlace.fecha_hora >= desde).order_by(LecturaSenalEnlace.fecha_hora)
        lecturas = session.scalars(consulta).all()
    else:
        # se toman las más recientes y se devuelven en orden cronológico para graficarlas
        consulta = consulta.order_by(LecturaSenalEnlace.fecha_hora.desc()).limit(ultimas or 20)
        lecturas = list(reversed(session.scalars(consulta).all()))
    return LecturasEnlace(enlace=EnlaceResumen.model_validate(enlace),
                          lecturas=[Lectura.model_validate(x) for x in lecturas])
