"""Drivers por versión de RouterOS: RouterOSDriver, RouterOSv6Driver y RouterOSv7Driver (Anexo G, clases 11 y 12).

Qué hace:
    RouterOSDriver es la clase base abstracta. Implementa una sola vez lo que
    es igual en RouterOS 6 y 7: buscar la cola simple de un abonado por su IP,
    aplicarle el corte (límite 1k/1k) y restablecerle las velocidades de su
    plan. Declara como abstracto leer_rutas_ospf(), porque la tabla de rutas
    OSPF está organizada de forma distinta en cada versión; cada subclase lo
    implementa a su manera.

    Las colas simples se crean a mano en el ruteador al instalar al abonado
    (aprovisionamiento manual); el sistema solo cambia su límite (max-limit).
    El límite se escribe "subida/bajada", por ejemplo "4M/7M".

Con qué se relaciona:
    - Lo crea: app/hal/capa_hardware.py (obtener_driver, según la versión del ruteador).
    - Usa: app/hal/cliente_api.py (MikrotikAPIClient) para hablar con el ruteador.
    - Lo prueba: tests/test_hal.py.
"""
from abc import ABC, abstractmethod

from app.hal.cliente_api import MikrotikAPIClient

LIMITE_CORTE = "1k/1k"          # límite que deja al abonado sin servicio útil (HU-03)
MULTIPLICADORES = {"k": 1_000, "M": 1_000_000, "G": 1_000_000_000}


class ColaNoEncontrada(Exception):
    """El ruteador no tiene una cola simple para la IP del abonado."""


def a_bits_por_segundo(valor: str) -> int:
    """Convierte una velocidad de RouterOS a número: "4M" -> 4000000, "1k" -> 1000, "7000000" -> 7000000."""
    valor = str(valor).strip()
    if valor and valor[-1] in MULTIPLICADORES:
        return int(float(valor[:-1]) * MULTIPLICADORES[valor[-1]])
    return int(valor or 0)


def mismo_limite(limite_a: str, limite_b: str) -> bool:
    """Indica si dos límites "subida/bajada" son iguales, aunque estén escritos distinto ("1k/1k" y "1000/1000")."""
    a = [a_bits_por_segundo(x) for x in str(limite_a).split("/")]
    b = [a_bits_por_segundo(x) for x in str(limite_b).split("/")]
    return a == b


class RouterOSDriver(ABC):
    """Base de los drivers: operaciones sobre colas simples, comunes a RouterOS 6 y 7."""

    def __init__(self, api_client: MikrotikAPIClient):
        self._api_client = api_client       # conexión con el ruteador; la heredan ambas subclases

    @property
    def api_client(self) -> MikrotikAPIClient:
        """Conexión que usa el driver; HardwareAbstractionLayer la abre y la cierra."""
        return self._api_client

    async def consultar_cola(self, ip: str) -> dict:
        """Devuelve la cola simple cuyo target es la IP del abonado (nombre, target, max-limit, .id).

        El target puede tener máscara o varias direcciones ("192.168.103.101/32,..."); se compara solo la IP.
        """
        colas = await self._api_client.enviar_trama_binaria("/queue/simple/print")
        for cola in colas:
            ips = [t.strip().split("/")[0] for t in str(cola.get("target", "")).split(",")]
            if ip in ips:
                return cola
        raise ColaNoEncontrada(f"No existe una cola simple para la IP {ip}.")

    async def _fijar_limite(self, ip: str, limite: str) -> bool:
        """Fija el max-limit de la cola del abonado. Devuelve False si ya tenía ese límite (no hace cambios)."""
        cola = await self.consultar_cola(ip)
        if mismo_limite(cola.get("max-limit", ""), limite):
            return False
        await self._api_client.enviar_trama_binaria("/queue/simple/set", **{".id": cola[".id"], "max-limit": limite})
        return True

    async def inyectar_politica_corte_capa3(self, ip: str) -> bool:
        """Corte (HU-03): fija la cola del abonado en 1k/1k. Devuelve False si ya estaba cortado."""
        return await self._fijar_limite(ip, LIMITE_CORTE)

    async def inyectar_politica_reactivacion(self, ip: str, rate_upload: str, rate_download: str) -> bool:
        """Reactivación (HU-03): restablece en la cola las velocidades del plan. Devuelve False si ya las tenía."""
        return await self._fijar_limite(ip, f"{rate_upload}/{rate_download}")

    @abstractmethod
    async def leer_rutas_ospf(self) -> list[str]:
        """Devuelve las redes de destino aprendidas por OSPF; cada versión de RouterOS lo implementa distinto."""


class RouterOSv6Driver(RouterOSDriver):
    """Driver para RouterOS 6."""

    async def leer_rutas_ospf(self) -> list[str]:
        """En RouterOS 6, las rutas OSPF están en /ip/route con el indicador ospf."""
        rutas = await self._api_client.enviar_trama_binaria("/ip/route/print")
        return [r["dst-address"] for r in rutas if r.get("ospf") is True]


class RouterOSv7Driver(RouterOSDriver):
    """Driver para RouterOS 7."""

    async def leer_rutas_ospf(self) -> list[str]:
        """En RouterOS 7, las rutas de todos los protocolos están en /routing/route; se toman las de OSPF."""
        rutas = await self._api_client.enviar_trama_binaria("/routing/route/print")
        return [r["dst-address"] for r in rutas if r.get("ospf") is True]
