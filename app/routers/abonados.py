"""Endpoints de abonados: registro, búsqueda y ficha (sección 6.5; HU-01, HU-02, HU-03).

Qué hace:
    Define las direcciones web que el operador usa desde /docs:
        POST /abonados                -> registra un abonado nuevo
        GET  /abonados?buscar=texto   -> busca por DNI o apellidos
        GET  /abonados/{id}           -> muestra la ficha de un abonado
    Cada función recibe la solicitud, llama a GestionAbonadosService y
    devuelve el resultado, o convierte el error del negocio en un código HTTP:
        201 registrado | 404 no existe | 409 IP repetida o sin cola simple | 422 datos mal escritos.

    Al registrar, antes de guardar, se verifica en el ruteador que exista la
    cola simple de la IP del abonado:
        - El ruteador responde y no hay cola -> 409, no se registra.
        - La cola existe                     -> se registra con su orden de alta.
        - El ruteador no responde            -> se registra igual, con su orden de
          alta y un aviso: la cola de órdenes la aplicará cuando el equipo vuelva.
    Así el registro comercial nunca queda detenido por una falla de la red.

Con qué se relaciona:
    - Lo incluye: app/main.py (app.include_router).
    - Llama a: app/services/abonados.py (reglas de negocio) y
      app/hal/capa_hardware.py (consulta de la cola simple al registrar).
    - Usa: app/schemas.py (formato de entrada y salida) y app/database.py (sesión).
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_session
from app.hal.capa_hardware import HardwareAbstractionLayer
from app.hal.cliente_api import ErrorComandoRouter, ErrorConexionRouter
from app.hal.drivers import ColaNoEncontrada
from app.models import RouterNode
from app.schemas import AbonadoCrear, AbonadoFicha, AbonadoRegistrado, AbonadoResumen, OrdenResumen
from app.services.abonados import GestionAbonadosService, IpDuplicada, RecursoNoEncontrado

# Todas las rutas de este archivo empiezan con /abonados y se agrupan como "Abonados" en /docs.
router = APIRouter(prefix="/abonados", tags=["Abonados"])


def get_servicio(session: Session = Depends(get_session)) -> GestionAbonadosService:
    """Crea el servicio de abonados con la sesión de base de datos de la solicitud actual."""
    return GestionAbonadosService(session)


@router.post(
    "",
    response_model=AbonadoRegistrado,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar abonado (HU-01)",
    description="Registra la ficha del abonado al concluir su instalación. "
    "El servicio corre desde el día siguiente; ese día vence su primer pago. "
    "Antes de guardar, verifica en el ruteador que exista la cola simple de su IP.",
)
async def registrar_abonado(datos: AbonadoCrear, servicio: GestionAbonadosService = Depends(get_servicio)):
    """Registra un abonado con su orden de alta y devuelve su ficha (201).

    Responde 404 si el ruteador o el plan no existen y 409 si la IP ya está
    usada en ese ruteador o si el ruteador no tiene una cola simple para ella.
    """
    router_db = await asyncio.to_thread(
        servicio.session.get, RouterNode, datos.router_id, options=[joinedload(RouterNode.master)])
    if router_db is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No existe el ruteador con id {datos.router_id}.")
    aviso = await verificar_cola(router_db, str(datos.ip_cliente))

    def registrar():
        cliente = servicio.registrar_cliente_nuevo(datos, con_orden_alta=True)
        orden = cliente.orden_alta
        respuesta = AbonadoRegistrado.model_validate(servicio.obtener_ficha(cliente.id), from_attributes=True)
        respuesta.orden_alta = OrdenResumen.model_validate(orden)
        respuesta.aviso = aviso
        return respuesta

    try:
        return await asyncio.to_thread(registrar)       # la base se usa sin detener al sistema
    except RecursoNoEncontrado as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except IpDuplicada as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


async def verificar_cola(router_db: RouterNode, ip: str) -> Optional[str]:
    """Consulta en el ruteador la cola simple de la IP antes de registrar al abonado.

    Si el ruteador confirma que no hay cola, responde 409 y el registro se detiene.
    Si el ruteador no responde, devuelve un aviso y el registro sigue: la orden de
    alta espera en la cola hasta que el equipo vuelva. Si la cola existe, devuelve None.
    """
    try:
        await HardwareAbstractionLayer().consultar_cola(router_db, ip)
        return None
    except ColaNoEncontrada:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El ruteador {router_db.nombre_equipo} no tiene una cola simple para la IP {ip}. "
                   "Créela en el ruteador y vuelva a registrar al abonado.")
    except (ErrorConexionRouter, ErrorComandoRouter, OSError, asyncio.TimeoutError):
        return (f"No se pudo verificar la cola en {router_db.nombre_equipo} (el ruteador no responde). "
                "El abonado quedó registrado; su configuración se aplicará cuando el ruteador responda.")


@router.get(
    "",
    response_model=list[AbonadoResumen],
    summary="Buscar abonados por DNI o apellidos (HU-02, HU-03)",
)
def buscar_abonados(
    buscar: str = Query(min_length=1, max_length=40, description="DNI completo o parte de los apellidos"),
    servicio: GestionAbonadosService = Depends(get_servicio),
):
    """Devuelve la lista de abonados que coinciden con el texto, ordenada por apellidos."""
    return servicio.buscar_abonados(buscar)


@router.get("/{cliente_id}", response_model=AbonadoFicha, summary="Ficha del abonado")
def ficha_abonado(cliente_id: int, servicio: GestionAbonadosService = Depends(get_servicio)):
    """Devuelve la ficha completa de un abonado por su id; responde 404 si no existe."""
    try:
        return servicio.obtener_ficha(cliente_id)
    except RecursoNoEncontrado as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
