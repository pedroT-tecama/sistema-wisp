"""Modelos persistentes: las tablas de MySQL representadas como clases de Python (sección 6.4).

Qué hace:
    Cada clase corresponde a una tabla del Anexo H y cada atributo a una
    columna. Con estas clases, el resto del programa lee y guarda datos sin
    escribir SQL a mano.

Importante:
    Las tablas las crea el script sql/01_crear_esquema.sql. Estas clases solo
    las describen; el programa nunca crea ni modifica la estructura de las tablas.

Con qué se relaciona:
    - sql/01_crear_esquema.sql      : definición real de las tablas (debe coincidir).
    - app/services/abonados.py      : usa Cliente, RouterNode, PerfilTarifa,
                                      CajaIngreso y TareaPendienteRed.
    - tests/conftest.py             : crea datos de prueba con RouterMaster, RouterNode y PerfilTarifa.

Hasta este bloque se describen las tablas del registro de abonados, de los
pagos (caja_ingreso) y de la cola de órdenes (tarea_pendiente_red). Las de
alertas y enlaces se agregan en sus bloques.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Integer, Numeric, SmallInteger, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base común de todos los modelos; agrupa las tablas del sistema."""


class RouterMaster(Base):
    """Tabla router_master: cabeceras distritales.

    Una fila por distrito, con la dirección pública (DDNS o IP) por la que el
    sistema llega a la red de ese distrito.
    """

    __tablename__ = "router_master"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre_distrito: Mapped[str] = mapped_column(String(80))
    ddns_url: Mapped[str] = mapped_column(String(255))
    puerto_base: Mapped[int] = mapped_column(SmallInteger)
    version_routeros: Mapped[Optional[str]] = mapped_column(String(10))


class RouterNode(Base):
    """Tabla router_node: ruteadores de cada distrito, organizados en árbol.

    Incluye el ruteador de la cabecera como nodo raíz (padre_id vacío) y los
    ruteadores de borde que dependen de él (padre_id = ruteador superior).
    Los abonados se asignan a uno de estos ruteadores.
    """

    __tablename__ = "router_node"

    id: Mapped[int] = mapped_column(primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("router_master.id"))   # distrito al que pertenece
    padre_id: Mapped[Optional[int]] = mapped_column(ForeignKey("router_node.id"))  # ruteador superior
    nombre_equipo: Mapped[str] = mapped_column(String(80))
    tipo_nodo: Mapped[str] = mapped_column(Enum("ROUTER", "ACCESS_POINT", native_enum=False))
    ip_gestion_ospf: Mapped[str] = mapped_column(String(15))
    puerto_socket: Mapped[int] = mapped_column(SmallInteger)
    version_routeros: Mapped[Optional[str]] = mapped_column(String(10))
    estado_operativo: Mapped[str] = mapped_column(
        Enum("CHECK_OK", "NODO_CAIDO", native_enum=False), default="CHECK_OK"
    )

    master: Mapped[RouterMaster] = relationship()   # permite leer el distrito desde el ruteador


class PerfilTarifa(Base):
    """Tabla perfil_tarifa: planes de servicio (precio y velocidades)."""

    __tablename__ = "perfil_tarifa"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre_plan: Mapped[str] = mapped_column(String(60))
    precio_mensual: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    rate_upload: Mapped[str] = mapped_column(String(10))     # formato RouterOS, ej. "4M"
    rate_download: Mapped[str] = mapped_column(String(10))   # formato RouterOS, ej. "7M"


class Cliente(Base):
    """Tabla cliente: abonados del ISP.

    Cada fila es un servicio: un abonado con su IP, su ruteador, su plan,
    su estado (ACTIVO, PENDIENTE_SUSPENSION o SUSPENDIDO), su fecha de registro,
    su fecha de vencimiento y su día de pago.
    """

    __tablename__ = "cliente"

    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("router_node.id"))     # ruteador que le da servicio
    tarifa_id: Mapped[int] = mapped_column(ForeignKey("perfil_tarifa.id"))   # plan contratado
    nombres: Mapped[str] = mapped_column(String(40))
    apellidos: Mapped[str] = mapped_column(String(40))
    dni: Mapped[str] = mapped_column(String(12))
    direccion: Mapped[str] = mapped_column(String(150))
    ip_cliente: Mapped[str] = mapped_column(String(15))
    mac_cliente: Mapped[Optional[str]] = mapped_column(String(17))
    estado: Mapped[str] = mapped_column(
        Enum("ACTIVO", "PENDIENTE_SUSPENSION", "SUSPENDIDO", native_enum=False), default="ACTIVO"
    )
    fecha_registro: Mapped[date] = mapped_column(Date)               # día de la instalación (dato histórico)
    fecha_vencimiento: Mapped[date] = mapped_column(Date)            # día en que vence el pago del periodo
    dia_pago: Mapped[int] = mapped_column(SmallInteger)              # día del mes en que paga (1 a 31)
    fecha_corte_efectivo: Mapped[Optional[date]] = mapped_column(Date)  # día en que se aplicó el último corte
    saldo_dias_favor: Mapped[int] = mapped_column(SmallInteger, default=0)

    router: Mapped[RouterNode] = relationship()     # permite leer el ruteador desde el abonado
    tarifa: Mapped[PerfilTarifa] = relationship()   # permite leer el plan desde el abonado


class CajaIngreso(Base):
    """Tabla caja_ingreso: pagos registrados (HU-02).

    Una fila por pago, con su monto, su medio de pago y la fecha en que se cobró.
    Nunca se borra: es el historial de ingresos del abonado.
    """

    __tablename__ = "caja_ingreso"

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"))   # abonado que pagó
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    medio_pago: Mapped[str] = mapped_column(String(30))                 # efectivo, Yape, transferencia, etc.
    fecha_registro: Mapped[date] = mapped_column(Date)                  # fecha del pago


class TareaPendienteRed(Base):
    """Tabla tarea_pendiente_red: cola de órdenes de corte y activación (Capa 2 del Anexo G).

    Cada orden indica qué hay que aplicar en un ruteador (CORTE o ACTIVACION)
    y con qué parámetros de red. El servicio comercial solo crea o anula
    órdenes; el envío a los ruteadores lo hace otro proceso en segundo plano
    (ControladorColaSincronizacion, en app/cola_sincronizacion.py).
    """

    __tablename__ = "tarea_pendiente_red"

    id: Mapped[int] = mapped_column(primary_key=True)
    router_id: Mapped[int] = mapped_column(ForeignKey("router_node.id"))    # ruteador donde se aplica
    cliente_id: Mapped[int] = mapped_column(ForeignKey("cliente.id"))       # abonado afectado
    accion: Mapped[str] = mapped_column(Enum("CORTE", "ACTIVACION", native_enum=False))
    payload_parametros_red: Mapped[dict] = mapped_column(JSON)   # los parámetros de red que contiene la orden
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    estado: Mapped[str] = mapped_column(
        Enum("PENDIENTE", "PROCESADO", "ANULADO", native_enum=False), default="PENDIENTE"
    )
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
