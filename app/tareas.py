"""Tareas automáticas que corren en segundo plano mientras el sistema está encendido.

Qué hace:
    - Suspensión diaria por vencimiento (HU-03): una vez al día ejecuta
      GestionAbonadosService.procesar_vencimientos(), que pasa a
      PENDIENTE_SUSPENSION a los abonados que superaron su plazo de gracia y
      encola sus órdenes de corte. La primera revisión se hace al encender el
      sistema y luego se repite cada SUSPENSION_INTERVALO_HORAS (24 por defecto).
    - Se puede desactivar con SUSPENSION_AUTOMATICA=0 en el archivo .env.

Cómo funciona:
    El sistema web atiende solicitudes de forma asíncrona. Para no detenerlo
    mientras se consulta la base de datos, la revisión se ejecuta en un hilo
    aparte (asyncio.to_thread) y luego la tarea espera hasta la siguiente vez.

Con qué se relaciona:
    - Lo arranca: app/main.py, al encender el sistema.
    - Llama a: app/services/abonados.py (procesar_vencimientos).
    - Usa: app/database.py (SessionLocal) para abrir su propia sesión.
"""
import asyncio
import logging
import os

from dotenv import load_dotenv

from app.database import SessionLocal
from app.services.abonados import GestionAbonadosService

load_dotenv()
log = logging.getLogger("uvicorn.error")      # los mensajes salen en la misma consola de uvicorn

SUSPENSION_AUTOMATICA = os.getenv("SUSPENSION_AUTOMATICA", "1") == "1"
INTERVALO_HORAS = float(os.getenv("SUSPENSION_INTERVALO_HORAS", "24"))


def revisar_vencimientos() -> int:
    """Ejecuta una revisión de vencimientos con su propia sesión y devuelve cuántos abonados se suspendieron."""
    with SessionLocal() as session:
        resultados = GestionAbonadosService(session).procesar_vencimientos()
        for r in resultados:
            log.info("Suspensión por vencimiento: abonado %s (orden de corte %s)", r.cliente.id, r.orden.id)
        return len(resultados)


async def ciclo_suspension_diaria():
    """Repite la revisión de vencimientos cada INTERVALO_HORAS mientras el sistema esté encendido."""
    while True:
        try:
            total = await asyncio.to_thread(revisar_vencimientos)
            log.info("Revisión de vencimientos terminada: %s abonado(s) suspendido(s).", total)
        except Exception as error:                  # un error no detiene la tarea; se reintenta en la siguiente vuelta
            log.error("Error en la revisión de vencimientos: %s", error)
        await asyncio.sleep(INTERVALO_HORAS * 3600)
