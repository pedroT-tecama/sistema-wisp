"""Script de prueba de conexión con la API de RouterOS (actividad A7 del Anexo I).

Qué hace:
    Se conecta a un ruteador MikroTik y muestra en pantalla su versión de
    RouterOS, su modelo y el estado de sus interfaces. Sirve para comprobar
    que el equipo de desarrollo llega a un ruteador antes de usar el sistema.

Uso (desde la carpeta del proyecto):
    python scripts/prueba_conexion.py IP [PUERTO]
    python scripts/prueba_conexion.py 192.168.5.20

Con qué se relaciona:
    - Archivo .env : credenciales MK_USER, MK_PASS y el puerto MK_PORT (8728 por defecto).
    - Es independiente del sistema: no usa la base de datos ni la aplicación web.
"""
import os
import sys

from dotenv import load_dotenv
from librouteros import connect

load_dotenv()

if len(sys.argv) < 2:
    sys.exit("Uso: python scripts/prueba_conexion.py IP [PUERTO]")

host = sys.argv[1]                                    # IP del ruteador (primer parámetro)
puerto = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.getenv("MK_PORT", "8728"))

api = connect(
    host=host,
    username=os.getenv("MK_USER"),
    password=os.getenv("MK_PASS"),
    port=puerto,
    timeout=5,                                        # segundos de espera antes de dar el equipo por inaccesible
)

# Versión de RouterOS y modelo del equipo (/system resource)
for r in api.path("system", "resource"):
    print("RouterOS:", r["version"], "| Placa:", r["board-name"])

# Interfaces del equipo y si están activas (/interface)
for i in api.path("interface"):
    print(i["name"], "-", i["type"], "- activa:", i["running"])

api.close()
