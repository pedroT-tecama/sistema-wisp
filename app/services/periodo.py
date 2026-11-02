"""Cálculo de fechas del periodo prepago: clase CalculadorPeriodoComercial (Anexo G, capa 4).

Qué hace:
    Reúne en un solo lugar las reglas de fechas del modelo prepago, para que
    el registro de abonados, los pagos y las suspensiones las apliquen igual.

Reglas (obtenidas en el levantamiento de información, Capítulo 4):
    1. El servicio corre desde el día siguiente al registro (instalación). Ese
       día vence el primer mes adelantado y pasa a ser su DÍA DE PAGO.
    2. El abonado tiene 10 días de gracia después de cada vencimiento.
    3. Si paga a tiempo, su día de pago se mantiene: el siguiente vencimiento
       es el mismo día del mes siguiente (si le toca el 18, paga todos los 18).
    4. Si su día de pago no existe en un mes (el 31 en noviembre, el 30 en
       febrero), ese mes vence el último día del mes; al mes siguiente vuelve
       a su día.
    5. Solo si fue cortado, al pagar se recalcula todo: el nuevo periodo de 30
       días empieza el día del pago, se le descuentan los días que usó el
       servicio sin pagar (del vencimiento al corte) y se le suman los días a
       favor. La fecha que resulta es su nuevo día de pago (prueba PU-04).

Todas las funciones son cálculos puros: no leen ni guardan en la base de datos.

Con qué se relaciona:
    - Lo usa: app/services/abonados.py (primer vencimiento, pagos y suspensión
      por vencimiento). Los nombres de los métodos siguen el Anexo G.
    - Lo prueba: tests/test_periodo.py.
"""
import calendar
import os
from datetime import date, timedelta
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
DIAS_GRACIA = int(os.getenv("DIAS_GRACIA", "10"))   # parámetro de operación (sección 6.2)
DIAS_PERIODO_RECALCULO = 30                        # periodo que se usa solo al recalcular tras un corte


class CalculadorPeriodoComercial:
    """Reglas de fechas del modelo prepago (vencimientos, gracia y recálculo tras un corte)."""

    @staticmethod
    def vencimiento_del_mes(anio: int, mes: int, dia_pago: int) -> date:
        """Devuelve el día de vencimiento de un mes dado (regla 4).

        Si el día de pago no existe en ese mes, devuelve el último día del mes.
        Ejemplo: día 31 en noviembre de 2026 -> 30/11/2026.
        """
        ultimo_dia = calendar.monthrange(anio, mes)[1]     # cantidad de días del mes
        return date(anio, mes, min(dia_pago, ultimo_dia))

    @staticmethod
    def primer_vencimiento(fecha_registro: date) -> date:
        """Primer vencimiento: el día siguiente al registro (regla 1).

        Ejemplo: registrado el 15/10 -> vence el 16/10 y su día de pago es el 16.
        """
        return fecha_registro + timedelta(days=1)

    @staticmethod
    def limite_gracia(vencimiento: date) -> date:
        """Último día para pagar sin corte: vencimiento + días de gracia (regla 2).

        Ejemplo: vence el 16/10 -> puede pagar hasta el 26/10.
        """
        return vencimiento + timedelta(days=DIAS_GRACIA)

    @classmethod
    def siguiente_vencimiento(cls, vencimiento_actual: date, dia_pago: int) -> date:
        """Vencimiento del mes siguiente, conservando el día de pago (reglas 3 y 4).

        Ejemplos: 18/10 con día 18 -> 18/11; 30/11 con día 31 -> 31/12;
        30/01/2027 con día 30 -> 28/02/2027; 28/02/2027 con día 30 -> 30/03/2027.
        """
        if vencimiento_actual.month == 12:
            anio, mes = vencimiento_actual.year + 1, 1
        else:
            anio, mes = vencimiento_actual.year, vencimiento_actual.month + 1
        return cls.vencimiento_del_mes(anio, mes, dia_pago)

    @staticmethod
    def calcular_dias_consumidos_en_espera(fecha_venc: date, fecha_corte: date) -> int:
        """Días en que el abonado usó el servicio sin pagar: del vencimiento al corte (regla 5).

        Incluye los días de gracia y el tiempo en que la orden de corte estuvo pendiente.
        Si el corte ocurrió antes del vencimiento (suspensión manual), devuelve 0.
        Ejemplo: vence 01/10, corte 11/10 -> 10 días.
        """
        return max((fecha_corte - fecha_venc).days, 0)

    @staticmethod
    def calcular_saldo_dias_favor(fecha_venc: date, fecha_corte: date) -> int:
        """Días pagados que el abonado no llegó a usar porque fue cortado antes de su vencimiento.

        Solo ocurre con la suspensión manual; se suman al reactivar el servicio.
        Ejemplo: vence 20/10, corte 12/10 -> 8 días a favor.
        """
        return max((fecha_venc - fecha_corte).days, 0)

    @classmethod
    def conciliar_fechas_por_reactivacion(
        cls, vencimiento: date, fecha_corte: date, fecha_pago: date, saldo_dias_favor: int = 0
    ) -> date:
        """Nuevo vencimiento cuando el abonado paga después de haber sido cortado (regla 5).

        nuevo vencimiento = fecha de pago + 30 - días consumidos sin pagar + días a favor.
        Ejemplo (PU-04): vence 01/10, corte 11/10, paga 15/10 -> 15/10 + 30 - 10 = 04/11.
        """
        dias_consumidos = cls.calcular_dias_consumidos_en_espera(vencimiento, fecha_corte)
        return fecha_pago + timedelta(days=DIAS_PERIODO_RECALCULO - dias_consumidos + saldo_dias_favor)

    @classmethod
    def gracia_superada(cls, vencimiento: date, hoy: date) -> bool:
        """Indica si ya pasaron los días de gracia: hoy es posterior al último día para pagar (PU-06).

        Ejemplo: vence 01/10 -> puede pagar hasta el 11/10; el 12/10 la gracia está superada.
        """
        return hoy > cls.limite_gracia(vencimiento)

    @classmethod
    def nuevo_vencimiento_por_pago(
        cls,
        vencimiento: date,
        dia_pago: int,
        fecha_pago: date,
        fecha_corte: Optional[date] = None,
        saldo_dias_favor: int = 0,
    ) -> tuple[date, int]:
        """Decide qué regla aplica al registrar un pago y devuelve (nuevo vencimiento, nuevo día de pago).

        - Sin corte (pagó a tiempo o dentro de la gracia): mismo día del mes siguiente.
        - Con corte: recálculo; el día del nuevo vencimiento pasa a ser su día de pago.
        """
        if fecha_corte is None:
            return cls.siguiente_vencimiento(vencimiento, dia_pago), dia_pago
        nuevo = cls.conciliar_fechas_por_reactivacion(vencimiento, fecha_corte, fecha_pago, saldo_dias_favor)
        return nuevo, nuevo.day
