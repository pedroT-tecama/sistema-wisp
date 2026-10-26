import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from librouteros import connect
from sqlalchemy import text

from app.database import engine

load_dotenv()                          # lee el archivo .env
app = FastAPI(title="Sistema WISP")    # como una app de Spring Boot

@app.get("/")                          # como @GetMapping("/")
def inicio():
    return {"mensaje": "Sistema WISP funcionando"}

@app.get("/routers/{ip}/info")         # como @GetMapping("/routers/{ip}/info")
def info_router(ip: str):              # como @PathVariable String ip
    try:
        api = connect(
            host=ip,
            username=os.getenv("MK_USER"),
            password=os.getenv("MK_PASS"),
            port=int(os.getenv("MK_PORT", "8728")),
            timeout=5,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo conectar: {e}")

    try:
        res = list(api.path("system", "resource"))[0]
        interfaces = [
            {"nombre": i["name"], "tipo": i["type"], "activa": i["running"]}
            for i in api.path("interface")
        ]
    finally:
        api.close()

    return {"version": res["version"], "placa": res["board-name"], "interfaces": interfaces}


@app.get("/salud/db")                  # verifica la conexión con MySQL
def salud_db():
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
            tablas = [fila[0] for fila in conn.execute(text("SHOW TABLES"))]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Sin conexión con la base de datos: {e}")
    return {"mysql": version, "total_tablas": len(tablas), "tablas": tablas}
