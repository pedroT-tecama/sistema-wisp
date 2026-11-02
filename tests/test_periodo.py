"""Pruebas unitarias de las reglas de fechas del periodo prepago (sección 6.7, PU-04).

Qué prueba:
    - Primer vencimiento y límite de gracia.
    - Día de pago fijo para el abonado puntual (mismo día de cada mes).
    - Días 29, 30 y 31: último día del mes cuando el día no existe, y regreso
      a su día al mes siguiente (incluido febrero de año bisiesto).
    - PU-04: recálculo del vencimiento cuando el abonado paga después del corte.
    - PU-06: cuándo se considera superada la gracia; días consumidos y saldo a favor.

Estas pruebas no usan la base de datos: verifican solo los cálculos.

Con qué se relaciona:
    - Prueba app/services/periodo.py (CalculadorPeriodoComercial).
"""
from datetime import date

from app.services.periodo import CalculadorPeriodoComercial as Periodo


def test_primer_vencimiento_y_gracia():
    """Registrado el 15/10: vence el 16/10 y puede pagar hasta el 26/10."""
    vence = Periodo.primer_vencimiento(date(2026, 10, 15))
    assert vence == date(2026, 10, 16)
    assert Periodo.limite_gracia(vence) == date(2026, 10, 26)


def test_puntual_conserva_su_dia_de_pago():
    """Vence el 18/10 y paga el 24/10 (dentro de la gracia): su próximo vencimiento es el 18/11."""
    nuevo, dia = Periodo.nuevo_vencimiento_por_pago(date(2026, 10, 18), 18, fecha_pago=date(2026, 10, 24))
    assert (nuevo, dia) == (date(2026, 11, 18), 18)


def test_dia_31_cae_el_ultimo_dia_y_luego_vuelve():
    """Día de pago 31: en noviembre vence el 30 y en diciembre vuelve al 31."""
    noviembre = Periodo.siguiente_vencimiento(date(2026, 10, 31), 31)
    diciembre = Periodo.siguiente_vencimiento(noviembre, 31)
    assert noviembre == date(2026, 11, 30)
    assert diciembre == date(2026, 12, 31)


def test_dia_30_en_febrero_y_regreso_en_marzo():
    """Día de pago 30: en febrero vence el 28 (29 en año bisiesto) y en marzo vuelve al 30."""
    febrero = Periodo.siguiente_vencimiento(date(2027, 1, 30), 30)
    assert febrero == date(2027, 2, 28)
    assert Periodo.siguiente_vencimiento(febrero, 30) == date(2027, 3, 30)
    assert Periodo.siguiente_vencimiento(date(2028, 1, 30), 30) == date(2028, 2, 29)


def test_pu04_recalculo_tras_el_corte():
    """PU-04: vence el 01/10, corte el 11/10, paga el 15/10 -> nuevo vencimiento el 04/11, día de pago 4."""
    nuevo, dia = Periodo.nuevo_vencimiento_por_pago(
        date(2026, 10, 1), 1, fecha_pago=date(2026, 10, 15), fecha_corte=date(2026, 10, 11)
    )
    assert (nuevo, dia) == (date(2026, 11, 4), 4)


def test_gracia_superada_solo_despues_del_ultimo_dia():
    """Vence el 01/10: el 11/10 aún está en gracia; el 12/10 la gracia está superada (PU-06)."""
    assert not Periodo.gracia_superada(date(2026, 10, 1), date(2026, 10, 11))
    assert Periodo.gracia_superada(date(2026, 10, 1), date(2026, 10, 12))


def test_dias_consumidos_y_saldo_a_favor():
    """Corte después del vencimiento: días consumidos. Corte antes del vencimiento (manual): días a favor."""
    assert Periodo.calcular_dias_consumidos_en_espera(date(2026, 10, 1), date(2026, 10, 11)) == 10
    assert Periodo.calcular_saldo_dias_favor(date(2026, 10, 20), date(2026, 10, 12)) == 8
    assert Periodo.calcular_dias_consumidos_en_espera(date(2026, 10, 20), date(2026, 10, 12)) == 0
