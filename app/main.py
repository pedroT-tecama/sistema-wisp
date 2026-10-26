"""Punto de arranque del sistema.

Qué hace:
    Crea la aplicación web (FastAPI) y le agrega todas las rutas (endpoints)
    que el operador puede usar desde la documentación interactiva (/docs).

Cómo se ejecuta:
    uvicorn app.main:app --reload
    ("app.main" es este archivo y "app" es la variable creada abajo).

Con qué se relaciona:
    - app/routers/abonados.py : rutas de abonados (registro, búsqueda, ficha).
    - app/database.py         : conexión con MySQL, usada por /salud/db.
    - Archivo .env            : credenciales de los ruteadores (MK_USER, MK_PASS, MK_PORT).
"""
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from librouteros import connect
from sqlalchemy import text

from app.database import engine
from app.routers import abonados

load_dotenv()                          # carga las variables del archivo .env
app = FastAPI(title="Sistema WISP")    # aplicación web; uvicorn la pone en marcha
app.include_router(abonados.router)    # agrega las rutas /abonados (HU-01, HU-02, HU-03)


@app.get("/")
def inicio():
    """Responde un mensaje simple para comprobar que el servidor está encendido."""
    return {"mensaje": "Sistema WISP funcionando"}


@app.get("/routers/{ip}/info")
def info_router(ip: str):
    """Prueba de conexión con un ruteador MikroTik a través de su API.

    Recibe la IP del ruteador, se conecta con las credenciales del .env y
    devuelve la versión de RouterOS, el modelo del equipo y sus interfaces.
    Si el ruteador no responde, devuelve el código 502.
    """
    try:
        api = connect(
            host=ip,
            username=os.getenv("MK_USER"),
            password=os.getenv("MK_PASS"),
            port=int(os.getenv("MK_PORT", "8728")),
            timeout=5,                      # segundos de espera antes de dar el equipo por inaccesible
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo conectar: {e}")

    try:
        res = list(api.path("system", "resource"))[0]   # /system resource: versión y modelo
        interfaces = [                                    # /interface: nombre, tipo y estado de cada puerto
            {"nombre": i["name"], "tipo": i["type"], "activa": i["running"]}
            for i in api.path("interface")
        ]
    finally:
        api.close()                         # la conexión se cierra siempre, aunque haya error

    return {"version": res["version"], "placa": res["board-name"], "interfaces": interfaces}


@app.get("/salud/db")
def salud_db():
    """Comprueba la conexión con MySQL.

    Devuelve la versión de MySQL y la lista de tablas de la base configurada
    en DB_URL (deben ser las 9 del Anexo H). Si no hay conexión, devuelve 503.
    """
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
            tablas = [fila[0] for fila in conn.execute(text("SHOW TABLES"))]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Sin conexión con la base de datos: {e}")
    return {"mysql": version, "total_tablas": len(tablas), "tablas": tablas}
