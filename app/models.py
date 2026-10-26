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
    - app/services/abonados.py      : usa Cliente, RouterNode y PerfilTarifa.
    - tests/conftest.py             : crea datos de prueba con RouterMaster, RouterNode y PerfilTarifa.

En este bloque se describen las tablas que necesita el registro de abonados.
Las de pagos, órdenes y alertas se agregan en sus bloques.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Numeric, SmallInteger, String
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
    su estado (ACTIVO, PENDIENTE_SUSPENSION o SUSPENDIDO) y su fecha de vencimiento.
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
    fecha_vencimiento: Mapped[date] = mapped_column(Date)            # día en que vence el pago del periodo
    fecha_corte_efectivo: Mapped[Optional[date]] = mapped_column(Date)  # día en que se aplicó el último corte
    saldo_dias_favor: Mapped[int] = mapped_column(SmallInteger, default=0)

    router: Mapped[RouterNode] = relationship()     # permite leer el ruteador desde el abonado
    tarifa: Mapped[PerfilTarifa] = relationship()   # permite leer el plan desde el abonado
