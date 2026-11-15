"""Pruebas unitarias del monitoreo de conectividad (MotorTelemetriaProactiva; HU-04, HU-05).

Qué prueba:
    - Con todas las banderas en la tabla de la cabecera, ningún ruteador cae ni se registran alertas.
    - Una sola consulta sin bandera no basta: hacen falta MONITOREO_LECTURAS seguidas (2 en las pruebas).
    - Si cae un ruteador intermedio, caen él y los que cuelgan de él; la alerta del inferior indica la cascada.
    - Mientras dura la caída no se repiten las alertas.
    - Cuando la bandera reaparece, el ruteador vuelve a CHECK_OK y su alerta se cierra.
    - Si la cabecera no responde, se registra CABECERA_INACCESIBLE y no se cambian los estados;
      cuando vuelve a responder, la alerta se cierra.
    - RouterNode distingue al ruteador conectado a la cabecera del que depende de otro ruteador (cascada).
    - Correo de alerta: uno solo por vuelta (la cascada va en el mismo correo), otro al restablecerse,
      otro si la cabecera no responde, ninguno si no hay cambios; si el correo falla, el monitoreo sigue.

Cómo se prueba sin red:
    CabeceraSimulada reemplaza a HardwareAbstractionLayer y devuelve la tabla de
    rutas que cada prueba indica, o simula que la cabecera no responde.
    CorreoSimulado reemplaza a NotificadorCorreo: guarda los correos en lugar de enviarlos. La base
    es wisp_test, con la preparación "session" de tests/conftest.py.

    Red de prueba (como el distrito del caso de estudio):
        Cabecera (raíz) -> Torre 6 -> Torre 3 -> Torre 5,   y Cabecera -> AP

Con qué se relaciona:
    - Prueba app/monitoreo.py (MotorTelemetriaProactiva) y su uso de app/notificador.py.
"""
import asyncio
from contextlib import nullcontext

import pytest
from sqlalchemy import select

from app.hal.cliente_api import ErrorConexionRouter
from app.models import RegistroAlerta, RouterMaster, RouterNode
from app.monitoreo import MotorTelemetriaProactiva

BANDERAS = {"torre6": "10.250.0.6", "torre3": "10.250.0.3", "torre5": "10.250.0.5", "ap": "10.250.0.14"}


class CabeceraSimulada:
    """Reemplazo de HardwareAbstractionLayer: devuelve la tabla de rutas indicada o simula que no responde."""

    def __init__(self):
        self.rutas = []
        self.responde = True

    async def consultar_rutas_ospf(self, cabecera):
        if not self.responde:
            raise ErrorConexionRouter("la cabecera no responde (simulado)")
        return self.rutas


class CorreoSimulado:
    """Reemplazo de NotificadorCorreo: guarda (asunto, cuerpo) de cada correo o simula que el envío falla."""

    def __init__(self, falla=False):
        self.activo = True
        self.falla = falla
        self.enviados = []

    def enviar(self, asunto, cuerpo):
        if self.falla:
            raise OSError("el servidor de correo no responde (simulado)")
        self.enviados.append((asunto, cuerpo))


@pytest.fixture
def distrito(session):
    """Distrito de prueba: cabecera (raíz), Torre 6 -> Torre 3 -> Torre 5 y un AP, cada uno con su bandera."""
    master = RouterMaster(nombre_distrito="Distrito Monitoreo", ddns_url="10.250.0.1", puerto_base=8001)
    session.add(master)
    session.flush()

    def ruteador(nombre, ip, puerto, padre=None, bandera=None):
        r = RouterNode(master_id=master.id, padre_id=padre, nombre_equipo=nombre, tipo_nodo="ROUTER",
                       ip_router=ip, ip_gestion_ospf=bandera, puerto_socket=puerto, version_routeros="7.20.4")
        session.add(r)
        session.flush()
        return r

    cabecera = ruteador("Cabecera Prueba", "192.0.2.1", 8001)
    torre6 = ruteador("Torre 6 Prueba", "192.0.2.33", 8006, cabecera.id, BANDERAS["torre6"])
    torre3 = ruteador("Torre 3 Prueba", "198.51.100.2", 8003, torre6.id, BANDERAS["torre3"])
    torre5 = ruteador("Torre 5 Prueba", "198.51.100.4", 8004, torre3.id, BANDERAS["torre5"])
    ap = ruteador("AP Prueba", "192.0.2.14", 8005, cabecera.id, BANDERAS["ap"])
    session.commit()
    return {"master": master, "torre6": torre6, "torre3": torre3, "torre5": torre5, "ap": ap}


def motor(session, cabecera, correo=None):
    """Motor con la sesión de prueba (sin cerrarla), la cabecera simulada, 2 lecturas y un correo simulado."""
    return MotorTelemetriaProactiva(sesion=lambda: nullcontext(session), hal=cabecera, lecturas=2,
                                    correo=correo or CorreoSimulado())


def tabla(*nombres):
    """Tabla de rutas OSPF de la cabecera con las banderas indicadas (y una red de enlace, que no es bandera)."""
    return [f"{BANDERAS[n]}/32" for n in nombres] + ["192.168.108.0/24"]


def evaluar(m):
    return asyncio.run(m.ejecutar_monitoreo_distrital())


def alertas(session, **origen):
    consulta = select(RegistroAlerta)
    for columna, valor in origen.items():
        consulta = consulta.where(getattr(RegistroAlerta, columna) == valor)
    return session.scalars(consulta).all()


# ------------------------------------------------------------ todo en orden
def test_todas_las_banderas_presentes(session, distrito):
    """Con las cuatro banderas en la tabla, nadie cae y no hay alertas."""
    cabecera = CabeceraSimulada()
    cabecera.rutas = tabla("torre6", "torre3", "torre5", "ap")

    r = evaluar(motor(session, cabecera))

    assert (r.caidos, r.restablecidos) == ([], [])
    assert all(distrito[n].estado_operativo == "CHECK_OK" for n in ("torre6", "torre3", "torre5", "ap"))
    assert alertas(session, master_id=distrito["master"].id) == []


# ------------------------------------------------------------ posición en el árbol
def test_posicion_del_ruteador_en_el_arbol(session, distrito):
    """Torre 6 y el AP cuelgan de la cabecera; Torre 3 y Torre 5 dependen de otro ruteador (cascada)."""
    for n in ("torre6", "ap"):
        assert distrito[n].es_hijo_directo_del_master() and not distrito[n].es_nodo_en_cascada()
    for n in ("torre3", "torre5"):
        assert distrito[n].es_nodo_en_cascada() and not distrito[n].es_hijo_directo_del_master()


# ------------------------------------------------------------ caída en cascada
def test_una_sola_consulta_sin_bandera_no_basta(session, distrito):
    """La primera consulta sin la bandera no marca la caída: hacen falta dos seguidas."""
    cabecera = CabeceraSimulada()
    cabecera.rutas = tabla("torre6", "torre5", "ap")                # falta Torre 3 una vez
    r = evaluar(motor(session, cabecera))
    assert r.caidos == []
    assert distrito["torre3"].estado_operativo == "CHECK_OK"


def test_caida_en_cascada(session, distrito):
    """Cae Torre 3: en la segunda consulta caen Torre 3 y Torre 5; la alerta de Torre 5 indica la cascada."""
    cabecera = CabeceraSimulada()
    cabecera.rutas = tabla("torre6", "ap")                          # sin Torre 3 ni Torre 5
    m = motor(session, cabecera)
    evaluar(m)
    r = evaluar(m)

    assert sorted(r.caidos) == sorted([distrito["torre3"].id, distrito["torre5"].id])
    assert distrito["torre3"].estado_operativo == "NODO_CAIDO"
    assert distrito["torre5"].estado_operativo == "NODO_CAIDO"
    assert distrito["torre6"].estado_operativo == "CHECK_OK"
    alerta_t5 = alertas(session, router_id=distrito["torre5"].id)
    assert len(alerta_t5) == 1 and alerta_t5[0].prefijo_excepcion == "OSPF_RUTA_AUSENTE"
    assert "cascada" in alerta_t5[0].descripcion_error and "Torre 3 Prueba" in alerta_t5[0].descripcion_error


def test_no_repite_alertas_mientras_dura_la_caida(session, distrito):
    """Cinco consultas sin la bandera del AP: una sola alerta."""
    cabecera = CabeceraSimulada()
    cabecera.rutas = tabla("torre6", "torre3", "torre5")
    m = motor(session, cabecera)
    for _ in range(5):
        evaluar(m)
    assert len(alertas(session, router_id=distrito["ap"].id)) == 1


# ------------------------------------------------------------ restablecimiento
def test_restablecimiento_cierra_la_alerta(session, distrito):
    """Cuando la bandera reaparece, el ruteador vuelve a CHECK_OK y su alerta queda resuelta."""
    cabecera = CabeceraSimulada()
    m = motor(session, cabecera)
    cabecera.rutas = tabla("torre6", "torre3", "torre5")            # el AP cae
    evaluar(m)
    evaluar(m)
    cabecera.rutas = tabla("torre6", "torre3", "torre5", "ap")      # el AP vuelve
    r = evaluar(m)

    assert r.restablecidos == [distrito["ap"].id]
    assert distrito["ap"].estado_operativo == "CHECK_OK"
    alerta = alertas(session, router_id=distrito["ap"].id)[0]
    assert alerta.fecha_resolucion is not None


# ------------------------------------------------------------ cabecera sin respuesta
def test_cabecera_sin_respuesta(session, distrito):
    """Si la cabecera no responde, se registra CABECERA_INACCESIBLE sin cambiar estados; al volver, se cierra."""
    cabecera = CabeceraSimulada()
    cabecera.responde = False
    m = motor(session, cabecera)
    evaluar(m)
    r = evaluar(m)

    assert r.cabeceras_sin_respuesta == [distrito["master"].id]
    assert r.caidos == []
    assert all(distrito[n].estado_operativo == "CHECK_OK" for n in ("torre6", "torre3", "torre5", "ap"))
    sin_respuesta = alertas(session, master_id=distrito["master"].id)
    assert len(sin_respuesta) == 1 and sin_respuesta[0].prefijo_excepcion == "CABECERA_INACCESIBLE"

    cabecera.responde = True
    cabecera.rutas = tabla("torre6", "torre3", "torre5", "ap")
    evaluar(m)
    assert alertas(session, master_id=distrito["master"].id)[0].fecha_resolucion is not None


# ------------------------------------------------------------ correo de alerta
def test_correo_unico_por_vuelta_con_la_cascada(session, distrito):
    """Caen Torre 3 y Torre 5 en la misma vuelta: un solo correo con las dos fallas; sin cambios, no hay correo."""
    cabecera, correo = CabeceraSimulada(), CorreoSimulado()
    cabecera.rutas = tabla("torre6", "ap")
    m = motor(session, cabecera, correo)
    evaluar(m)
    assert correo.enviados == []                                    # primera ausencia: aún no hay alerta
    evaluar(m)
    assert len(correo.enviados) == 1
    asunto, cuerpo = correo.enviados[0]
    assert "ALERTA: 2 falla(s)" in asunto
    assert "Torre 3 Prueba" in cuerpo and "Torre 5 Prueba" in cuerpo and "cascada" in cuerpo
    evaluar(m)
    assert len(correo.enviados) == 1                                # la caída sigue: no se repite


def test_correo_de_restablecimiento(session, distrito):
    """Cuando el AP vuelve, llega un correo de restablecimiento."""
    cabecera, correo = CabeceraSimulada(), CorreoSimulado()
    m = motor(session, cabecera, correo)
    cabecera.rutas = tabla("torre6", "torre3", "torre5")
    evaluar(m)
    evaluar(m)
    cabecera.rutas = tabla("torre6", "torre3", "torre5", "ap")
    evaluar(m)
    asunto, cuerpo = correo.enviados[-1]
    assert "Restablecido" in asunto and "AP Prueba" in cuerpo


def test_correo_por_cabecera_sin_respuesta(session, distrito):
    """La cabecera no responde: un correo con CABECERA_INACCESIBLE; al volver, otro de restablecimiento."""
    cabecera, correo = CabeceraSimulada(), CorreoSimulado()
    cabecera.responde = False
    m = motor(session, cabecera, correo)
    evaluar(m)
    evaluar(m)
    assert len(correo.enviados) == 1 and "Cabecera Prueba" in correo.enviados[0][1]
    cabecera.responde = True
    cabecera.rutas = tabla("torre6", "torre3", "torre5", "ap")
    evaluar(m)
    assert len(correo.enviados) == 2 and "volvió a responder" in correo.enviados[1][1]


def test_correo_fallido_no_detiene_el_monitoreo(session, distrito):
    """Si el correo falla, la caída igual se registra en la base."""
    cabecera = CabeceraSimulada()
    cabecera.rutas = tabla("torre6", "torre3", "torre5")
    m = motor(session, cabecera, CorreoSimulado(falla=True))
    evaluar(m)
    r = evaluar(m)
    assert r.caidos == [distrito["ap"].id]
    assert len(alertas(session, router_id=distrito["ap"].id)) == 1
