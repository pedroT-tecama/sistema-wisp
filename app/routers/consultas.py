"""Consultas de solo lectura para el panel web: planes de servicio y mapa de la red.

Qué hace:
    Entrega a la interfaz web (app/web) datos que ya están en la base, armados para mostrarse:
        GET /consultas/planes     -> planes de servicio, para elegir el plan en el alta del abonado
        GET /consultas/topologia  -> ruteadores, conexiones y enlaces con su estado, para dibujar la red
    No se conecta a los equipos ni modifica nada: el estado de cada ruteador y de cada enlace
    es el que el monitoreo (app/monitoreo.py) ya determinó y guardó en la base.

Con qué se relaciona:
    - Lo incluye: app/main.py (app.include_router).
    - Lo llama: app/web/panel.js (pestañas Nuevo abonado y Red, y el aviso de averías).
    - Usa: app/database.py (get_session), app/models.py (RouterNode, EnlaceBackhaulPTP,
      LecturaSenalEnlace, RegistroAlerta, Cliente, PerfilTarifa) y app/notificador.py
      (NotificadorCorreo, solo para saber si el envío de correos está activado).
"""
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Cliente, EnlaceBackhaulPTP, LecturaSenalEnlace, PerfilTarifa, RegistroAlerta, RouterNode
from app.notificador import NotificadorCorreo

# Las rutas se agrupan como "Consultas del panel" en /docs.
router = APIRouter(prefix="/consultas", tags=["Consultas del panel"])

# Una lectura de señal se considera reciente si tiene menos de tres vueltas del monitoreo.
INTERVALO = int(os.getenv("MONITOREO_INTERVALO_SEGUNDOS", "30"))


class Plan(BaseModel):
    """Plan de servicio que se muestra en la lista del alta."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre_plan: str
    precio_mensual: Decimal
    rate_upload: str
    rate_download: str


class Nodo(BaseModel):
    """Ruteador del mapa con su estado según el monitoreo."""

    id: int
    nombre: str
    ip: str
    padre_id: Optional[int]
    estado: str                      # CHECK_OK, NODO_CAIDO o CABECERA_INACCESIBLE (solo la raíz)
    en_cascada: bool                 # caído porque cayó un ruteador superior
    abonados: int
    alerta: Optional[str]            # descripción de su alerta abierta, si la tiene


class Enlace(BaseModel):
    """Enlace troncal inalámbrico del mapa con su estado."""

    id: int
    nombre: str
    origen_id: int
    destino_id: int
    umbral: int
    ultima_senal: Optional[int]
    ultima_lectura: Optional[datetime]
    estado: str                      # OK, DEGRADADO o CAIDO
    alerta: Optional[str]


class Topologia(BaseModel):
    """Mapa completo: nodos, enlaces y si el correo de alertas está activado."""

    nodos: list[Nodo]
    enlaces: list[Enlace]
    correo_activo: bool
    generado: datetime


@router.get("/planes", response_model=list[Plan], summary="Planes de servicio")
def listar_planes(session: Session = Depends(get_session)):
    """Devuelve los planes de servicio ordenados por precio."""
    return session.scalars(select(PerfilTarifa).order_by(PerfilTarifa.precio_mensual)).all()


@router.get("/topologia", response_model=Topologia, summary="Mapa de la red con su estado")
def topologia(session: Session = Depends(get_session)):
    """Arma el árbol de ruteadores y los enlaces troncales con el estado guardado por el monitoreo.

    Reglas (las mismas del monitoreo):
      - Ruteador caído: estado_operativo NODO_CAIDO; en cascada si su ruteador superior también lo está.
      - Cabecera inaccesible: alerta CABECERA_INACCESIBLE abierta en su distrito (se marca la raíz).
      - Enlace degradado: alerta PTP_DEGRADADO abierta.
      - Enlace caído: el ruteador que alimenta está caído y la antena no tiene una lectura reciente.
    """
    ahora = datetime.now()
    rs = session.scalars(select(RouterNode).order_by(RouterNode.id)).all()
    abiertas = session.scalars(select(RegistroAlerta).where(RegistroAlerta.fecha_resolucion.is_(None))).all()
    abonados = dict(session.execute(select(Cliente.router_id, func.count()).group_by(Cliente.router_id)).all())
    cabeceras_mudas = {a.master_id for a in abiertas if a.prefijo_excepcion == "CABECERA_INACCESIBLE"}
    alerta_router = {a.router_id: a.descripcion_error for a in abiertas if a.router_id}
    alerta_enlace = {a.enlace_id: a.descripcion_error for a in abiertas if a.enlace_id}
    caidos = {r.id for r in rs if r.estado_operativo == "NODO_CAIDO"}

    nodos = []
    for r in rs:
        estado = "CABECERA_INACCESIBLE" if r.padre_id is None and r.master_id in cabeceras_mudas else r.estado_operativo
        nodos.append(Nodo(id=r.id, nombre=r.nombre_equipo, ip=r.ip_router, padre_id=r.padre_id, estado=estado,
                          en_cascada=r.id in caidos and r.padre_id in caidos, abonados=abonados.get(r.id, 0),
                          alerta=alerta_router.get(r.id)))

    enlaces = []
    for e in session.scalars(select(EnlaceBackhaulPTP)).all():
        ult = session.scalars(select(LecturaSenalEnlace).where(LecturaSenalEnlace.enlace_id == e.id)
                              .order_by(LecturaSenalEnlace.fecha_hora.desc()).limit(1)).first()
        reciente = ult is not None and ult.fecha_hora >= ahora - timedelta(seconds=3 * INTERVALO)
        if e.router_destino_id in caidos and not reciente:
            estado = "CAIDO"
        elif e.id in alerta_enlace:
            estado = "DEGRADADO"
        else:
            estado = "OK"
        enlaces.append(Enlace(id=e.id, nombre=e.nombre_enlace, origen_id=e.router_origen_id,
                              destino_id=e.router_destino_id, umbral=e.rssi_minimo_esperado,
                              ultima_senal=ult.rssi_medido if ult else None,
                              ultima_lectura=ult.fecha_hora if ult else None,
                              estado=estado, alerta=alerta_enlace.get(e.id)))

    return Topologia(nodos=nodos, enlaces=enlaces, correo_activo=NotificadorCorreo().activo, generado=ahora)
