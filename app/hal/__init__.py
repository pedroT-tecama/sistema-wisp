"""Capa de Abstracción de Hardware (Anexo G, capa 3).

Es la única parte del sistema que se comunica con los ruteadores MikroTik.
Contiene:
    - cliente_api.py    : MikrotikAPIClient, la conexión con la API de RouterOS.
    - drivers.py        : RouterOSDriver y sus subclases RouterOSv6Driver y RouterOSv7Driver.
    - capa_hardware.py  : HardwareAbstractionLayer, la puerta de entrada que usan los procesos.
"""
