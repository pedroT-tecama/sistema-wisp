"""Monitoreo de conectividad: clase MotorTelemetriaProactiva (Anexo G; HU-04, HU-05).

Qué hace:
    Detecta los ruteadores de borde caídos comparando la tabla de rutas OSPF
    de la cabecera de cada distrito con los ruteadores registrados:
        - Cada ruteador anuncia en OSPF una bandera: una dirección /32 propia,
          configurada en un bridge sin puertos (columna ip_gestion_ospf).
        - Si la bandera de un ruteador falta en la tabla de la cabecera durante
          MONITOREO_LECTURAS consultas seguidas, el ruteador pasa a NODO_CAIDO
          y se registra una alerta OSPF_RUTA_AUSENTE (una sola mientras dure).
        - Cuando la bandera reaparece, el ruteador vuelve a CHECK_OK y la
          alerta se cierra con su fecha de resolución.
        - Si la cabecera no responde, se registra una alerta
          CABECERA_INACCESIBLE y no se cambia el estado de sus ruteadores,
          porque no se sabe si están caídos.
    La alerta indica la cascada: si el ruteador superior (padre_id) también
    está caído, la falla viene de más arriba. También indica cuántos abonados
    están afectados.
    Al final de cada vuelta se envía un solo correo con las alertas nuevas y
    las resueltas (disparar_alerta_critica); si no hubo cambios, no se envía nada.

Configuración (archivo .env):
    MONITOREO_LECTURAS : consultas seguidas sin bandera para declarar la caída (2 por defecto).

Con qué se relaciona:
    - Lo pone en marcha: app/tareas.py (cada MONITOREO_INTERVALO_SEGUNDOS) y la
      ruta POST /monitoreo/evaluar de app/routers/monitoreo.py.
    - Llama a: app/hal/capa_hardware.py (consultar_rutas_ospf), que lee la tabla
      de la cabecera según su versión de RouterOS.
    - Llama a: app/notificador.py (NotificadorCorreo) para el correo de alerta.
    - Lee y guarda en: app/models.py (RouterNode, RouterMaster, RegistroAlerta, Cliente).
    - Lo prueba: tests/test_monitoreo.py.
"""
import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Callable, Optional

from dotenv import load_dotenv
from sqlalchemy import func, select

from app.database import SessionLocal
from app.hal.capa_hardware import HardwareAbstractionLayer
from app.hal.cliente_api import ErrorComandoRouter, ErrorConexionRouter
from app.models import Cliente, RegistroAlerta, RouterMaster, RouterNode
from app.notificador import NotificadorCorreo

load_dotenv()
log = logging.getLogger("uvicorn.error")            # los mensajes salen en la consola de uvicorn
LECTURAS = int(os.getenv("MONITOREO_LECTURAS", "2"))


@dataclass
class ResultadoMonitoreo:
    """Resultado de una vuelta del monitoreo: qué ruteadores cayeron, cuáles volvieron y qué cabeceras no respondieron."""

    vuelta: int
    caidos: list[int] = field(default_factory=list)
    restablecidos: list[int] = field(default_factory=list)
    cabeceras_sin_respuesta: list[int] = field(default_factory=list)


class MotorTelemetriaProactiva:
    """Compara las banderas OSPF de los ruteadores registrados con la tabla de rutas de cada cabecera."""

    def __init__(self, sesion: Callable = SessionLocal, hal: Optional[HardwareAbstractionLayer] = None,
                 lecturas: int = LECTURAS, correo=None):
        """sesion: fábrica de sesiones; hal: acceso a los ruteadores; lecturas: consultas seguidas para
        declarar la caída; correo: quien envía el correo de alerta.

        sesion, hal y correo se pueden reemplazar en las pruebas (base de pruebas, cabecera y correo simulados).
        """
        self._sesion = sesion
        self._hal = hal or HardwareAbstractionLayer()
        self._correo = correo or NotificadorCorreo()
        self._nuevas: list[str] = []             # alertas registradas en la vuelta (van al correo)
        self._resueltas: list[str] = []          # alertas cerradas en la vuelta (van al correo)
        self.lecturas_para_alertar = lecturas
        self.ausencias: dict[int, int] = {}      # router_id -> consultas seguidas sin su bandera
        self.vuelta = 0                          # número de la vuelta en curso (aparece en los mensajes)

    # ------------------------------------------------------------ vuelta completa
    async def ejecutar_monitoreo_distrital(self, master_id: Optional[int] = None) -> ResultadoMonitoreo:
        """Una vuelta: lee la tabla de rutas de cada cabecera (o solo la del distrito indicado) y actualiza sus ruteadores.

        Incluye el restablecimiento: los ruteadores cuya bandera reaparece vuelven
        a CHECK_OK y sus alertas se cierran (cerrar_alertas_resueltas).
        """
        self.vuelta += 1
        resultado = ResultadoMonitoreo(vuelta=self.vuelta)
        self._nuevas, self._resueltas = [], []
        for cabecera in await asyncio.to_thread(self._leer_cabeceras):   # la base se lee sin detener al sistema
            if master_id is not None and cabecera.master_id != master_id:
                continue
            try:
                rutas = await self._hal.consultar_rutas_ospf(cabecera)
            except (ErrorConexionRouter, ErrorComandoRouter, OSError) as error:
                await asyncio.to_thread(self._cabecera_sin_respuesta, cabecera, str(error))
                resultado.cabeceras_sin_respuesta.append(cabecera.master_id)
                continue
            banderas = {r.split("/")[0] for r in rutas if r.endswith("/32")}   # solo las /32 son banderas
            caidos, restablecidos = await asyncio.to_thread(self._comparar, cabecera, banderas)
            resultado.caidos += caidos
            resultado.restablecidos += restablecidos
        await self.disparar_alerta_critica()     # un solo correo por vuelta, solo si hubo cambios
        return resultado

    def _leer_cabeceras(self) -> list[SimpleNamespace]:
        """Devuelve, por distrito, los datos de conexión de su cabecera (el nodo raíz de router_node)."""
        with self._sesion() as s:
            filas = s.execute(
                select(RouterNode, RouterMaster).join(RouterMaster, RouterNode.master_id == RouterMaster.id)
                .where(RouterNode.padre_id.is_(None))
            ).all()
            return [SimpleNamespace(
                master_id=m.id, nombre_distrito=m.nombre_distrito, nombre_equipo=r.nombre_equipo,
                ip_router=r.ip_router, puerto_socket=r.puerto_socket, version_routeros=r.version_routeros,
                master=SimpleNamespace(ddns_url=m.ddns_url, puerto_base=m.puerto_base),
            ) for r, m in filas]

    # ------------------------------------------------------------ comparación
    def _comparar(self, cabecera: SimpleNamespace, banderas: set[str]) -> tuple[list[int], list[int]]:
        """Primero restablece lo resuelto; luego cuenta las ausencias y marca NODO_CAIDO a quien llegue al límite."""
        caidos = []
        ahora = datetime.now()
        with self._sesion() as s:
            try:
                restablecidos = self.cerrar_alertas_resueltas(s, cabecera.master_id, banderas, ahora)
                ruteadores = s.scalars(select(RouterNode).where(
                    RouterNode.master_id == cabecera.master_id, RouterNode.ip_gestion_ospf.is_not(None))).all()
                for r in ruteadores:
                    if r.ip_gestion_ospf in banderas:
                        self.ausencias[r.id] = 0
                    else:
                        self.ausencias[r.id] = self.ausencias.get(r.id, 0) + 1
                        if self.ausencias[r.id] >= self.lecturas_para_alertar and r.estado_operativo == "CHECK_OK":
                            r.estado_operativo = "NODO_CAIDO"
                            caidos.append(r)
                s.flush()
                for r in caidos:                     # después de marcar a todos, para saber si el padre también cayó
                    self._registrar_alerta_ruteador(s, r, ahora)
                s.commit()
            except Exception:
                s.rollback()
                raise
        for r in caidos:
            log.warning("Monitoreo, vuelta %s: %s sin ruta OSPF (bandera %s): NODO_CAIDO.",
                        self.vuelta, r.nombre_equipo, r.ip_gestion_ospf)
        for rid in restablecidos:
            log.info("Monitoreo, vuelta %s: ruteador %s restablecido (CHECK_OK).", self.vuelta, rid)
        return [r.id for r in caidos], restablecidos

    def _registrar_alerta_ruteador(self, s, r: RouterNode, ahora: datetime):
        """Registra la alerta OSPF_RUTA_AUSENTE del ruteador, si no tiene una abierta, con su cascada y abonados afectados."""
        if self._alerta_abierta(s, router_id=r.id):
            return
        abonados = s.scalar(select(func.count()).select_from(Cliente).where(Cliente.router_id == r.id))
        texto = (f"{r.nombre_equipo} ({r.ip_router}) sin ruta OSPF hacia su bandera {r.ip_gestion_ospf}/32 "
                 f"durante {self.lecturas_para_alertar} consultas: el ruteador o su enlace no responde.")
        if r.es_nodo_en_cascada() and r.padre.estado_operativo == "NODO_CAIDO":
            texto += f" Cae en cascada: su ruteador superior, {r.padre.nombre_equipo}, también está caído."
        elif r.es_nodo_en_cascada():
            texto += f" Ruteador superior: {r.padre.nombre_equipo}."
        elif r.es_hijo_directo_del_master():
            texto += f" Se conecta directamente a la cabecera ({r.padre.nombre_equipo})."
        texto += f" Abonados afectados: {abonados}."
        s.add(RegistroAlerta(prefijo_excepcion="OSPF_RUTA_AUSENTE", router_id=r.id,
                             descripcion_error=texto[:500], fecha_registro=ahora))
        self._nuevas.append(texto)

    def _cabecera_sin_respuesta(self, cabecera: SimpleNamespace, error: str):
        """Registra la alerta CABECERA_INACCESIBLE del distrito, si no tiene una abierta."""
        with self._sesion() as s:
            try:
                if not self._alerta_abierta(s, master_id=cabecera.master_id):
                    texto = (f"La cabecera {cabecera.nombre_equipo} ({cabecera.nombre_distrito}) "
                             f"no responde: {error}")
                    s.add(RegistroAlerta(
                        prefijo_excepcion="CABECERA_INACCESIBLE", master_id=cabecera.master_id,
                        descripcion_error=texto[:500], fecha_registro=datetime.now()))
                    self._nuevas.append(texto)
                    log.warning("Monitoreo, vuelta %s: la cabecera %s no responde: %s",
                                self.vuelta, cabecera.nombre_equipo, error)
                s.commit()
            except Exception:
                s.rollback()
                raise

    # ------------------------------------------------------------ correo
    async def disparar_alerta_critica(self) -> bool:
        """Envía un solo correo con lo ocurrido en la vuelta: alertas nuevas y alertas resueltas.

        No envía nada si no hubo cambios o si el correo está apagado (ALERTA_CORREO).
        Si el envío falla, solo se anota en la consola: el monitoreo y las alertas de la base siguen igual.
        Lo llama ejecutar_monitoreo_distrital al final de cada vuelta; envía con app/notificador.py.
        """
        if not self._correo.activo or not (self._nuevas or self._resueltas):
            return False
        if self._nuevas:
            asunto = f"[Sistema WISP] ALERTA: {len(self._nuevas)} falla(s) detectada(s)"
        else:
            asunto = f"[Sistema WISP] Restablecido: {len(self._resueltas)} equipo(s) en servicio"
        lineas = [f"Monitoreo, vuelta {self.vuelta} ({datetime.now():%d/%m/%Y %H:%M:%S})", ""]
        if self._nuevas:
            lineas += ["Fallas detectadas:"] + [f"- {t}" for t in self._nuevas] + [""]
        if self._resueltas:
            lineas += ["Restablecidos:"] + [f"- {t}" for t in self._resueltas] + [""]
        lineas.append("Detalle de las alertas: GET /monitoreo/alertas.")
        try:
            await asyncio.to_thread(self._correo.enviar, asunto, "\n".join(lineas))   # el envío no detiene al sistema
            log.info("Monitoreo, vuelta %s: correo de alerta enviado.", self.vuelta)
            return True
        except Exception as error:               # un correo fallido no detiene el monitoreo
            log.error("Monitoreo, vuelta %s: no se pudo enviar el correo de alerta: %s", self.vuelta, error)
            return False

    # ------------------------------------------------------------ alertas
    def cerrar_alertas_resueltas(self, s, master_id: int, banderas: set[str], ahora: datetime) -> list[int]:
        """Restablecimiento del distrito: cierra las alertas cuyo problema ya se resolvió.

        - La cabecera respondió: se cierra su alerta CABECERA_INACCESIBLE, si tenía una.
        - Un ruteador NODO_CAIDO cuya bandera reapareció vuelve a CHECK_OK y se cierra su alerta.
        Devuelve los id de los ruteadores restablecidos.
        Lo llama _comparar en cada vuelta, dentro de la misma transacción.
        """
        if self._cerrar_alertas(s, ahora, master_id=master_id):
            distrito = s.get(RouterMaster, master_id)
            self._resueltas.append(f"La cabecera del distrito {distrito.nombre_distrito} volvió a responder.")
        restablecidos = []
        for r in s.scalars(select(RouterNode).where(
                RouterNode.master_id == master_id, RouterNode.estado_operativo == "NODO_CAIDO")).all():
            if r.ip_gestion_ospf in banderas:
                r.estado_operativo = "CHECK_OK"
                self._cerrar_alertas(s, ahora, router_id=r.id)
                restablecidos.append(r.id)
                self._resueltas.append(f"{r.nombre_equipo} ({r.ip_router}) volvió a tener ruta OSPF "
                                       f"hacia su bandera: CHECK_OK.")
        return restablecidos

    @staticmethod
    def _alerta_abierta(s, **origen) -> Optional[RegistroAlerta]:
        """Devuelve la alerta abierta del origen indicado (router_id= o master_id=), si existe."""
        consulta = select(RegistroAlerta).where(RegistroAlerta.fecha_resolucion.is_(None))
        for columna, valor in origen.items():
            consulta = consulta.where(getattr(RegistroAlerta, columna) == valor)
        return s.scalars(consulta).first()

    @staticmethod
    def _cerrar_alertas(s, ahora: datetime, **origen) -> list[RegistroAlerta]:
        """Registra la fecha de resolución en las alertas abiertas del origen indicado y las devuelve."""
        consulta = select(RegistroAlerta).where(RegistroAlerta.fecha_resolucion.is_(None))
        for columna, valor in origen.items():
            consulta = consulta.where(getattr(RegistroAlerta, columna) == valor)
        cerradas = s.scalars(consulta).all()
        for alerta in cerradas:
            alerta.fecha_resolucion = ahora
        return cerradas
