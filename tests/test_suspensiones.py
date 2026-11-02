"""Pruebas unitarias de las suspensiones (sección 6.7: PU-06; HU-03).

Qué prueba:
    - PU-06: la suspensión diaria solo encola el corte de los abonados cuya
      fecha de vencimiento más los días de gracia ya fue superada.
    - La suspensión diaria puede repetirse el mismo día sin duplicar órdenes.
    - Suspensión manual: un abonado ACTIVO pasa a PENDIENTE_SUSPENSION con su orden de corte.
    - Suspensión manual rechazada si el abonado no está ACTIVO o no existe.

Cómo se ejecuta (desde la carpeta del proyecto):
    python -m pytest -v

Con qué se relaciona:
    - Prueba app/services/abonados.py (procesar_vencimientos y suspender_abonado_manual).
    - Usa las preparaciones "session" y "red" de tests/conftest.py (base wisp_test).
"""
from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import TareaPendienteRed
from app.schemas import AbonadoCrear
from app.services.abonados import EstadoNoPermitido, GestionAbonadosService, RecursoNoEncontrado


def abonado(servicio, red, ip, dni, vencimiento, estado="ACTIVO"):
    """Registra un abonado de prueba con la IP, el vencimiento y el estado indicados."""
    cliente = servicio.registrar_cliente_nuevo(AbonadoCrear(
        nombres="Prueba", apellidos="Suspensión " + dni[-2:], dni=dni, direccion="Jr. Prueba 789",
        ip_cliente=ip, router_id=red["router_a"], tarifa_id=red["plan"], fecha_registro=date(2026, 9, 1),
    ))
    cliente.fecha_vencimiento = vencimiento
    cliente.dia_pago = vencimiento.day
    cliente.estado = estado
    servicio.session.commit()
    return cliente


def cortes_de(session, cliente_id):
    """Cuenta las órdenes de corte del abonado."""
    return session.scalar(select(func.count()).select_from(TareaPendienteRed).where(
        TareaPendienteRed.cliente_id == cliente_id, TareaPendienteRed.accion == "CORTE"))


# ------------------------------------------------------------ PU-06
def test_pu06_solo_se_corta_a_quien_supero_la_gracia(session, red):
    """El 12/10: se corta a quien venció el 01/10 (gracia hasta el 11/10); no a quien está en gracia, al día o ya suspendido."""
    servicio = GestionAbonadosService(session)
    vencido = abonado(servicio, red, "192.168.103.121", "46000001", date(2026, 10, 1))
    en_gracia = abonado(servicio, red, "192.168.103.122", "46000002", date(2026, 10, 2))      # gracia hasta el 12/10
    al_dia = abonado(servicio, red, "192.168.103.123", "46000003", date(2026, 10, 20))
    suspendido = abonado(servicio, red, "192.168.103.124", "46000004", date(2026, 9, 1), estado="SUSPENDIDO")

    resultados = servicio.procesar_vencimientos(hoy=date(2026, 10, 12))

    assert [r.cliente.id for r in resultados] == [vencido.id]
    assert vencido.estado == "PENDIENTE_SUSPENSION"
    orden = resultados[0].orden
    assert (orden.accion, orden.estado) == ("CORTE", "PENDIENTE")
    assert orden.payload_parametros_red == {"ip_cliente": "192.168.103.121", "rate_upload": "1k", "rate_download": "1k"}
    for cliente in (en_gracia, al_dia, suspendido):
        assert cortes_de(session, cliente.id) == 0
    assert en_gracia.estado == "ACTIVO" and al_dia.estado == "ACTIVO"


def test_suspension_diaria_repetida_no_duplica_ordenes(session, red):
    """Si la tarea diaria se ejecuta dos veces el mismo día, el abonado vencido tiene una sola orden de corte."""
    servicio = GestionAbonadosService(session)
    vencido = abonado(servicio, red, "192.168.103.121", "46000001", date(2026, 10, 1))

    servicio.procesar_vencimientos(hoy=date(2026, 10, 12))
    segunda = servicio.procesar_vencimientos(hoy=date(2026, 10, 12))

    assert segunda == []
    assert cortes_de(session, vencido.id) == 1


# ------------------------------------------------------------ suspensión manual
def test_suspension_manual_de_abonado_activo(session, red):
    """Un abonado ACTIVO suspendido por el negocio pasa a PENDIENTE_SUSPENSION con su orden de corte."""
    servicio = GestionAbonadosService(session)
    cliente = abonado(servicio, red, "192.168.103.125", "46000005", date(2026, 10, 20))

    r = servicio.suspender_abonado_manual(cliente.id)

    assert r.cliente.estado == "PENDIENTE_SUSPENSION"
    assert (r.orden.accion, r.orden.estado) == ("CORTE", "PENDIENTE")
    assert r.cliente.fecha_vencimiento == date(2026, 10, 20)     # el vencimiento no cambia al suspender


def test_suspension_manual_rechazada_si_no_esta_activo(session, red):
    """No se puede suspender a un abonado que ya está suspendido; no se crea otra orden."""
    servicio = GestionAbonadosService(session)
    cliente = abonado(servicio, red, "192.168.103.126", "46000006", date(2026, 9, 1), estado="SUSPENDIDO")

    with pytest.raises(EstadoNoPermitido):
        servicio.suspender_abonado_manual(cliente.id)
    assert cortes_de(session, cliente.id) == 0


def test_suspension_manual_de_abonado_inexistente(session, red):
    """Suspender a un abonado que no existe es rechazado."""
    servicio = GestionAbonadosService(session)
    with pytest.raises(RecursoNoEncontrado):
        servicio.suspender_abonado_manual(999999)
