"""Reglas de negocio de los abonados: clase GestionAbonadosService (Anexo G, capa 4).

Qué hace:
    Registra abonados nuevos, los busca por DNI o apellidos y entrega su ficha.
    Aquí se aplican las reglas: que el ruteador y el plan existan, que la IP no
    se repita en el mismo ruteador y cuándo vence el primer pago.

Regla del periodo (prepago):
    - El servicio corre desde el día siguiente al registro (instalación).
    - fecha_vencimiento es el día en que vence el pago del periodo en curso.
      Al registrar, el primer periodo aún no está pagado: vence el día siguiente.
    - El abonado tiene 10 días de gracia para pagar. El pago lo registra el
      servicio de pagos (HU-02), que extiende el vencimiento en 30 días.

Con qué se relaciona:
    - Lo llama: app/routers/abonados.py (endpoints) y tests/test_abonados.py (pruebas).
    - Usa: app/models.py (tablas cliente, router_node, perfil_tarifa) y
      app/schemas.py (AbonadoCrear, datos ya validados).
    - No se comunica con los ruteadores: por diseño (sección 6.3), solo la Capa
      de Abstracción de Hardware accede a los equipos.
"""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import Cliente, PerfilTarifa, RouterNode
from app.schemas import AbonadoCrear


# ------------------------------------------------------------ errores del negocio
class ErrorNegocio(Exception):
    """Error general de una regla de negocio. Los endpoints lo convierten en un código HTTP."""


class RecursoNoEncontrado(ErrorNegocio):
    """El ruteador, el plan o el abonado indicado no existe (PU-02). El endpoint responde 404."""


class IpDuplicada(ErrorNegocio):
    """La IP ya está asignada a otro abonado del mismo ruteador (PU-01). El endpoint responde 409."""


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
            3. Calcula el primer vencimiento: fecha de registro + 1 día.
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
            fecha_vencimiento=fecha_registro + timedelta(days=1),
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
