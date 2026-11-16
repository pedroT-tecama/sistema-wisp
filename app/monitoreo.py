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
    Enlaces troncales (HU-05): en cada vuelta se lee la señal (RSSI) de la antena
    receptora de cada enlace punto a punto del distrito y se guarda en el
    historial. Si SENAL_LECTURAS lecturas seguidas quedan por debajo del umbral
    del enlace, se registra una alerta PTP_DEGRADADO; cuando la señal vuelve a
    estar sobre el umbral, la alerta se cierra. Las lecturas más antiguas que
    SENAL_DIAS_HISTORICO se borran.
    La señal se lee antes de comparar las banderas: si un ruteador cae y la
    antena del enlace que lo conecta tampoco respondió en esa vuelta, su alerta
    indica la probable caída del radioenlace. Una antena sin respuesta, con su
    ruteador en servicio, no es una caída: solo se anota en la consola.
    Al final de cada vuelta se envía un solo correo con las alertas nuevas y
    las resueltas (disparar_alerta_critica); si no hubo cambios, no se envía nada.

Configuración (archivo .env):
    MONITOREO_LECTURAS   : consultas seguidas sin bandera para declarar la caída (2 por defecto).
    SENAL_LECTURAS       : lecturas seguidas bajo el umbral para alertar un enlace degradado (3 por defecto).
    SENAL_DIAS_HISTORICO : días que se conservan las lecturas de señal (30 por defecto).

Con qué se relaciona:
    - Lo pone en marcha: app/tareas.py (cada MONITOREO_INTERVALO_SEGUNDOS) y la
      ruta POST /monitoreo/evaluar de app/routers/monitoreo.py.
    - Llama a: app/hal/capa_hardware.py (consultar_rutas_ospf), que lee la tabla
      de la cabecera según su versión de RouterOS, y consultar_senal_enlace, que
      lee la señal en la antena receptora de cada enlace troncal.
    - Llama a: app/notificador.py (NotificadorCorreo) para el correo de alerta.
    - Lee y guarda en: app/models.py (RouterNode, RouterMaster, RegistroAlerta, Cliente,
      EnlaceBackhaulPTP, LecturaSenalEnlace).
    - Lo prueba: tests/test_monitoreo.py.
"""
import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Callable, Optional

from dotenv import load_dotenv
from sqlalchemy import delete, func, select

from app.database import SessionLocal
from app.hal.capa_hardware import HardwareAbstractionLayer
from app.hal.cliente_api import ErrorComandoRouter, ErrorConexionRouter
from app.hal.drivers import SenalNoDisponible
from app.models import (Cliente, EnlaceBackhaulPTP, LecturaSenalEnlace, RegistroAlerta, RouterMaster,
                        RouterNode)
from app.notificador import NotificadorCorreo

load_dotenv()
log = logging.getLogger("uvicorn.error")            # los mensajes salen en la consola de uvicorn
LECTURAS = int(os.getenv("MONITOREO_LECTURAS", "2"))
SENAL_LECTURAS = int(os.getenv("SENAL_LECTURAS", "3"))
SENAL_DIAS_HISTORICO = int(os.getenv("SENAL_DIAS_HISTORICO", "30"))


@dataclass
class ResultadoMonitoreo:
    """Resultado de una vuelta del monitoreo: qué ruteadores cayeron, cuáles volvieron y qué cabeceras no respondieron."""

    vuelta: int
    caidos: list[int] = field(default_factory=list)
    restablecidos: list[int] = field(default_factory=list)
    cabeceras_sin_respuesta: list[int] = field(default_factory=list)
    enlaces_degradados: list[int] = field(default_factory=list)


class MotorTelemetriaProactiva:
    """Compara las banderas OSPF de los ruteadores registrados con la tabla de rutas de cada cabecera."""

    def __init__(self, sesion: Callable = SessionLocal, hal: Optional[HardwareAbstractionLayer] = None,
                 lecturas: int = LECTURAS, correo=None, lecturas_senal: int = SENAL_LECTURAS):
        """sesion: fábrica de sesiones; hal: acceso a los ruteadores; lecturas: consultas seguidas para
        declarar la caída; correo: quien envía el correo de alerta; lecturas_senal: lecturas seguidas
        bajo el umbral para declarar un enlace degradado.

        sesion, hal y correo se pueden reemplazar en las pruebas (base de pruebas, cabecera y correo simulados).
        """
        self._sesion = sesion
        self._hal = hal or HardwareAbstractionLayer()
        self._correo = correo or NotificadorCorreo()
        self._nuevas: list[str] = []             # alertas registradas en la vuelta (van al correo)
        self._resueltas: list[str] = []          # alertas cerradas en la vuelta (van al correo)
        self.lecturas_senal = lecturas_senal
        self._antenas_sin_respuesta: set[int] = set()   # enlaces cuya antena no respondió (se avisa una vez)
        self._sin_lectura: set[int] = set()             # enlaces sin lectura en la vuelta en curso
        self._ultima_purga: Optional[datetime] = None   # última limpieza del historial de lecturas
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
        self._sin_lectura = set()
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
            resultado.enlaces_degradados += await self.evaluar_senal_enlaces(cabecera.master_id)   # antes del OSPF
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
        """Registra la alerta OSPF_RUTA_AUSENTE del ruteador, si no tiene una abierta, con su cascada y abonados afectados.

        Si no cae en cascada y la antena del enlace que lo conecta no respondió en esta vuelta,
        agrega la probable caída del radioenlace.
        """
        if self._alerta_abierta(s, router_id=r.id):
            return
        abonados = s.scalar(select(func.count()).select_from(Cliente).where(Cliente.router_id == r.id))
        texto = (f"{r.nombre_equipo} ({r.ip_router}) sin ruta OSPF hacia su bandera {r.ip_gestion_ospf}/32 "
                 f"durante {self.lecturas_para_alertar} consultas: el ruteador o su enlace no responde.")
        cascada = r.es_nodo_en_cascada() and r.padre.estado_operativo == "NODO_CAIDO"   # la falla viene de arriba
        if cascada:
            texto += f" Cae en cascada: su ruteador superior, {r.padre.nombre_equipo}, también está caído."
        elif r.es_nodo_en_cascada():
            texto += f" Ruteador superior: {r.padre.nombre_equipo}."
        elif r.es_hijo_directo_del_master():
            texto += f" Se conecta directamente a la cabecera ({r.padre.nombre_equipo})."
        enlace = s.scalars(select(EnlaceBackhaulPTP).where(EnlaceBackhaulPTP.router_destino_id == r.id)).first()
        if not cascada and enlace is not None and enlace.id in self._sin_lectura:
            texto += (f" Probable caída del radioenlace {enlace.nombre_enlace}: "
                      f"su antena {enlace.ip_antena_destino} tampoco responde.")
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

    # ------------------------------------------------------------ enlaces troncales
    async def evaluar_senal_enlaces(self, master_id: int) -> list[int]:
        """Evaluación de la señal de los enlaces troncales del distrito (HU-05).

        Lee a la vez la señal de la antena receptora de cada enlace, la guarda en
        LecturaSenalEnlace y aplica la regla de las SENAL_LECTURAS lecturas seguidas.
        Devuelve los id de los enlaces con alerta PTP_DEGRADADO nueva.
        Lo llama ejecutar_monitoreo_distrital en cada vuelta.
        """
        enlaces = await asyncio.to_thread(self._leer_enlaces, master_id)
        if not enlaces:
            return []
        lecturas = await asyncio.gather(*(self._leer_senal(e) for e in enlaces))   # todas las antenas a la vez
        return await asyncio.to_thread(self._registrar_lecturas, enlaces, lecturas)

    def _leer_enlaces(self, master_id: int) -> list[SimpleNamespace]:
        """Devuelve los enlaces troncales del distrito (su ruteador de origen es del distrito)."""
        with self._sesion() as s:
            enlaces = s.scalars(select(EnlaceBackhaulPTP).join(EnlaceBackhaulPTP.origen)
                                .where(RouterNode.master_id == master_id).order_by(EnlaceBackhaulPTP.id)).all()
            return [SimpleNamespace(id=e.id, nombre_enlace=e.nombre_enlace, ip_antena_destino=e.ip_antena_destino)
                    for e in enlaces]

    async def _leer_senal(self, enlace: SimpleNamespace) -> Optional[int]:
        """Lee la señal del enlace; si la antena no responde devuelve None y lo avisa una sola vez en la consola."""
        try:
            rssi = await self._hal.consultar_senal_enlace(enlace)
        except (ErrorConexionRouter, ErrorComandoRouter, SenalNoDisponible, OSError) as error:
            self._sin_lectura.add(enlace.id)               # lo usa la alerta OSPF de su ruteador en esta vuelta
            if enlace.id not in self._antenas_sin_respuesta:
                self._antenas_sin_respuesta.add(enlace.id)
                log.warning("Monitoreo, vuelta %s: no se pudo leer la señal del enlace %s (%s): %s",
                            self.vuelta, enlace.nombre_enlace, enlace.ip_antena_destino, error)
            return None
        if enlace.id in self._antenas_sin_respuesta:
            self._antenas_sin_respuesta.discard(enlace.id)
            log.info("Monitoreo, vuelta %s: la antena del enlace %s volvió a responder.", self.vuelta, enlace.nombre_enlace)
        return rssi

    def _registrar_lecturas(self, enlaces: list[SimpleNamespace], lecturas: list[Optional[int]]) -> list[int]:
        """Guarda las lecturas, registra o cierra las alertas PTP_DEGRADADO y limpia el historial antiguo."""
        degradados = []
        ahora = datetime.now()
        with self._sesion() as s:
            try:
                for datos, rssi in zip(enlaces, lecturas):
                    if rssi is None:                       # antena sin respuesta: no hay lectura que guardar
                        continue
                    enlace = s.get(EnlaceBackhaulPTP, datos.id)
                    s.add(LecturaSenalEnlace(enlace_id=enlace.id, rssi_medido=rssi, fecha_hora=ahora))
                    s.flush()
                    ultimas = s.scalars(select(LecturaSenalEnlace.rssi_medido)
                                        .where(LecturaSenalEnlace.enlace_id == enlace.id)
                                        .order_by(LecturaSenalEnlace.id.desc()).limit(self.lecturas_senal)).all()
                    if enlace.senal_degradada(rssi):
                        confirmada = (len(ultimas) == self.lecturas_senal
                                      and all(enlace.senal_degradada(x) for x in ultimas))
                        if confirmada and not self._alerta_abierta(s, enlace_id=enlace.id):
                            texto = (f"Enlace troncal {enlace.nombre_enlace} con señal de {rssi} dBm, por debajo "
                                     f"del mínimo esperado de {enlace.rssi_minimo_esperado} dBm durante "
                                     f"{self.lecturas_senal} lecturas seguidas (antena {enlace.ip_antena_destino}).")
                            s.add(RegistroAlerta(prefijo_excepcion="PTP_DEGRADADO", enlace_id=enlace.id,
                                                 descripcion_error=texto[:500], fecha_registro=ahora))
                            self._nuevas.append(texto)
                            degradados.append(enlace.id)
                            log.warning("Monitoreo, vuelta %s: %s", self.vuelta, texto)
                    elif self._cerrar_alertas(s, ahora, enlace_id=enlace.id):
                        texto = (f"Enlace troncal {enlace.nombre_enlace} recuperó su señal: {rssi} dBm "
                                 f"(mínimo esperado {enlace.rssi_minimo_esperado} dBm).")
                        self._resueltas.append(texto)
                        log.info("Monitoreo, vuelta %s: %s", self.vuelta, texto)
                self._purgar_historial(s, ahora)
                s.commit()
            except Exception:
                s.rollback()
                raise
        return degradados

    def _purgar_historial(self, s, ahora: datetime):
        """Borra, como máximo una vez por hora, las lecturas más antiguas que SENAL_DIAS_HISTORICO."""
        if self._ultima_purga and ahora - self._ultima_purga < timedelta(hours=1):
            return
        s.execute(delete(LecturaSenalEnlace).where(
            LecturaSenalEnlace.fecha_hora < ahora - timedelta(days=SENAL_DIAS_HISTORICO)))
        self._ultima_purga = ahora

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
