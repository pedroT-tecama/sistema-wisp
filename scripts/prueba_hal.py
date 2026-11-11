"""Prueba manual de la Capa de Abstracción de Hardware sobre un ruteador real.

Qué hace:
    Busca el ruteador en la base de operación (wisp_db) por su IP de gestión y,
    a través de HardwareAbstractionLayer, consulta, corta o reactiva la cola
    simple de una IP de prueba. Sirve para verificar en Winbox que el sistema
    cambia la cola sin intervención manual, antes de construir la cola de órdenes.

Uso (desde la carpeta del proyecto, con el entorno virtual activo):
    python -m scripts.prueba_hal ver       192.168.103.101
    python -m scripts.prueba_hal cortar    192.168.103.101
    python -m scripts.prueba_hal reactivar 192.168.103.101 4M 7M
    Opcional: --router 192.168.5.43 (es el valor por defecto: Condominio 1 - E7)

Importante:
    Usar solo IP ficticias con su cola de prueba creada a mano en el ruteador.
    No modifica la base de datos: solo la lee para obtener el ruteador.

Con qué se relaciona:
    - Llama a: app/hal/capa_hardware.py (HardwareAbstractionLayer).
    - Lee: app/models.py (RouterNode) mediante app/database.py (SessionLocal).
    - Credenciales: MK_USER y MK_PASS del archivo .env.
"""
import argparse
import asyncio

from sqlalchemy import select

from app.database import SessionLocal
from app.hal.capa_hardware import HardwareAbstractionLayer
from app.models import RouterNode


def mostrar(cola: dict) -> None:
    """Imprime los datos principales de la cola simple."""
    print(f"  Cola: {cola.get('name')} | target: {cola.get('target')} | max-limit: {cola.get('max-limit')}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Prueba de la Capa de Abstracción de Hardware")
    parser.add_argument("accion", choices=["ver", "cortar", "reactivar"])
    parser.add_argument("ip_abonado")
    parser.add_argument("subida", nargs="?", help="velocidad de subida del plan, ej. 4M (solo reactivar)")
    parser.add_argument("bajada", nargs="?", help="velocidad de bajada del plan, ej. 7M (solo reactivar)")
    parser.add_argument("--router", default="192.168.5.43", help="IP de gestión del ruteador")
    args = parser.parse_args()

    with SessionLocal() as session:
        router = session.scalars(select(RouterNode).where(RouterNode.ip_router == args.router)).first()
        if router is None:
            raise SystemExit(f"El ruteador {args.router} no está registrado en la base de datos.")
        session.expunge(router)          # se usa fuera de la sesión; solo se leen sus datos

    hal = HardwareAbstractionLayer()
    print(f"Ruteador: {router.nombre_equipo} ({router.ip_router}, RouterOS {router.version_routeros})")
    print(f"Driver: {type(hal.obtener_driver(router)).__name__}")

    if args.accion == "cortar":
        cambio = await hal.suspender_ancho_banda(router, args.ip_abonado)
        print("Corte aplicado (1k/1k)." if cambio else "Sin cambios: la cola ya estaba cortada.")
    elif args.accion == "reactivar":
        if not (args.subida and args.bajada):
            raise SystemExit("Para reactivar indique subida y bajada, ej.: reactivar 192.168.103.101 4M 7M")
        cambio = await hal.reactivar_ancho_banda(router, args.ip_abonado, args.subida, args.bajada)
        print("Reactivación aplicada." if cambio else "Sin cambios: la cola ya tenía esas velocidades.")

    mostrar(await hal.consultar_cola(router, args.ip_abonado))   # estado final, para comparar con Winbox


if __name__ == "__main__":
    asyncio.run(main())
