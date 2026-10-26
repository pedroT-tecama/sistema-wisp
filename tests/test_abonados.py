"""Pruebas unitarias del registro y la búsqueda de abonados (sección 6.7).

Qué prueba:
    - Regla del primer vencimiento: registro + 1 día, estado ACTIVO.
    - PU-01: IP única por ruteador (rechazada en el mismo ruteador, aceptada en otro distrito).
    - PU-02: integridad referencial (rechaza ruteador o plan inexistente).
    - PU-08: búsqueda por apellidos (sin mayúsculas ni tildes, en orden) y por DNI.

Cómo se ejecuta (desde la carpeta del proyecto):
    python -m pytest -v

Con qué se relaciona:
    - Prueba app/services/abonados.py (GestionAbonadosService).
    - Usa las preparaciones "session" y "red" de tests/conftest.py (base wisp_test).
"""
from datetime import date

import pytest

from app.schemas import AbonadoCrear
from app.services.abonados import GestionAbonadosService, IpDuplicada, RecursoNoEncontrado


def abonado(router_id, plan_id, ip, apellidos="Pérez Quispe", dni="40123456", **extra):
    """Arma los datos de un abonado de prueba registrado el 26/10/2026."""
    datos = dict(nombres="Juan", apellidos=apellidos, dni=dni, direccion="Jr. Prueba 123",
                 ip_cliente=ip, router_id=router_id, tarifa_id=plan_id,
                 fecha_registro=date(2026, 10, 26))
    datos.update(extra)
    return AbonadoCrear(**datos)


# ------------------------------------------------------------ regla del periodo
def test_primer_vencimiento_es_el_dia_siguiente(session, red):
    """Registrado el 26/10, su servicio y su primer vencimiento son el 27/10."""
    servicio = GestionAbonadosService(session)
    cliente = servicio.registrar_cliente_nuevo(abonado(red["router_a"], red["plan"], "192.168.103.101"))
    assert cliente.fecha_vencimiento == date(2026, 10, 27)
    assert cliente.estado == "ACTIVO"
    assert cliente.saldo_dias_favor == 0


# ------------------------------------------------------------ PU-01
def test_pu01_ip_repetida_en_el_mismo_ruteador_es_rechazada(session, red):
    """Dos abonados con la misma IP en el mismo ruteador: el segundo es rechazado."""
    servicio = GestionAbonadosService(session)
    servicio.registrar_cliente_nuevo(abonado(red["router_a"], red["plan"], "192.168.103.101"))
    with pytest.raises(IpDuplicada):
        servicio.registrar_cliente_nuevo(
            abonado(red["router_a"], red["plan"], "192.168.103.101", dni="40999999")
        )


def test_pu01_misma_ip_en_distritos_distintos_es_aceptada(session, red):
    """La misma IP en ruteadores de distritos distintos: ambos registros se aceptan."""
    servicio = GestionAbonadosService(session)
    uno = servicio.registrar_cliente_nuevo(abonado(red["router_a"], red["plan"], "192.168.103.101"))
    dos = servicio.registrar_cliente_nuevo(
        abonado(red["router_b"], red["plan"], "192.168.103.101", dni="40999999")
    )
    assert uno.id != dos.id


# ------------------------------------------------------------ PU-02
def test_pu02_ruteador_inexistente_es_rechazado(session, red):
    """Un abonado asociado a un ruteador que no existe no se registra."""
    servicio = GestionAbonadosService(session)
    with pytest.raises(RecursoNoEncontrado):
        servicio.registrar_cliente_nuevo(abonado(999999, red["plan"], "192.168.103.101"))


def test_pu02_plan_inexistente_es_rechazado(session, red):
    """Un abonado asociado a un plan que no existe no se registra."""
    servicio = GestionAbonadosService(session)
    with pytest.raises(RecursoNoEncontrado):
        servicio.registrar_cliente_nuevo(abonado(red["router_a"], 999999, "192.168.103.101"))


# ------------------------------------------------------------ PU-08
def test_pu08_busqueda_por_apellidos_sin_mayusculas_ni_tildes(session, red):
    """Buscar "perez" encuentra Pérez y PEREZ en cualquier posición, en orden alfabético."""
    servicio = GestionAbonadosService(session)
    r, p = red["router_a"], red["plan"]
    servicio.registrar_cliente_nuevo(abonado(r, p, "192.168.103.101", apellidos="Pérez Quispe", dni="40000001"))
    servicio.registrar_cliente_nuevo(abonado(r, p, "192.168.103.102", apellidos="PEREZ Mamani", dni="40000002"))
    servicio.registrar_cliente_nuevo(abonado(r, p, "192.168.103.103", apellidos="Gómez Pérez", dni="40000003"))
    servicio.registrar_cliente_nuevo(abonado(r, p, "192.168.103.104", apellidos="Quispe Huanca", dni="40000004"))

    resultado = [c.apellidos for c in servicio.buscar_abonados("perez")]

    assert resultado == ["Gómez Pérez", "PEREZ Mamani", "Pérez Quispe"]


def test_pu08_busqueda_por_dni_retorna_todos_los_servicios_del_titular(session, red):
    """Un titular con dos servicios: buscar su DNI devuelve los dos y ninguno ajeno."""
    servicio = GestionAbonadosService(session)
    r, p = red["router_a"], red["plan"]
    servicio.registrar_cliente_nuevo(abonado(r, p, "192.168.103.101", dni="40123456"))
    servicio.registrar_cliente_nuevo(abonado(r, p, "192.168.104.101", dni="40123456"))
    servicio.registrar_cliente_nuevo(abonado(r, p, "192.168.103.105", dni="41111111", apellidos="Otro Titular"))

    resultado = servicio.buscar_abonados("40123456")

    assert len(resultado) == 2
    assert {c.ip_cliente for c in resultado} == {"192.168.103.101", "192.168.104.101"}
