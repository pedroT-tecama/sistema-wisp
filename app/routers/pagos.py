"""Endpoint de pagos: registro del pago de un abonado (sección 6.5; HU-02, HU-03).

Qué hace:
    Define la dirección web que el operador usa desde /docs para cobrar:
        POST /abonados/{cliente_id}/pagos  -> registra el pago y actualiza el vencimiento
    Recibe el pago, llama a GestionAbonadosService.registrar_pago_abonado() y
    responde con el nuevo vencimiento y lo que pasó con las órdenes de la cola:
        201 registrado | 404 el abonado no existe | 422 datos mal escritos.

Con qué se relaciona:
    - Lo incluye: app/main.py (app.include_router).
    - Llama a: app/services/abonados.py (registrar_pago_abonado).
    - Usa: app/schemas.py (PagoCrear, PagoResultado) y app/routers/abonados.py
      (get_servicio, que crea el servicio con la sesión de la base de datos).
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.routers.abonados import get_servicio
from app.schemas import OrdenResumen, PagoCrear, PagoResultado
from app.services.abonados import GestionAbonadosService, RecursoNoEncontrado

# Las rutas de pagos cuelgan del abonado y se agrupan como "Pagos" en /docs.
router = APIRouter(prefix="/abonados", tags=["Pagos"])


@router.post(
    "/{cliente_id}/pagos",
    response_model=PagoResultado,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar pago del abonado (HU-02)",
    description="Registra el pago y calcula el nuevo vencimiento. Si el abonado estaba cortado, "
    "encola su reactivación; si el corte aún no se había aplicado, lo anula.",
)
def registrar_pago(cliente_id: int, datos: PagoCrear, servicio: GestionAbonadosService = Depends(get_servicio)):
    """Registra el pago de un abonado y devuelve su nuevo vencimiento (201); 404 si no existe."""
    try:
        r = servicio.registrar_pago_abonado(cliente_id, datos)
    except RecursoNoEncontrado as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))

    if r.orden_generada is not None:
        mensaje = "Pago registrado. Reactivación encolada; el servicio se restablece al aplicarse en el ruteador."
    elif r.orden_anulada is not None:
        mensaje = "Pago registrado. Se anuló el corte pendiente; el abonado sigue activo."
    else:
        mensaje = "Pago registrado. El abonado sigue activo."

    return PagoResultado(
        pago_id=r.pago.id,
        cliente_id=r.cliente.id,
        monto=r.pago.monto,
        fecha_pago=r.pago.fecha_registro,
        nuevo_vencimiento=r.cliente.fecha_vencimiento,
        dia_pago=r.cliente.dia_pago,
        estado_abonado=r.cliente.estado,
        orden_generada=OrdenResumen.model_validate(r.orden_generada) if r.orden_generada else None,
        orden_anulada=OrdenResumen.model_validate(r.orden_anulada) if r.orden_anulada else None,
        mensaje=mensaje,
    )
