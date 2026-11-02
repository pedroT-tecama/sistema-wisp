"""Reglas de negocio de los abonados: clase GestionAbonadosService (Anexo G, capa 4).

Qué hace:
    Registra abonados nuevos, los busca por DNI o apellidos, entrega su ficha,
    registra sus pagos y los suspende (por vencimiento o por decisión del negocio). Aquí se aplican las reglas: que el ruteador y el plan
    existan, que la IP no se repita en el mismo ruteador, cuándo vence el primer
    pago y qué pasa con el vencimiento y las órdenes cuando el abonado paga.

Regla del periodo (prepago):
    - El servicio corre desde el día siguiente al registro (instalación).
    - fecha_registro guarda el día de la instalación como dato histórico.
    - fecha_vencimiento es el día en que vence el pago del periodo en curso.
      Al registrar, el primer periodo aún no está pagado: vence el día siguiente,
      y ese día del mes pasa a ser su día de pago (dia_pago).
    - El abonado tiene 10 días de gracia para pagar. El pago lo registra el
      servicio de pagos (HU-02), que calcula el siguiente vencimiento.
    Los cálculos de fechas están en app/services/periodo.py.

Con qué se relaciona:
    - Lo llaman: app/routers/abonados.py, app/routers/pagos.py y
      app/routers/suspensiones.py (endpoints), app/tareas.py (suspensión
      diaria automática) y los archivos de tests/ (pruebas).
    - Usa: app/models.py (tablas cliente, router_node, perfil_tarifa,
      caja_ingreso y tarea_pendiente_red), app/schemas.py (datos ya validados)
      y app/services/periodo.py (cálculo de vencimientos).
    - No se comunica con los ruteadores: por diseño (sección 6.3), solo crea o
      anula órdenes en la cola (tarea_pendiente_red); la Capa de Abstracción de
      Hardware es la única que accede a los equipos.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import CajaIngreso, Cliente, PerfilTarifa, RouterNode, TareaPendienteRed
from app.schemas import AbonadoCrear, PagoCrear
from app.services.periodo import CalculadorPeriodoComercial


# ------------------------------------------------------------ errores del negocio
class ErrorNegocio(Exception):
    """Error general de una regla de negocio. Los endpoints lo convierten en un código HTTP."""


class RecursoNoEncontrado(ErrorNegocio):
    """El ruteador, el plan o el abonado indicado no existe (PU-02). El endpoint responde 404."""


class EstadoNoPermitido(ErrorNegocio):
    """La operación no corresponde al estado actual del abonado (p. ej., suspender a uno ya suspendido). El endpoint responde 409."""


class IpDuplicada(ErrorNegocio):
    """La IP ya está asignada a otro abonado del mismo ruteador (PU-01). El endpoint responde 409."""


@dataclass
class ResultadoPago:
    """Lo que devuelve registrar_pago_abonado(): el pago guardado y qué pasó con las órdenes."""

    pago: CajaIngreso
    cliente: Cliente
    orden_generada: Optional[TareaPendienteRed] = None
    orden_anulada: Optional[TareaPendienteRed] = None


@dataclass
class ResultadoSuspension:
    """Abonado suspendido y orden de corte encolada por la suspensión."""

    cliente: Cliente
    orden: TareaPendienteRed


# ---------------------------------------------------------------- servicio
class GestionAbonadosService:
    """Operaciones sobre abonados: registrar, buscar y consultar la ficha.

    Recibe una sesión de base de datos al crearse; todas sus operaciones leen
    y guardan a través de esa sesión.
    """

    def __init__(self, session: Session):
        self.session = session

    # HU-01 -----------------------------------------------------------------
    def registrar_cliente_nuevo(self, datos: AbonadoCrear, hoy: Optional[date] = None) -> Cliente:
        """Registra la ficha de un abonado al concluir su instalación (HU-01).

        Pasos:
            1. Verifica que el ruteador y el plan existan (si no, RecursoNoEncontrado).
            2. Verifica que la IP no esté usada en el mismo ruteador (si lo está, IpDuplicada).
               La misma IP sí puede repetirse en ruteadores de otros distritos.
            3. Calcula el primer vencimiento (fecha de registro + 1 día); el día
               de ese vencimiento queda como su día de pago.
            4. Guarda el abonado con estado ACTIVO y lo devuelve.
        No envía órdenes al ruteador: la configuración inicial del equipo es manual.
        """
        ip = str(datos.ip_cliente)

        # 1. El ruteador y el plan deben existir
        if self.session.get(RouterNode, datos.router_id) is None:
            raise RecursoNoEncontrado(f"No existe el ruteador con id {datos.router_id}.")
        if self.session.get(PerfilTarifa, datos.tarifa_id) is None:
            raise RecursoNoEncontrado(f"No existe el plan con id {datos.tarifa_id}.")

        # 2. La IP no puede repetirse en el mismo ruteador
        repetido = self.session.scalar(
            select(Cliente.id).where(Cliente.router_id == datos.router_id, Cliente.ip_cliente == ip)
        )
        if repetido is not None:
            raise IpDuplicada(
                f"La IP {ip} ya está asignada al abonado {repetido} en este ruteador."
            )

        # 3. Primer vencimiento: el servicio empieza el día siguiente al registro
        fecha_registro = datos.fecha_registro or hoy or date.today()
        primer_vencimiento = CalculadorPeriodoComercial.primer_vencimiento(fecha_registro)
        cliente = Cliente(
            router_id=datos.router_id,
            tarifa_id=datos.tarifa_id,
            nombres=datos.nombres,
            apellidos=datos.apellidos,
            dni=datos.dni,
            direccion=datos.direccion,
            ip_cliente=ip,
            mac_cliente=datos.mac_cliente,
            estado="ACTIVO",
            fecha_registro=fecha_registro,
            fecha_vencimiento=primer_vencimiento,
            dia_pago=primer_vencimiento.day,
            saldo_dias_favor=0,
        )

        # 4. Guardar
        self.session.add(cliente)
        try:
            self.session.commit()
        except IntegrityError as error:
            # Segunda barrera: si dos registros con la misma IP llegan al mismo
            # tiempo, la restricción UNIQUE (router_id, ip_cliente) de MySQL lo impide.
            self.session.rollback()
            raise IpDuplicada(f"La IP {ip} ya está asignada en este ruteador.") from error
        self.session.refresh(cliente)
        return cliente

    # HU-02, HU-03 ----------------------------------------------------------
    def buscar_abonados(self, texto: str) -> list[Cliente]:
        """Busca abonados por DNI o por apellidos (HU-02, HU-03; prueba PU-08).

        - Por DNI: coincidencia exacta; devuelve todos los servicios del mismo titular.
        - Por apellidos: devuelve los que contienen el texto buscado.
        - Ordena por apellidos y nombres.
        No distingue mayúsculas ni tildes ("perez" encuentra "Pérez") porque así
        compara MySQL con la intercalación utf8mb4_0900_ai_ci definida en las tablas.
        Es el paso previo para registrar un pago o suspender a un abonado.
        """
        texto = " ".join(texto.split())
        if not texto:
            return []
        # Los caracteres % y _ escritos por el operador se buscan como texto, no como comodines.
        patron = "%" + texto.replace("/", "//").replace("%", "/%").replace("_", "/_") + "%"
        consulta = (
            select(Cliente)
            .options(joinedload(Cliente.router))              # trae también el ruteador de cada abonado
            .where(or_(Cliente.dni == texto, Cliente.apellidos.like(patron, escape="/")))
            .order_by(Cliente.apellidos, Cliente.nombres, Cliente.id)
        )
        return list(self.session.scalars(consulta).unique())

    def obtener_ficha(self, cliente_id: int) -> Cliente:
        """Devuelve un abonado con su ruteador y su plan; si no existe, RecursoNoEncontrado."""
        cliente = self.session.get(
            Cliente, cliente_id, options=[joinedload(Cliente.router), joinedload(Cliente.tarifa)]
        )
        if cliente is None:
            raise RecursoNoEncontrado(f"No existe el abonado con id {cliente_id}.")
        return cliente

    # HU-02 -----------------------------------------------------------------
    def registrar_pago_abonado(self, cliente_id: int, datos: PagoCrear, hoy: Optional[date] = None) -> ResultadoPago:
        """Registra el pago de un abonado y actualiza su vencimiento (HU-02; pruebas PU-03 a PU-05).

        Según el estado del abonado al momento de pagar:
            - ACTIVO: su día de pago se mantiene; el nuevo vencimiento es ese
              día del mes siguiente. No se genera ninguna orden.
            - PENDIENTE_SUSPENSION (el corte se ordenó pero aún no se aplicó):
              se anula la orden de corte, vuelve a ACTIVO y su vencimiento
              avanza al mes siguiente, sin orden de activación (PU-05).
            - SUSPENDIDO (el corte ya se aplicó): se recalcula el vencimiento
              descontando los días usados sin pagar, el día de ese nuevo
              vencimiento pasa a ser su día de pago y se encola una orden de
              ACTIVACION con su IP y las velocidades de su plan (PU-04). Sigue
              SUSPENDIDO hasta que la orden se aplique en el ruteador.
        El pago, los cambios del abonado y la orden se guardan en una sola
        transacción: si algo falla, no se guarda nada (PU-03).
        """
        cliente = self.session.get(Cliente, cliente_id, options=[joinedload(Cliente.tarifa)])
        if cliente is None:
            raise RecursoNoEncontrado(f"No existe el abonado con id {cliente_id}.")
        fecha_pago = datos.fecha_pago or hoy or date.today()

        try:
            # 1. Pago en caja
            pago = CajaIngreso(cliente_id=cliente.id, monto=Decimal(datos.monto),
                               medio_pago=datos.medio_pago, fecha_registro=fecha_pago)
            self.session.add(pago)

            # 2. Nuevo vencimiento según el estado del abonado
            #
            # Fecha del corte solo si el corte ya se aplicó (SUSPENDIDO); si no, None: no hay corte que descontar.
            corte_aplicado = cliente.fecha_corte_efectivo if cliente.estado == "SUSPENDIDO" else None

            # El calculador devuelve dos valores, en este orden: nueva fecha de vencimiento y nuevo día de pago.
            nuevo_vencimiento, nuevo_dia = CalculadorPeriodoComercial.nuevo_vencimiento_por_pago(
                cliente.fecha_vencimiento, cliente.dia_pago, fecha_pago,
                fecha_corte=corte_aplicado, saldo_dias_favor=cliente.saldo_dias_favor,
            )
            cliente.fecha_vencimiento = nuevo_vencimiento
            cliente.dia_pago = nuevo_dia

            # 3. Órdenes de la cola, según el estado del abonado al pagar:
            #    - ACTIVO: no se genera ni se anula ninguna orden.
            #    - PENDIENTE_SUSPENSION: el corte aún no se aplicó; se anula y vuelve a ACTIVO de inmediato.
            #    - SUSPENDIDO: el corte ya se aplicó; se encola la reactivación y sigue SUSPENDIDO
            #      hasta que la cola la aplique en el ruteador (consistencia eventual).
            orden_generada = orden_anulada = None
            if cliente.estado == "PENDIENTE_SUSPENSION":
                orden_anulada = self._anular_corte_pendiente(cliente)
                cliente.estado = "ACTIVO"
            elif cliente.estado == "SUSPENDIDO":
                orden_generada = self._registrar_orden_activacion(cliente)
                cliente.fecha_corte_efectivo = None     # el corte ya se descontó en el recálculo
                cliente.saldo_dias_favor = 0

            # 4. Todo se confirma junto
            self.session.commit()
        except Exception:
            self.session.rollback()     # PU-03: si algo falla, no queda ni el pago ni la orden
            raise

        return ResultadoPago(pago=pago, cliente=cliente, orden_generada=orden_generada, orden_anulada=orden_anulada)

    # HU-03: suspensiones -----------------------------------------------------
    def procesar_vencimientos(self, hoy: Optional[date] = None) -> list[ResultadoSuspension]:
        """Suspensión automática por vencimiento: tarea programada diaria (HU-03; prueba PU-06).

        Busca a los abonados ACTIVOS cuya fecha de vencimiento más los días de
        gracia ya fue superada; a cada uno lo pasa a PENDIENTE_SUSPENSION y
        encola su orden de CORTE. Los que están dentro de la gracia no se tocan.
        Todas las suspensiones del día se guardan juntas: si una falla, no se
        guarda ninguna, y la tarea puede volver a ejecutarse sin duplicar órdenes.
        La lanza app/tareas.py una vez al día; no es una operación de la interfaz.
        """
        hoy = hoy or date.today()
        activos = self.session.scalars(
            select(Cliente).options(joinedload(Cliente.tarifa)).where(Cliente.estado == "ACTIVO")
        ).unique().all()
        vencidos = [c for c in activos if CalculadorPeriodoComercial.gracia_superada(c.fecha_vencimiento, hoy)]

        resultados = []
        try:
            for cliente in vencidos:
                orden = self._registrar_orden_corte(cliente)
                cliente.estado = "PENDIENTE_SUSPENSION"
                resultados.append(ResultadoSuspension(cliente=cliente, orden=orden))
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return resultados

    def suspender_abonado_manual(self, cliente_id: int) -> ResultadoSuspension:
        """Suspensión manual por decisión del negocio (HU-03).

        Permite suspender a un abonado ACTIVO antes de que concluya su plazo de
        gracia: lo pasa a PENDIENTE_SUSPENSION y encola su orden de CORTE.
        Si el corte se aplica antes de su vencimiento, los días pagados que no
        usó se registran como saldo a favor cuando la orden se ejecute en el
        ruteador (lo hará la cola de órdenes en un bloque posterior).
        Errores: RecursoNoEncontrado si no existe; EstadoNoPermitido si no está ACTIVO.
        """
        cliente = self.session.get(Cliente, cliente_id, options=[joinedload(Cliente.tarifa)])
        if cliente is None:
            raise RecursoNoEncontrado(f"No existe el abonado con id {cliente_id}.")
        if cliente.estado != "ACTIVO":
            raise EstadoNoPermitido(
                f"El abonado {cliente_id} está en estado {cliente.estado}; solo se suspende a un abonado ACTIVO."
            )
        try:
            orden = self._registrar_orden_corte(cliente)
            cliente.estado = "PENDIENTE_SUSPENSION"
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return ResultadoSuspension(cliente=cliente, orden=orden)

    def _registrar_orden_corte(self, cliente: Cliente) -> TareaPendienteRed:
        """Encola la orden de cortar al abonado: su cola simple quedará limitada a 1k/1k en su ruteador.

        Si ya tiene una orden de corte pendiente, la devuelve en lugar de crear otra.
        """
        existente = self.session.scalar(
            select(TareaPendienteRed).where(
                TareaPendienteRed.cliente_id == cliente.id,
                TareaPendienteRed.accion == "CORTE",
                TareaPendienteRed.estado == "PENDIENTE",
            )
        )
        if existente is not None:
            return existente
        orden = TareaPendienteRed(
            router_id=cliente.router_id,
            cliente_id=cliente.id,
            accion="CORTE",
            payload_parametros_red={"ip_cliente": cliente.ip_cliente, "rate_upload": "1k", "rate_download": "1k"},
            estado="PENDIENTE",
        )
        self.session.add(orden)
        self.session.flush()            # obtiene el id de la orden antes de confirmar
        return orden

    def _registrar_orden_activacion(self, cliente: Cliente) -> TareaPendienteRed:
        """Encola la orden de reactivar al abonado en su ruteador, con su IP y las velocidades de su plan."""
        orden = TareaPendienteRed(
            router_id=cliente.router_id,
            cliente_id=cliente.id,
            accion="ACTIVACION",
            payload_parametros_red={
                "ip_cliente": cliente.ip_cliente,
                "rate_upload": cliente.tarifa.rate_upload,
                "rate_download": cliente.tarifa.rate_download,
            },
            estado="PENDIENTE",
        )
        self.session.add(orden)
        self.session.flush()            # obtiene el id de la orden antes de confirmar
        return orden

    def _anular_corte_pendiente(self, cliente: Cliente) -> Optional[TareaPendienteRed]:
        """Anula la orden de corte del abonado que aún no se aplicó en el ruteador (PU-05)."""
        orden = self.session.scalar(
            select(TareaPendienteRed).where(
                TareaPendienteRed.cliente_id == cliente.id,
                TareaPendienteRed.accion == "CORTE",
                TareaPendienteRed.estado == "PENDIENTE",
            )
        )
        if orden is not None:
            orden.estado = "ANULADO"
        return orden
