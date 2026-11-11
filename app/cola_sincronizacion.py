"""Cola de órdenes: clase ControladorColaSincronizacion (Anexo G, capa 2).

Qué hace:
    Toma las órdenes PENDIENTE de la tabla tarea_pendiente_red y las aplica en
    los ruteadores a través de la Capa de Abstracción de Hardware:
        - CORTE      -> la cola simple del abonado queda en 1k/1k.
        - ACTIVACION -> la cola simple recupera las velocidades del plan.
    Si el ruteador aplica la orden, la marca PROCESADO y actualiza al abonado:
        - CORTE      -> SUSPENDIDO, con la fecha del corte (fecha_corte_efectivo)
                        y los días pagados que no usó (saldo_dias_favor).
        - ACTIVACION -> ACTIVO, si estaba SUSPENDIDO. La orden de alta (abonado
                        recién registrado) solo deja la cola con las velocidades del plan.
    Si el ruteador no responde, la orden sigue PENDIENTE, se cuenta el intento
    y se vuelve a intentar en la siguiente vuelta. No hay un máximo de
    reintentos: la orden espera hasta que el ruteador vuelva (consistencia eventual).

Reglas del despacho:
    - De cada abonado se toma solo su orden más antigua: así un CORTE y una
      ACTIVACION del mismo abonado se aplican en el orden en que se crearon.
    - Las órdenes de abonados distintos se aplican a la vez (de forma
      concurrente), hasta COLA_CONCURRENCIA a la vez.
    - Si el abonado pagó mientras su corte se estaba aplicando, la orden ya
      figura ANULADO al confirmar: el corte quedó aplicado en el ruteador, por
      lo que se encola de inmediato su reactivación.

Configuración (archivo .env):
    COLA_CONCURRENCIA : órdenes que se aplican a la vez (5 por defecto).

Con qué se relaciona:
    - Lo pone en marcha: app/tareas.py (cada COLA_INTERVALO_SEGUNDOS) y la ruta
      POST /ordenes/despachar de app/routers/ordenes.py.
    - Llama a: app/hal/capa_hardware.py (suspender_ancho_banda, reactivar_ancho_banda),
      único camino hacia los ruteadores.
    - Lee y guarda en: app/models.py (TareaPendienteRed, Cliente, RouterNode).
    - Usa: app/services/periodo.py (días a favor) y app/services/abonados.py
      (orden de reactivación cuando el pago llega durante un corte).
    - Lo prueba: tests/test_cola.py.
"""
import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Callable, Optional

from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.hal.capa_hardware import HardwareAbstractionLayer
from app.hal.cliente_api import ErrorComandoRouter, ErrorConexionRouter
from app.hal.drivers import ColaNoEncontrada
from app.models import Cliente, RouterNode, TareaPendienteRed
from app.services.abonados import GestionAbonadosService
from app.services.periodo import CalculadorPeriodoComercial

load_dotenv()
log = logging.getLogger("uvicorn.error")            # los mensajes salen en la consola de uvicorn
COLA_CONCURRENCIA = int(os.getenv("COLA_CONCURRENCIA", "5"))


@dataclass
class OrdenADespachar:
    """Copia de una orden con lo necesario para aplicarla, sin depender de la sesión de base de datos."""

    id: int
    cliente_id: int
    accion: str
    ip: str
    rate_upload: str
    rate_download: str
    router: SimpleNamespace          # datos de conexión del ruteador (IP, puertos, versión, cabecera)


@dataclass
class ResumenDespacho:
    """Resultado de una vuelta de la cola: qué órdenes se aplicaron y cuáles quedaron pendientes."""

    lote: int
    procesadas: list[int] = field(default_factory=list)
    pendientes: list[int] = field(default_factory=list)
    reactivaciones_por_pago: list[int] = field(default_factory=list)


class ControladorColaSincronizacion:
    """Aplica en los ruteadores las órdenes pendientes y actualiza el estado de los abonados."""

    def __init__(self, sesion: Callable = SessionLocal, hal: Optional[HardwareAbstractionLayer] = None):
        """sesion: fábrica de sesiones de base de datos; hal: puerta de entrada a los ruteadores.

        Ambos se pueden reemplazar en las pruebas (base de pruebas y ruteador simulado).
        """
        self._sesion = sesion
        self._hal = hal or HardwareAbstractionLayer()
        self.id_lote_comercial = 0           # número de la vuelta en curso (aparece en los mensajes)
        self.ultimo_id_confirmado = 0        # última orden aplicada con éxito

    # ------------------------------------------------------------ despacho
    async def despachar_comandos_cola_tareas(self, hoy: Optional[date] = None) -> ResumenDespacho:
        """Una vuelta de la cola: toma las órdenes pendientes, las aplica a la vez y confirma cada resultado."""
        self.id_lote_comercial += 1
        resumen = ResumenDespacho(lote=self.id_lote_comercial)
        ordenes = await asyncio.to_thread(self._tomar_ordenes)   # la lectura de la base no detiene al sistema
        limite = asyncio.Semaphore(COLA_CONCURRENCIA)

        async def atender(orden: OrdenADespachar):
            async with limite:
                aplicada = await self._aplicar_en_ruteador(orden)
            resultado = await asyncio.to_thread(self._confirmar, orden, aplicada, hoy or date.today())
            if resultado == "PROCESADO":
                resumen.procesadas.append(orden.id)
            elif resultado == "REACTIVACION_POR_PAGO":
                resumen.reactivaciones_por_pago.append(orden.id)
            else:
                resumen.pendientes.append(orden.id)

        await asyncio.gather(*(atender(o) for o in ordenes))
        return resumen

    def _tomar_ordenes(self) -> list[OrdenADespachar]:
        """Lee las órdenes PENDIENTE y devuelve la más antigua de cada abonado, con los datos de su ruteador."""
        with self._sesion() as s:
            pendientes = s.scalars(
                select(TareaPendienteRed).where(TareaPendienteRed.estado == "PENDIENTE").order_by(TareaPendienteRed.id)
            ).all()
            primeras, vistos = [], set()
            for orden in pendientes:
                if orden.cliente_id not in vistos:         # solo la primera orden de cada abonado
                    vistos.add(orden.cliente_id)
                    primeras.append(orden)
            routers = {r.id: r for r in s.scalars(
                select(RouterNode).options(joinedload(RouterNode.master))
                .where(RouterNode.id.in_({o.router_id for o in primeras}))
            ).unique()}
            return [self._copiar(o, routers[o.router_id]) for o in primeras]

    @staticmethod
    def _copiar(orden: TareaPendienteRed, router: RouterNode) -> OrdenADespachar:
        """Copia la orden y los datos de conexión de su ruteador para usarlos fuera de la sesión."""
        p = orden.payload_parametros_red
        destino = SimpleNamespace(
            nombre_equipo=router.nombre_equipo, ip_router=router.ip_router,
            puerto_socket=router.puerto_socket, version_routeros=router.version_routeros,
            master=SimpleNamespace(ddns_url=router.master.ddns_url, puerto_base=router.master.puerto_base),
        )
        return OrdenADespachar(orden.id, orden.cliente_id, orden.accion, p["ip_cliente"],
                               p.get("rate_upload", ""), p.get("rate_download", ""), destino)

    async def _aplicar_en_ruteador(self, orden: OrdenADespachar) -> bool:
        """Aplica la orden en el ruteador. Devuelve False si el equipo no responde o no la acepta."""
        try:
            if orden.accion == "CORTE":
                await self._hal.suspender_ancho_banda(orden.router, orden.ip)
            else:
                await self._hal.reactivar_ancho_banda(orden.router, orden.ip, orden.rate_upload, orden.rate_download)
            return True
        except (ErrorConexionRouter, ErrorComandoRouter, ColaNoEncontrada) as error:
            log.warning("Orden %s (%s %s) queda pendiente en %s: %s",
                        orden.id, orden.accion, orden.ip, orden.router.nombre_equipo, error)
            return False

    def _confirmar(self, orden: OrdenADespachar, aplicada: bool, hoy: date) -> str:
        """Guarda el resultado de la orden y, si se aplicó, el nuevo estado del abonado (una sola transacción).

        Devuelve PROCESADO, PENDIENTE o REACTIVACION_POR_PAGO.
        """
        with self._sesion() as s:
            try:
                fila = s.get(TareaPendienteRed, orden.id, with_for_update=True)    # bloquea la orden mientras se confirma
                cliente = s.get(Cliente, orden.cliente_id, with_for_update=True,
                                options=[joinedload(Cliente.tarifa)])
                fila.intentos += 1
                if not aplicada:
                    resultado = "PENDIENTE"
                elif fila.estado == "ANULADO":
                    # El abonado pagó mientras se aplicaba el corte: el ruteador ya lo cortó,
                    # así que se encola su reactivación con las velocidades de su plan.
                    GestionAbonadosService(s)._registrar_orden_activacion(cliente)
                    resultado = "REACTIVACION_POR_PAGO"
                else:
                    fila.estado = "PROCESADO"
                    if orden.accion == "CORTE":
                        cliente.estado = "SUSPENDIDO"
                        cliente.fecha_corte_efectivo = hoy
                        cliente.saldo_dias_favor = CalculadorPeriodoComercial.calcular_saldo_dias_favor(
                            cliente.fecha_vencimiento, hoy)
                    elif cliente.estado == "SUSPENDIDO":
                        cliente.estado = "ACTIVO"       # una orden de alta no cambia el estado del abonado
                    self.ultimo_id_confirmado = max(self.ultimo_id_confirmado, orden.id)
                    resultado = "PROCESADO"
                s.commit()
            except Exception:
                s.rollback()
                raise
        if resultado != "PENDIENTE":
            log.info("Orden %s (%s %s) aplicada en %s: %s",
                     orden.id, orden.accion, orden.ip, orden.router.nombre_equipo, resultado)
        return resultado

    # ------------------------------------------------------------ arranque
    async def autosanar_lotes_por_corte_energia(self) -> int:
        """Al encender el sistema: recupera la última orden aplicada y retoma las pendientes.

        Las órdenes se guardan en la base de datos, por lo que un apagado o un
        corte de energía no las pierde: las que quedaron PENDIENTE se aplican en
        la primera vuelta. Devuelve cuántas órdenes estaban pendientes.
        """
        def leer():
            with self._sesion() as s:
                ultimo = s.scalar(select(func.max(TareaPendienteRed.id)).where(TareaPendienteRed.estado == "PROCESADO"))
                pendientes = s.scalar(select(func.count()).select_from(TareaPendienteRed)
                                      .where(TareaPendienteRed.estado == "PENDIENTE"))
                return ultimo or 0, pendientes
        self.ultimo_id_confirmado, pendientes = await asyncio.to_thread(leer)
        log.info("Cola de órdenes: última orden aplicada %s; %s orden(es) pendiente(s) por retomar.",
                 self.ultimo_id_confirmado, pendientes)
        return pendientes
