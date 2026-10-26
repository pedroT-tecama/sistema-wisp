"""Endpoints de abonados: registro, búsqueda y ficha (sección 6.5; HU-01, HU-02, HU-03).

Qué hace:
    Define las direcciones web que el operador usa desde /docs:
        POST /abonados                -> registra un abonado nuevo
        GET  /abonados?buscar=texto   -> busca por DNI o apellidos
        GET  /abonados/{id}           -> muestra la ficha de un abonado
    Cada función recibe la solicitud, llama a GestionAbonadosService y
    devuelve el resultado, o convierte el error del negocio en un código HTTP:
        201 registrado | 404 no existe | 409 IP repetida | 422 datos mal escritos.

Con qué se relaciona:
    - Lo incluye: app/main.py (app.include_router).
    - Llama a: app/services/abonados.py (reglas de negocio).
    - Usa: app/schemas.py (formato de entrada y salida) y app/database.py (sesión).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas import AbonadoCrear, AbonadoFicha, AbonadoResumen
from app.services.abonados import GestionAbonadosService, IpDuplicada, RecursoNoEncontrado

# Todas las rutas de este archivo empiezan con /abonados y se agrupan como "Abonados" en /docs.
router = APIRouter(prefix="/abonados", tags=["Abonados"])


def get_servicio(session: Session = Depends(get_session)) -> GestionAbonadosService:
    """Crea el servicio de abonados con la sesión de base de datos de la solicitud actual."""
    return GestionAbonadosService(session)


@router.post(
    "",
    response_model=AbonadoFicha,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar abonado (HU-01)",
    description="Registra la ficha del abonado al concluir su instalación. "
    "El servicio corre desde el día siguiente; ese día vence su primer pago.",
)
def registrar_abonado(datos: AbonadoCrear, servicio: GestionAbonadosService = Depends(get_servicio)):
    """Registra un abonado y devuelve su ficha completa (201).

    Responde 404 si el ruteador o el plan no existen y 409 si la IP ya está
    usada en ese ruteador.
    """
    try:
        cliente = servicio.registrar_cliente_nuevo(datos)
        return servicio.obtener_ficha(cliente.id)
    except RecursoNoEncontrado as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except IpDuplicada as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


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
