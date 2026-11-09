"""Pruebas unitarias de la cola de órdenes (ControladorColaSincronizacion; HU-03).

Qué prueba:
    - Corte aplicado: la orden pasa a PROCESADO y el abonado a SUSPENDIDO, con la fecha del corte.
    - Corte antes del vencimiento (suspensión manual): los días no usados quedan como saldo a favor.
    - Reactivación aplicada: el abonado vuelve a ACTIVO con las velocidades de su plan.
    - Ruteador sin respuesta: la orden sigue PENDIENTE, se cuenta el intento y se aplica en la vuelta siguiente.
    - Órdenes del mismo abonado: el corte y la reactivación se aplican en el orden en que se crearon.
    - Pago durante el corte: si el corte se anuló mientras se aplicaba, se encola la reactivación.
    - Las órdenes ANULADO no se envían al ruteador.

Cómo se prueba sin ruteador:
    RuteadorSimulado reemplaza a HardwareAbstractionLayer: registra cada orden
    recibida y puede simular que el equipo no responde. La base es wisp_test,
    con las preparaciones "session" y "red" de tests/conftest.py.

Con qué se relaciona:
    - Prueba app/cola_sincronizacion.py (ControladorColaSincronizacion).
    - Usa app/services/abonados.py para crear abonados y órdenes como en la operación real.
"""
import asyncio
from contextlib import nullcontext
from datetime import date

from sqlalchemy import select

from app.cola_sincronizacion import ControladorColaSincronizacion
from app.hal.cliente_api import ErrorConexionRouter
from app.models import TareaPendienteRed
from app.schemas import AbonadoCrear, PagoCrear
from app.services.abonados import GestionAbonadosService

HOY = date(2026, 10, 12)


class RuteadorSimulado:
    """Reemplazo de HardwareAbstractionLayer: guarda las órdenes recibidas y puede fallar a pedido."""

    def __init__(self, responde=True, al_aplicar=None):
        self.responde = responde
        self.al_aplicar = al_aplicar          # acción opcional mientras "se aplica" la orden
        self.recibidas = []

    async def _recibir(self, orden):
        if self.al_aplicar:
            self.al_aplicar()
        if not self.responde:
            raise ErrorConexionRouter("el ruteador no responde (simulado)")
        self.recibidas.append(orden)
        return True

    async def suspender_ancho_banda(self, router, ip):
        return await self._recibir(("CORTE", ip))

    async def reactivar_ancho_banda(self, router, ip, upload, download):
        return await self._recibir(("ACTIVACION", ip, upload, download))


def controlador(session, ruteador):
    """Controlador que usa la sesión de prueba (sin cerrarla) y el ruteador simulado."""
    return ControladorColaSincronizacion(sesion=lambda: nullcontext(session), hal=ruteador)


def despachar(ctrl):
    """Ejecuta una vuelta de la cola con la fecha de la prueba."""
    return asyncio.run(ctrl.despachar_comandos_cola_tareas(hoy=HOY))


def abonado_en_corte(servicio, red, ip, dni, vencimiento):
    """Registra un abonado activo y lo suspende de forma manual: queda PENDIENTE_SUSPENSION con su orden de CORTE."""
    cliente = servicio.registrar_cliente_nuevo(AbonadoCrear(
        nombres="Prueba", apellidos="Cola " + dni[-2:], dni=dni, direccion="Jr. Prueba 321",
        ip_cliente=ip, router_id=red["router_a"], tarifa_id=red["plan"], fecha_registro=date(2026, 9, 1),
    ))
    cliente.fecha_vencimiento = vencimiento
    cliente.dia_pago = vencimiento.day
    servicio.session.commit()
    return servicio.suspender_abonado_manual(cliente.id)


# ------------------------------------------------------------ corte
def test_corte_aplicado_suspende_al_abonado(session, red):
    """El ruteador aplica el corte: orden PROCESADO; abonado SUSPENDIDO con la fecha del corte y sin saldo a favor."""
    servicio = GestionAbonadosService(session)
    r = abonado_en_corte(servicio, red, "192.168.103.131", "47000001", date(2026, 10, 1))
    ruteador = RuteadorSimulado()

    resumen = despachar(controlador(session, ruteador))

    assert resumen.procesadas == [r.orden.id]
    assert ruteador.recibidas == [("CORTE", "192.168.103.131")]
    assert (r.orden.estado, r.orden.intentos) == ("PROCESADO", 1)
    assert r.cliente.estado == "SUSPENDIDO"
    assert r.cliente.fecha_corte_efectivo == HOY
    assert r.cliente.saldo_dias_favor == 0


def test_corte_antes_del_vencimiento_guarda_saldo_a_favor(session, red):
    """Suspensión manual el 12/10 con vencimiento el 20/10: quedan 8 días pagados a favor del abonado."""
    servicio = GestionAbonadosService(session)
    r = abonado_en_corte(servicio, red, "192.168.103.132", "47000002", date(2026, 10, 20))

    despachar(controlador(session, RuteadorSimulado()))

    assert r.cliente.estado == "SUSPENDIDO"
    assert r.cliente.saldo_dias_favor == 8


# ------------------------------------------------------------ ruteador sin respuesta
def test_ruteador_sin_respuesta_deja_la_orden_pendiente(session, red):
    """Si el ruteador no responde, la orden sigue PENDIENTE; cuando vuelve, se aplica en la siguiente vuelta."""
    servicio = GestionAbonadosService(session)
    r = abonado_en_corte(servicio, red, "192.168.103.133", "47000003", date(2026, 10, 1))
    ruteador = RuteadorSimulado(responde=False)
    ctrl = controlador(session, ruteador)

    primera = despachar(ctrl)
    assert primera.pendientes == [r.orden.id]
    assert (r.orden.estado, r.orden.intentos) == ("PENDIENTE", 1)
    assert r.cliente.estado == "PENDIENTE_SUSPENSION"

    ruteador.responde = True            # el ruteador vuelve
    segunda = despachar(ctrl)
    assert segunda.procesadas == [r.orden.id]
    assert (r.orden.estado, r.orden.intentos) == ("PROCESADO", 2)
    assert r.cliente.estado == "SUSPENDIDO"


# ------------------------------------------------------------ reactivación
def test_reactivacion_aplicada_activa_al_abonado(session, red):
    """Corte aplicado y luego pago: la reactivación usa las velocidades del plan y el abonado vuelve a ACTIVO."""
    servicio = GestionAbonadosService(session)
    r = abonado_en_corte(servicio, red, "192.168.103.134", "47000004", date(2026, 10, 1))
    ruteador = RuteadorSimulado()
    ctrl = controlador(session, ruteador)
    despachar(ctrl)                                         # se aplica el corte
    pago = servicio.registrar_pago_abonado(r.cliente.id, PagoCrear(monto=50, medio_pago="Efectivo"), hoy=date(2026, 10, 15))

    resumen = despachar(ctrl)                               # se aplica la reactivación

    assert resumen.procesadas == [pago.orden_generada.id]
    assert ruteador.recibidas[-1] == ("ACTIVACION", "192.168.103.134", "4M", "7M")
    assert pago.orden_generada.estado == "PROCESADO"
    assert r.cliente.estado == "ACTIVO"


def test_ordenes_del_mismo_abonado_en_el_orden_de_creacion(session, red):
    """Con un corte y una reactivación pendientes del mismo abonado, primero se aplica el corte y luego la reactivación."""
    servicio = GestionAbonadosService(session)
    r = abonado_en_corte(servicio, red, "192.168.103.135", "47000005", date(2026, 10, 1))
    r.cliente.estado = "SUSPENDIDO"                         # simula que el corte ya se ordenó y el abonado pagó
    reactivacion = servicio._registrar_orden_activacion(r.cliente)
    session.commit()
    ruteador = RuteadorSimulado()
    ctrl = controlador(session, ruteador)

    despachar(ctrl)
    assert [o[0] for o in ruteador.recibidas] == ["CORTE"]   # en la primera vuelta, solo el corte
    assert reactivacion.estado == "PENDIENTE"
    despachar(ctrl)
    assert [o[0] for o in ruteador.recibidas] == ["CORTE", "ACTIVACION"]
    assert r.cliente.estado == "ACTIVO"


# ------------------------------------------------------------ pago durante el corte
def test_pago_mientras_se_aplica_el_corte_encola_la_reactivacion(session, red):
    """El abonado paga mientras el corte se aplica: el corte ya quedó en el ruteador, así que se encola su reactivación."""
    servicio = GestionAbonadosService(session)
    r = abonado_en_corte(servicio, red, "192.168.103.136", "47000006", date(2026, 10, 1))

    def pagar():                                            # el pago llega mientras el ruteador aplica el corte
        servicio.registrar_pago_abonado(r.cliente.id, PagoCrear(monto=50, medio_pago="Yape"), hoy=HOY)

    resumen = despachar(controlador(session, RuteadorSimulado(al_aplicar=pagar)))

    assert resumen.reactivaciones_por_pago == [r.orden.id]
    assert r.orden.estado == "ANULADO"
    assert r.cliente.estado == "ACTIVO"
    pendientes = session.scalars(select(TareaPendienteRed).where(
        TareaPendienteRed.cliente_id == r.cliente.id, TareaPendienteRed.estado == "PENDIENTE")).all()
    assert [o.accion for o in pendientes] == ["ACTIVACION"]


def test_ordenes_anuladas_no_se_envian(session, red):
    """Una orden de corte anulada (el abonado pagó antes) no llega al ruteador."""
    servicio = GestionAbonadosService(session)
    r = abonado_en_corte(servicio, red, "192.168.103.137", "47000007", date(2026, 10, 1))
    servicio.registrar_pago_abonado(r.cliente.id, PagoCrear(monto=50, medio_pago="Efectivo"), hoy=HOY)
    ruteador = RuteadorSimulado()

    despachar(controlador(session, ruteador))

    assert ruteador.recibidas == []
    assert r.orden.estado == "ANULADO"
