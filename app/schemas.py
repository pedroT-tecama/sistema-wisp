"""Esquemas de datos: forma y validación de lo que entra y sale de cada endpoint.

Qué hace:
    - Esquemas de ENTRADA (AbonadoCrear): revisan que los datos enviados por el
      operador estén completos y bien escritos (IP válida, MAC, DNI, longitudes)
      ANTES de llegar a las reglas de negocio. Si algo está mal, FastAPI responde
      con el código 422 y el detalle del campo con error.
    - Esquemas de SALIDA (AbonadoResumen, AbonadoFicha): definen qué datos se
      devuelven en cada respuesta.
    Además, FastAPI usa estos esquemas para dibujar los formularios de /docs.

Con qué se relaciona:
    - app/routers/abonados.py   : recibe AbonadoCrear y responde con AbonadoResumen o AbonadoFicha.
    - app/routers/pagos.py      : recibe PagoCrear y responde con PagoResultado.
    - app/routers/suspensiones.py : responde con SuspensionResultado.
    - app/services/abonados.py  : recibe AbonadoCrear ya validado.
    - app/models.py             : los esquemas de salida se llenan leyendo los modelos.
"""
from datetime import date
from decimal import Decimal
from ipaddress import IPv4Address
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAC_PATRON = r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$"   # formato AA:BB:CC:11:22:33


# ---------------------------------------------------------------- entrada
class AbonadoCrear(BaseModel):
    """Datos que el operador ingresa para registrar un abonado tras su instalación (HU-01).

    Los valores de "examples" son los que aparecen de ejemplo en /docs.
    """

    nombres: str = Field(min_length=1, max_length=40, examples=["Juan Carlos"])
    apellidos: str = Field(min_length=1, max_length=40, examples=["Pérez Quispe"])
    dni: str = Field(min_length=8, max_length=12, pattern=r"^[0-9A-Za-z]+$", examples=["40123456"])
    direccion: str = Field(min_length=1, max_length=150, examples=["Jr. Los Pinos 123, Condominio 1"])
    ip_cliente: IPv4Address = Field(examples=["192.168.103.101"])          # rechaza IP mal escritas
    mac_cliente: Optional[str] = Field(default=None, pattern=MAC_PATRON, examples=["AA:BB:CC:11:22:33"])
    router_id: int = Field(gt=0, examples=[2])                              # id en la tabla router_node
    tarifa_id: int = Field(gt=0, examples=[1])                              # id en la tabla perfil_tarifa
    fecha_registro: Optional[date] = Field(
        default=None,
        description="Fecha de registro (instalación). Si se omite, se usa la fecha de hoy.",
    )

    @field_validator("nombres", "apellidos", "direccion", "dni")
    @classmethod
    def quitar_espacios(cls, valor: str) -> str:
        """Elimina espacios repetidos o sobrantes y rechaza textos que solo tengan espacios."""
        valor = " ".join(valor.split())
        if not valor:
            raise ValueError("no puede estar vacío")
        return valor

    @field_validator("mac_cliente")
    @classmethod
    def mac_en_mayusculas(cls, valor: Optional[str]) -> Optional[str]:
        """Guarda la MAC siempre en mayúsculas para que se lea de forma uniforme."""
        return valor.upper() if valor else valor


# ---------------------------------------------------------------- salida
class RouterResumen(BaseModel):
    """Datos básicos del ruteador que se muestran dentro de la ficha o la búsqueda."""

    model_config = ConfigDict(from_attributes=True)   # permite llenarlo desde un modelo de app/models.py

    id: int
    nombre_equipo: str
    ip_gestion_ospf: str


class PlanResumen(BaseModel):
    """Datos del plan contratado que se muestran dentro de la ficha."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_plan: str
    precio_mensual: Decimal
    rate_upload: str
    rate_download: str


class AbonadoResumen(BaseModel):
    """Una fila del resultado de búsqueda (HU-02, HU-03): lo necesario para ubicar al abonado."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nombres: str
    apellidos: str
    dni: str
    direccion: str
    estado: str
    fecha_vencimiento: date
    router: RouterResumen


class AbonadoFicha(AbonadoResumen):
    """Ficha completa del abonado: los datos del resumen más su IP, MAC, plan, fechas y día de pago."""

    ip_cliente: str
    mac_cliente: Optional[str]
    fecha_registro: date
    dia_pago: int
    fecha_corte_efectivo: Optional[date]
    saldo_dias_favor: int
    tarifa: PlanResumen


# ---------------------------------------------------------------- pagos
class PagoCrear(BaseModel):
    """Datos que el operador ingresa al cobrar a un abonado (HU-02)."""

    monto: Decimal = Field(gt=0, max_digits=10, decimal_places=2, examples=["50.00"])
    medio_pago: str = Field(min_length=1, max_length=30, examples=["Efectivo"])
    fecha_pago: Optional[date] = Field(
        default=None,
        description="Fecha del pago. Si se omite, se usa la fecha de hoy.",
    )

    @field_validator("medio_pago")
    @classmethod
    def quitar_espacios(cls, valor: str) -> str:
        """Elimina espacios sobrantes y rechaza un medio de pago vacío."""
        valor = " ".join(valor.split())
        if not valor:
            raise ValueError("no puede estar vacío")
        return valor


class OrdenResumen(BaseModel):
    """Orden de la cola generada o anulada por el pago."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    accion: str
    estado: str


class PagoResultado(BaseModel):
    """Respuesta al registrar un pago: el pago, el nuevo vencimiento y qué pasó con las órdenes."""

    pago_id: int
    cliente_id: int
    monto: Decimal
    fecha_pago: date
    nuevo_vencimiento: date
    dia_pago: int
    estado_abonado: str
    orden_generada: Optional[OrdenResumen] = None   # activación encolada (abonado que estaba cortado)
    orden_anulada: Optional[OrdenResumen] = None    # corte que aún no se aplicaba y se cancela (PU-05)
    mensaje: str


# ---------------------------------------------------------------- suspensiones
class SuspensionResultado(BaseModel):
    """Respuesta a la suspensión manual: el nuevo estado del abonado y la orden de corte encolada."""

    cliente_id: int
    estado_abonado: str
    fecha_vencimiento: date
    orden_corte: OrdenResumen
    mensaje: str
