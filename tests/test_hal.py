"""Pruebas unitarias de la Capa de Abstracción de Hardware, sin ruteador real.

Qué prueba:
    - El método fábrica elige el driver según la versión de RouterOS.
    - El corte fija la cola del abonado en 1k/1k y no repite el cambio si ya estaba cortado.
    - La reactivación restablece las velocidades del plan.
    - Se identifica la cola aunque el target tenga máscara o varias direcciones.
    - Una IP sin cola simple es rechazada.
    - La dirección de conexión según el modo (directo o por la cabecera).

Cómo se prueba sin ruteador:
    RuteadorSimulado reemplaza a MikrotikAPIClient: guarda las colas en memoria
    y responde a los comandos /queue/simple/print y /queue/simple/set como lo
    haría la API de RouterOS. Así se verifica la lógica de los drivers sin
    depender de la red. La prueba sobre el ruteador real se hace con
    scripts/prueba_hal.py.

Con qué se relaciona:
    - Prueba app/hal/drivers.py y app/hal/capa_hardware.py.
    - No usa la base de datos ni las preparaciones de tests/conftest.py.
"""
import asyncio

import pytest

from app.hal import capa_hardware
from app.hal.capa_hardware import HardwareAbstractionLayer
from app.hal.drivers import ColaNoEncontrada, RouterOSv6Driver, RouterOSv7Driver, mismo_limite
from app.models import RouterMaster, RouterNode


class RuteadorSimulado:
    """Reemplazo de MikrotikAPIClient: colas simples en memoria y registro de los comandos 'set' recibidos."""

    def __init__(self, colas):
        self.colas = colas
        self.cambios = []           # cada /queue/simple/set recibido

    async def enviar_trama_binaria(self, cmd, **parametros):
        if cmd == "/queue/simple/print":
            return [dict(c) for c in self.colas]
        if cmd == "/queue/simple/set":
            self.cambios.append(parametros)
            for c in self.colas:
                if c[".id"] == parametros[".id"]:
                    c["max-limit"] = parametros["max-limit"]
            return []
        raise AssertionError(f"comando no esperado: {cmd}")


def colas_de_prueba():
    """Dos colas como las devuelve RouterOS: límites en bits por segundo y target con máscara."""
    return [
        {".id": "*1", "name": "prueba-103.101", "target": "192.168.103.101/32", "max-limit": "4000000/7000000"},
        {".id": "*2", "name": "prueba-103.102", "target": "192.168.103.150/32,192.168.103.102/32",
         "max-limit": "1000/1000"},
    ]


def test_fabrica_elige_driver_por_version():
    hal = HardwareAbstractionLayer()
    assert isinstance(hal.obtener_driver(RouterNode(version_routeros="7.21.4")), RouterOSv7Driver)
    assert isinstance(hal.obtener_driver(RouterNode(version_routeros="6.48.3")), RouterOSv6Driver)
    assert isinstance(hal.obtener_driver(RouterNode(version_routeros=None)), RouterOSv6Driver)


def test_corte_fija_1k_y_no_repite_el_cambio():
    ruteador = RuteadorSimulado(colas_de_prueba())
    driver = RouterOSv7Driver(ruteador)

    assert asyncio.run(driver.inyectar_politica_corte_capa3("192.168.103.101")) is True
    assert ruteador.cambios == [{".id": "*1", "max-limit": "1k/1k"}]
    assert asyncio.run(driver.inyectar_politica_corte_capa3("192.168.103.101")) is False   # ya estaba cortado
    assert len(ruteador.cambios) == 1


def test_reactivacion_restablece_velocidades_del_plan():
    ruteador = RuteadorSimulado(colas_de_prueba())
    driver = RouterOSv6Driver(ruteador)

    assert asyncio.run(driver.inyectar_politica_reactivacion("192.168.103.102", "4M", "7M")) is True
    assert ruteador.cambios == [{".id": "*2", "max-limit": "4M/7M"}]


def test_cola_con_varias_direcciones_en_el_target():
    driver = RouterOSv7Driver(RuteadorSimulado(colas_de_prueba()))
    cola = asyncio.run(driver.consultar_cola("192.168.103.102"))
    assert cola["name"] == "prueba-103.102"


def test_ip_sin_cola_es_rechazada():
    driver = RouterOSv7Driver(RuteadorSimulado(colas_de_prueba()))
    with pytest.raises(ColaNoEncontrada):
        asyncio.run(driver.inyectar_politica_corte_capa3("192.168.103.109"))


def test_limites_iguales_escritos_distinto():
    assert mismo_limite("1k/1k", "1000/1000")
    assert mismo_limite("4M/7M", "4000000/7000000")
    assert not mismo_limite("4M/7M", "1k/1k")


def test_direccion_segun_modo_de_conexion(monkeypatch):
    master = RouterMaster(ddns_url="cabecera.ejemplo.net", puerto_base=8001)
    router = RouterNode(ip_gestion_ospf="192.168.5.43", puerto_socket=8002, master=master)

    monkeypatch.setattr(capa_hardware, "MODO_CONEXION", "directo")
    assert HardwareAbstractionLayer.direccion_de(router) == ("192.168.5.43", capa_hardware.PUERTO_API)

    monkeypatch.setattr(capa_hardware, "MODO_CONEXION", "cabecera")
    assert HardwareAbstractionLayer.direccion_de(router) == ("cabecera.ejemplo.net", 8002)
