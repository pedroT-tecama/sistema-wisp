"""Prueba de conexión con la API de RouterOS (bloque del 19 de octubre).

Uso:  python scripts/prueba_conexion.py IP [PUERTO]
      python scripts/prueba_conexion.py 192.168.5.20
Las credenciales se leen del archivo .env (MK_USER, MK_PASS, MK_PORT).
"""
import os
import sys

from dotenv import load_dotenv
from librouteros import connect

load_dotenv()

if len(sys.argv) < 2:
    sys.exit("Uso: python scripts/prueba_conexion.py IP [PUERTO]")

host = sys.argv[1]
puerto = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.getenv("MK_PORT", "8728"))

api = connect(
    host=host,
    username=os.getenv("MK_USER"),
    password=os.getenv("MK_PASS"),
    port=puerto,
    timeout=5,
)

# Versión de RouterOS
for r in api.path("system", "resource"):
    print("RouterOS:", r["version"], "| Placa:", r["board-name"])

# Interfaces
for i in api.path("interface"):
    print(i["name"], "-", i["type"], "- activa:", i["running"])

api.close()
