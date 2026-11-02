"""Endpoint de suspensión manual de un abonado (sección 6.5; HU-03).

Qué hace:
    Define la dirección web que el operador usa desde /docs para suspender a
    un abonado por decisión del negocio, antes de que termine su plazo de gracia:
        POST /abonados/{cliente_id}/suspension -> pasa a PENDIENTE_SUSPENSION y encola el corte
    Responde: 201 suspendido | 404 el abonado no existe | 409 el abonado no está ACTIVO.
    La suspensión automática por vencimiento no está aquí: la ejecuta una vez al
    día app/tareas.py, sin intervención del operador.

Con qué se relaciona:
    - Lo incluye: app/main.py (app.include_router).
    - Llama a: app/services/abonados.py (suspender_abonado_manual).
    - Usa: app/schemas.py (SuspensionResultado) y app/routers/abonados.py (get_servicio).
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.routers.abonados import get_servicio
from app.schemas import OrdenResumen, SuspensionResultado
from app.services.abonados import EstadoNoPermitido, GestionAbonadosService, RecursoNoEncontrado

# Las rutas de suspensión cuelgan del abonado y se agrupan como "Suspensiones" en /docs.
router = APIRouter(prefix="/abonados", tags=["Suspensiones"])


@router.post(
    "/{cliente_id}/suspension",
    response_model=SuspensionResultado,
    status_code=status.HTTP_201_CREATED,
    summary="Suspender abonado por decisión del negocio (HU-03)",
    description="Pasa al abonado a PENDIENTE_SUSPENSION y encola su orden de corte. "
    "El corte se aplica en el ruteador cuando la cola de órdenes la procesa.",
)
def suspender_abonado(cliente_id: int, servicio: GestionAbonadosService = Depends(get_servicio)):
    """Suspende a un abonado ACTIVO (201); 404 si no existe; 409 si no está ACTIVO."""
    try:
        r = servicio.suspender_abonado_manual(cliente_id)
    except RecursoNoEncontrado as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except EstadoNoPermitido as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return SuspensionResultado(
        cliente_id=r.cliente.id,
        estado_abonado=r.cliente.estado,
        fecha_vencimiento=r.cliente.fecha_vencimiento,
        orden_corte=OrdenResumen.model_validate(r.orden),
        mensaje="Suspensión registrada. El corte se aplicará cuando la cola de órdenes lo procese en el ruteador.",
    )
