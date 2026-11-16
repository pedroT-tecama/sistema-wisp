"""Reporte de incidentes del monitoreo, listo para capturar como evidencia.

Qué hace:
    Lee de la base de operación (wisp_db) las alertas registradas desde una
    fecha y hora, y arma una página HTML con una tabla ordenada: columnas
    cortas (id, tipo, origen, horas, duración) y la descripción completa en
    una sola celda con el texto justificado. Guarda la página en la carpeta
    evidencias y la abre en el navegador para tomar la captura.

Uso (desde la carpeta del proyecto, con el entorno virtual activo):
    python scripts/reporte_incidentes.py                      -> alertas de hoy
    python scripts/reporte_incidentes.py "2026-11-16 04:50"   -> desde esa fecha y hora

Con qué se relaciona:
    - Lee: app/models.py (RegistroAlerta, RouterNode, RouterMaster, EnlaceBackhaulPTP)
      con la conexión de app/database.py (DB_URL del archivo .env).
    - Las alertas las registra app/monitoreo.py (MotorTelemetriaProactiva).
    - Es de solo lectura: no modifica la base.
"""
import html
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # para importar app/ desde scripts/

from sqlalchemy import select

from app.database import SessionLocal
from app.models import EnlaceBackhaulPTP, RegistroAlerta, RouterMaster, RouterNode

NOMBRE_TIPO = {"OSPF_RUTA_AUSENTE": "Ruta OSPF ausente", "PTP_DEGRADADO": "Enlace degradado",
               "CABECERA_INACCESIBLE": "Cabecera inaccesible"}

# desde: fecha y hora pasada como parámetro, o el inicio del día de hoy
desde = datetime.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.combine(date.today(), datetime.min.time())

with SessionLocal() as s:
    alertas = s.scalars(select(RegistroAlerta).where(RegistroAlerta.fecha_registro >= desde)
                        .order_by(RegistroAlerta.id_alerta)).all()
    filas = []
    for a in alertas:
        if a.router_id:
            origen = s.get(RouterNode, a.router_id).nombre_equipo
        elif a.enlace_id:
            origen = s.get(EnlaceBackhaulPTP, a.enlace_id).nombre_enlace
        else:
            origen = s.get(RouterMaster, a.master_id).nombre_distrito
        duracion = str(a.fecha_resolucion - a.fecha_registro) if a.fecha_resolucion else ""
        filas.append((a.id_alerta, NOMBRE_TIPO.get(a.prefijo_excepcion, a.prefijo_excepcion), origen,
                      a.fecha_registro.strftime("%d/%m %H:%M:%S"),
                      a.fecha_resolucion.strftime("%d/%m %H:%M:%S") if a.fecha_resolucion else "ABIERTA",
                      duracion, a.descripcion_error))

# página HTML: columnas cortas sin salto de línea y descripción justificada en una sola celda
celdas = "".join(
    "<tr>" + "".join(f'<td class="c">{html.escape(str(v))}</td>' for v in f[:6])
    + f'<td class="d">{html.escape(f[6])}</td></tr>' for f in filas)
pagina = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>Incidentes del monitoreo</title>
<style>
 body {{ font-family: Arial, sans-serif; margin: 24px; color: #222; }}
 h1 {{ font-size: 18px; margin: 0 0 4px; }}
 p  {{ font-size: 12px; color: #555; margin: 0 0 12px; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
 th {{ background: #1F3864; color: #fff; text-align: left; padding: 6px 8px; }}
 td {{ border-bottom: 1px solid #ddd; padding: 6px 8px; vertical-align: top; }}
 td.c {{ white-space: nowrap; }}
 td.d {{ text-align: justify; width: 100%; }}
 tr:nth-child(even) td {{ background: #F5F7FA; }}
</style></head><body>
<h1>Incidentes registrados por el monitoreo</h1>
<p>Base de operación wisp_db · desde {desde:%d/%m/%Y %H:%M} · {len(filas)} alerta(s) · generado el {datetime.now():%d/%m/%Y %H:%M}</p>
<table><tr><th>Id</th><th>Tipo</th><th>Origen</th><th>Registro</th><th>Resolución</th><th>Duración</th><th>Descripción</th></tr>
{celdas}</table></body></html>"""

carpeta = Path(__file__).resolve().parent.parent / "evidencias"
archivo = carpeta / f"incidentes_{desde:%Y-%m-%d_%H%M}.html"
archivo.write_text(pagina, encoding="utf-8")
print(f"{len(filas)} alerta(s). Reporte guardado en {archivo}")
webbrowser.open(archivo.as_uri())                                   # se abre en el navegador para la captura
