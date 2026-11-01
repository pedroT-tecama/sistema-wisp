"""Pruebas unitarias del registro de pagos (sección 6.7: PU-03, PU-04 y PU-05).

Qué prueba:
    - Pago puntual: conserva su día de pago y no genera órdenes.
    - PU-04: pago después del corte; recalcula el vencimiento y encola la reactivación.
    - PU-05: pago con corte pendiente; anula la orden de corte y vuelve a ACTIVO.
    - PU-03: si falla el registro de la orden, tampoco se registra el pago.
    - Pago de un abonado inexistente: es rechazado.

Cómo se ejecuta (desde la carpeta del proyecto):
    python -m pytest -v

Con qué se relaciona:
    - Prueba app/services/abonados.py (GestionAbonadosService.registrar_pago_abonado).
    - Usa las preparaciones "session" y "red" de tests/conftest.py (base wisp_test).
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import CajaIngreso, TareaPendienteRed
from app.schemas import AbonadoCrear, PagoCrear
from app.services.abonados import GestionAbonadosService, RecursoNoEncontrado


def abonado_con_vencimiento(servicio, red, vencimiento, dia_pago, estado="ACTIVO", fecha_corte=None):
    """Registra un abonado de prueba y le asigna el vencimiento, el día de pago y el estado indicados."""
    cliente = servicio.registrar_cliente_nuevo(AbonadoCrear(
        nombres="Ana", apellidos="Prueba Pagos", dni="45000001", direccion="Jr. Prueba 456",
        ip_cliente="192.168.103.110", router_id=red["router_a"], tarifa_id=red["plan"],
        fecha_registro=date(2026, 9, 1),
    ))
    cliente.fecha_vencimiento = vencimiento
    cliente.dia_pago = dia_pago
    cliente.estado = estado
    cliente.fecha_corte_efectivo = fecha_corte
    servicio.session.commit()
    return cliente


def pago(fecha, monto="50.00"):
    """Datos de un pago en efectivo en la fecha indicada."""
    return PagoCrear(monto=Decimal(monto), medio_pago="Efectivo", fecha_pago=fecha)


def contar(session, modelo, cliente_id):
    """Cuenta las filas de una tabla que pertenecen al abonado."""
    return session.scalar(select(func.count()).select_from(modelo).where(modelo.cliente_id == cliente_id))


# ------------------------------------------------------------ pago puntual
def test_pago_puntual_conserva_su_dia_de_pago(session, red):
    """Vence el 18/10 y paga el 24/10 (dentro de la gracia): próximo vencimiento 18/11, sin órdenes."""
    servicio = GestionAbonadosService(session)
    cliente = abonado_con_vencimiento(servicio, red, date(2026, 10, 18), 18)

    r = servicio.registrar_pago_abonado(cliente.id, pago(date(2026, 10, 24)))

    assert r.cliente.fecha_vencimiento == date(2026, 11, 18)
    assert r.cliente.dia_pago == 18
    assert r.cliente.estado == "ACTIVO"
    assert r.orden_generada is None and r.orden_anulada is None
    assert contar(session, CajaIngreso, cliente.id) == 1


# ------------------------------------------------------------ PU-04
def test_pu04_pago_despues_del_corte_recalcula_y_encola_activacion(session, red):
    """Vence el 01/10, corte el 11/10, paga el 15/10: vence el 04/11 y se encola su reactivación."""
    servicio = GestionAbonadosService(session)
    cliente = abonado_con_vencimiento(servicio, red, date(2026, 10, 1), 1,
                                      estado="SUSPENDIDO", fecha_corte=date(2026, 10, 11))

    r = servicio.registrar_pago_abonado(cliente.id, pago(date(2026, 10, 15)))

    assert r.cliente.fecha_vencimiento == date(2026, 11, 4)
    assert r.cliente.dia_pago == 4
    assert r.cliente.fecha_corte_efectivo is None
    assert r.cliente.estado == "SUSPENDIDO"          # se reactiva cuando la orden se aplica en el ruteador
    assert r.orden_generada.accion == "ACTIVACION"
    assert r.orden_generada.estado == "PENDIENTE"
    assert r.orden_generada.payload_parametros_red == {
        "ip_cliente": "192.168.103.110", "rate_upload": "4M", "rate_download": "7M",
    }


# ------------------------------------------------------------ PU-05
def test_pu05_pago_con_corte_pendiente_anula_la_orden(session, red):
    """Con el corte ordenado pero sin aplicar, el pago lo anula y el abonado vuelve a ACTIVO sin activación."""
    servicio = GestionAbonadosService(session)
    cliente = abonado_con_vencimiento(servicio, red, date(2026, 10, 1), 1, estado="PENDIENTE_SUSPENSION")
    corte = TareaPendienteRed(router_id=cliente.router_id, cliente_id=cliente.id, accion="CORTE",
                              payload_parametros_red={"ip_cliente": cliente.ip_cliente}, estado="PENDIENTE")
    session.add(corte)
    session.commit()

    r = servicio.registrar_pago_abonado(cliente.id, pago(date(2026, 10, 12)))

    assert r.cliente.estado == "ACTIVO"
    assert r.orden_anulada.id == corte.id
    assert r.orden_anulada.estado == "ANULADO"
    assert r.orden_generada is None
    assert r.cliente.fecha_vencimiento == date(2026, 11, 1)
    activaciones = session.scalar(select(func.count()).select_from(TareaPendienteRed).where(
        TareaPendienteRed.cliente_id == cliente.id, TareaPendienteRed.accion == "ACTIVACION"))
    assert activaciones == 0


# ------------------------------------------------------------ PU-03
def test_pu03_si_falla_la_orden_no_se_registra_el_pago(session, red, monkeypatch):
    """Si falla el registro de la orden de activación, no queda ni el pago ni el cambio de vencimiento."""
    servicio = GestionAbonadosService(session)
    cliente = abonado_con_vencimiento(servicio, red, date(2026, 10, 1), 1,
                                      estado="SUSPENDIDO", fecha_corte=date(2026, 10, 11))

    def orden_que_falla(_cliente):
        raise RuntimeError("falla simulada al registrar la orden")

    monkeypatch.setattr(servicio, "_registrar_orden_activacion", orden_que_falla)

    with pytest.raises(RuntimeError):
        servicio.registrar_pago_abonado(cliente.id, pago(date(2026, 10, 15)))

    session.refresh(cliente)
    assert contar(session, CajaIngreso, cliente.id) == 0
    assert contar(session, TareaPendienteRed, cliente.id) == 0
    assert cliente.fecha_vencimiento == date(2026, 10, 1)
    assert cliente.estado == "SUSPENDIDO"


# ------------------------------------------------------------ abonado inexistente
def test_pago_de_abonado_inexistente_es_rechazado(session, red):
    """Un pago para un abonado que no existe no se registra."""
    servicio = GestionAbonadosService(session)
    with pytest.raises(RecursoNoEncontrado):
        servicio.registrar_pago_abonado(999999, pago(date(2026, 10, 15)))
