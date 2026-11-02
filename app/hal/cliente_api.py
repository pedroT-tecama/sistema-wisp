"""Conexión con la API de RouterOS: clase MikrotikAPIClient (Anexo G, clase 13).

Qué hace:
    Abre la conexión TCP con un ruteador MikroTik, envía comandos de la API
    de RouterOS y devuelve las respuestas como listas de diccionarios de
    Python. Las operaciones son asíncronas: mientras espera la respuesta de un
    ruteador, el sistema puede seguir atendiendo otras tareas.

    Si el ruteador no responde dentro del tiempo de espera (MK_TIMEOUT), o
    rechaza el usuario, se lanza ErrorConexionRouter. Si el ruteador responde
    con un error a un comando, se lanza ErrorComandoRouter.

Configuración (archivo .env, nunca en el código):
    MK_USER, MK_PASS : usuario y clave del grupo de la API (permisos limitados).
    MK_TIMEOUT       : segundos de espera por conexión (5 por defecto).

Con qué se relaciona:
    - Lo usa: app/hal/drivers.py (cada driver tiene su propio cliente).
    - Lo crea: app/hal/capa_hardware.py (HardwareAbstractionLayer.obtener_driver).
    - Usa la biblioteca librouteros (versión fijada en requirements.txt).
"""
import asyncio
import os

from dotenv import load_dotenv
from librouteros import async_connect
from librouteros.exceptions import LibRouterosError, TrapError

load_dotenv()
MK_TIMEOUT = float(os.getenv("MK_TIMEOUT", "5"))


class ErrorConexionRouter(Exception):
    """El ruteador no responde, no es accesible o rechazó el usuario. La orden debe reintentarse."""


class ErrorComandoRouter(Exception):
    """El ruteador respondió con un error al comando enviado."""


class MikrotikAPIClient:
    """Conexión asíncrona con un ruteador mediante la API de RouterOS."""

    def __init__(self, usuario: str | None = None, clave: str | None = None, timeout: float | None = None):
        """Toma el usuario, la clave y el tiempo de espera del archivo .env, salvo que se indiquen otros."""
        self._usuario = usuario or os.getenv("MK_USER")
        self._clave = clave or os.getenv("MK_PASS")
        self._timeout = timeout or MK_TIMEOUT
        self._api = None            # conexión abierta; None mientras no se conecte

    async def conectar_socket(self, host: str, puerto: int) -> None:
        """Abre la conexión con el ruteador e inicia sesión con el usuario de la API."""
        try:
            self._api = await async_connect(
                host=host, username=self._usuario, password=self._clave,
                port=puerto, timeout=self._timeout,
            )
        except (OSError, asyncio.TimeoutError, LibRouterosError) as error:
            raise ErrorConexionRouter(f"No se pudo conectar con {host}:{puerto} ({error})") from error

    async def enviar_trama_binaria(self, cmd: str, **parametros) -> list[dict]:
        """Envía un comando de la API (ej. "/queue/simple/print") y devuelve las filas de la respuesta.

        Los parámetros se envían como atributos del comando, por ejemplo:
        enviar_trama_binaria("/queue/simple/set", **{".id": "*1A", "max-limit": "1k/1k"}).
        """
        if self._api is None:
            raise ErrorConexionRouter("No hay conexión abierta con el ruteador.")
        try:
            return [fila async for fila in self._api(cmd, **parametros)]
        except TrapError as error:
            raise ErrorComandoRouter(f"El ruteador rechazó {cmd}: {error}") from error
        except (OSError, asyncio.TimeoutError, LibRouterosError) as error:
            raise ErrorConexionRouter(f"Se perdió la conexión al ejecutar {cmd} ({error})") from error

    async def cerrar_y_purgar_socket(self) -> None:
        """Cierra la conexión y libera sus recursos; no falla si ya estaba cerrada."""
        if self._api is not None:
            try:
                await self._api.close()
            except Exception:
                pass                # la conexión ya estaba caída; solo se libera la referencia
            self._api = None
