"""Puerta de entrada a los ruteadores: clase HardwareAbstractionLayer (Anexo G, clase 10).

Qué hace:
    Recibe un pedido (cortar, reactivar o consultar las rutas OSPF), elige el
    driver según la versión de RouterOS del ruteador, abre la conexión, ejecuta
    la operación y cierra la conexión, aunque la operación falle. Así, quien
    la usa no necesita saber si el equipo tiene RouterOS 6 o 7.

A qué dirección se conecta (MK_MODO_CONEXION en el archivo .env):
    - "directo" (por defecto): a la IP de gestión del ruteador (ip_gestion_ospf)
      y al puerto de la API (MK_PORT, 8728). Se usa cuando el equipo central
      llega a los ruteadores por rutas, como en la red del caso de estudio.
    - "cabecera": a la dirección de la cabecera del distrito (ddns_url) y al
      puerto asignado al ruteador (puerto_socket), que la cabecera redirige
      al equipo mediante mapeo de puertos (diseño de la sección 5.3).

Con qué se relaciona:
    - La usará: el proceso ControladorColaSincronizacion (siguiente bloque),
      único componente que pide cambios en los ruteadores.
    - Usa: app/hal/drivers.py y app/hal/cliente_api.py.
    - Lee de: app/models.py (RouterNode y RouterMaster: IP, puertos y versión).
    - Lo prueba: tests/test_hal.py; prueba manual: scripts/prueba_hal.py.
"""
import os

from dotenv import load_dotenv

from app.hal.cliente_api import MikrotikAPIClient
from app.hal.drivers import RouterOSDriver, RouterOSv6Driver, RouterOSv7Driver
from app.models import RouterMaster, RouterNode

load_dotenv()
MODO_CONEXION = os.getenv("MK_MODO_CONEXION", "directo")
PUERTO_API = int(os.getenv("MK_PORT", "8728"))


class HardwareAbstractionLayer:
    """Ejecuta las operaciones sobre los ruteadores sin depender de su versión de RouterOS."""

    @staticmethod
    def _version_mayor(version: str | None) -> int:
        """Primer número de la versión: "7.21.4" -> 7. Si no está registrada, se asume 6."""
        try:
            return int(str(version).split(".")[0])
        except ValueError:
            return 6

    def obtener_driver(self, router: RouterNode | RouterMaster) -> RouterOSDriver:
        """Método fábrica: devuelve un RouterOSv7Driver o un RouterOSv6Driver según la versión del ruteador."""
        clase = RouterOSv7Driver if self._version_mayor(router.version_routeros) >= 7 else RouterOSv6Driver
        return clase(MikrotikAPIClient())

    @staticmethod
    def direccion_de(router: RouterNode | RouterMaster) -> tuple[str, int]:
        """Devuelve (host, puerto) del ruteador según MK_MODO_CONEXION."""
        if isinstance(router, RouterMaster):
            return router.ddns_url, (PUERTO_API if MODO_CONEXION == "directo" else router.puerto_base)
        if MODO_CONEXION == "directo":
            return router.ip_gestion_ospf, PUERTO_API
        return router.master.ddns_url, router.puerto_socket

    async def _ejecutar(self, router, operacion):
        """Conecta, ejecuta operacion(driver) y cierra la conexión siempre, aunque la operación falle."""
        driver = self.obtener_driver(router)
        host, puerto = self.direccion_de(router)
        try:
            await driver.api_client.conectar_socket(host, puerto)
            return await operacion(driver)
        finally:
            await driver.api_client.cerrar_y_purgar_socket()

    async def suspender_ancho_banda(self, router: RouterNode, ip: str) -> bool:
        """Corta al abonado: su cola queda en 1k/1k. Devuelve False si ya estaba cortado."""
        return await self._ejecutar(router, lambda d: d.inyectar_politica_corte_capa3(ip))

    async def reactivar_ancho_banda(self, router: RouterNode, ip: str, upload: str, download: str) -> bool:
        """Reactiva al abonado con las velocidades de su plan. Devuelve False si ya las tenía."""
        return await self._ejecutar(router, lambda d: d.inyectar_politica_reactivacion(ip, upload, download))

    async def consultar_cola(self, router: RouterNode, ip: str) -> dict:
        """Devuelve la cola simple del abonado tal como está en el ruteador (para verificar)."""
        return await self._ejecutar(router, lambda d: d.consultar_cola(ip))

    async def consultar_rutas_ospf(self, master: RouterMaster) -> list[str]:
        """Devuelve las rutas OSPF de la cabecera del distrito (se usará en el monitoreo)."""
        return await self._ejecutar(master, lambda d: d.leer_rutas_ospf())
