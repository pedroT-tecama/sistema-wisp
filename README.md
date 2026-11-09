# Sistema integrado de gestión comercial y gestión de control de la plataforma MikroTik para proveedores de servicio de internet

Prototipo desarrollado como parte de la tesis de Ingeniería Informática de la **Pontificia Universidad Católica del Perú**.

- **Autor:** Pedro Turpo Cahuapaza
- **Asesora:** Claudia Zapata
- **Curso:** Proyecto de Fin de Carrera 2 (2026-2)

## Qué hace

Un proveedor de servicio de internet con una red jerárquicamente distribuida en Capa 3 —cabeceras distritales y ruteadores MikroTik de borde— suele gestionar los pagos en hojas de cálculo y aplicar a mano, ruteador por ruteador, cada corte y cada reactivación. Este sistema centraliza esa gestión:

- **Gestión comercial:** registro de abonados y pagos bajo un modelo prepago (diez días de gracia), suspensión automática diaria al superarse la gracia, suspensión manual y reactivación al registrar el pago.
- **Control de la red:** los cortes y reactivaciones se aplican de forma automática en la cola simple del abonado (límite 1k/1k para el corte, velocidades del plan para la reactivación), mediante la API de RouterOS 6 y 7.
- **Monitoreo** *(en construcción):* detección de la pérdida de conectividad de los ruteadores a partir de la tabla de rutas OSPF de la cabecera, señal de los enlaces troncales y aviso por correo.

## Estado

| Bloque | Estado |
|---|---|
| Base de datos (9 tablas, 3FN) y carga inicial | Concluido |
| Registro y búsqueda de abonados | Concluido |
| Periodo prepago y registro de pagos | Concluido |
| Suspensión automática y manual (Hito 1) | Concluido |
| Capa de Abstracción de Hardware (RouterOS 6 y 7) | Concluido; verificado en un ruteador real |
| Cola de órdenes (Hito 2) | Concluido; verificado en tres ruteadores reales (RouterOS 7.8, 7.13.3 y 7.21.4) |
| Monitoreo OSPF, señal y correo (Hito 3) | Pendiente |

Pruebas unitarias: **38 de 38 conformes** (ver `evidencias/`).

## Arquitectura

Una sola aplicación organizada en cuatro capas (Anexo G de la tesis):

1. **Entidades de negocio** (`app/models.py`): abonados, planes, pagos, cabeceras, ruteadores y enlaces.
2. **Consistencia eventual** (`app/cola_sincronizacion.py`): las operaciones comerciales registran órdenes de alta, corte o reactivación en la tabla `tarea_pendiente_red`, en la misma transacción del registro, el pago o la suspensión; `ControladorColaSincronizacion` las aplica en segundo plano y las reintenta mientras un equipo no responda.
3. **Capa de Abstracción de Hardware** (`app/hal/`): única vía de comunicación con los ruteadores. `HardwareAbstractionLayer` elige el driver según la versión de RouterOS (`RouterOSv6Driver` o `RouterOSv7Driver`, que heredan de la clase abstracta `RouterOSDriver`); `MikrotikAPIClient` se comunica de forma asíncrona con la API de RouterOS.
4. **Servicios de aplicación** (`app/services/`): reglas del negocio (`GestionAbonadosService`, `CalculadorPeriodoComercial`).

Los servicios comerciales nunca se comunican con los ruteadores: así, la caída de un enlace no impide cobrar ni suspender.

## Estructura del proyecto

```
app/
  main.py            Punto de arranque: crea la aplicación e incorpora las rutas
  database.py        Conexión con MySQL
  models.py          Tablas como clases de Python (SQLAlchemy)
  schemas.py         Validación de datos de entrada y salida (Pydantic)
  tareas.py          Tareas en segundo plano: suspensión diaria y cola de órdenes
  cola_sincronizacion.py  Cola de órdenes: aplica cortes y reactivaciones en los ruteadores
  routers/           Operaciones de la interfaz: abonados, pagos, suspensiones, órdenes
  services/          Reglas del negocio: abonados, pagos, periodo prepago
  hal/               Capa de Abstracción de Hardware (RouterOS 6 y 7)
sql/                 Scripts de creación del esquema, carga inicial y ajustes
tests/               Pruebas unitarias (pytest)
scripts/             Pruebas manuales de conexión y de la capa de hardware
evidencias/          Reportes de ejecución de las pruebas y capturas
```

## Requisitos

- Python 3.12 (probado con 3.12.10)
- MySQL Community Server 8.4 LTS
- Ruteadores MikroTik con RouterOS 6 o 7 y el servicio API (puerto 8728) habilitado para el equipo central
- Dependencias con versión fijada en `requirements.txt` (FastAPI 0.161.1, Uvicorn 0.54.0, SQLAlchemy 2.1.6, PyMySQL 1.2.3, Pydantic 2.14.1, librouteros 4.2.2, pytest 9.1.1, entre otras)

## Instalación

```powershell
# 1. Entorno virtual y dependencias
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. Configuración: copiar la plantilla y completar los valores reales
copy env.ejemplo.txt .env
```

Base de datos, en MySQL Workbench y en este orden:

1. `sql/00_crear_bases_y_usuario.ejemplo.sql`: copiarlo como `00_crear_bases_y_usuario.sql`, reemplazar la clave y ejecutarlo como root. Crea las bases `wisp_db` (operación) y `wisp_test` (pruebas) y el usuario de la aplicación.
2. `sql/01_crear_esquema.sql` en ambas bases.
3. `sql/02_carga_inicial.sql` en `wisp_db` (planes, cabecera, ruteadores y enlace troncal).
4. `sql/03_cliente_fecha_registro_dia_pago.sql` solo en bases creadas antes de ese ajuste; las instalaciones nuevas ya lo incluyen en el script 01.
5. `sql/04_ruteadores_y_enlaces_adicionales.sql` en `wisp_db` (dos ruteadores de borde y un radioenlace del caso de estudio).

## Configuración (`.env`)

| Variable | Uso |
|---|---|
| `DB_URL`, `DB_URL_TEST` | Conexión con la base de operación y con la base de pruebas |
| `MK_USER`, `MK_PASS` | Usuario de la API de los ruteadores (se recomienda un grupo con permisos `read`, `write`, `api` y `test`) |
| `MK_PORT` | Puerto de la API (8728 por defecto) |
| `MK_TIMEOUT` | Segundos de espera por conexión (5 por defecto) |
| `MK_MODO_CONEXION` | `directo` (IP de gestión del ruteador) o `cabecera` (dirección pública de la cabecera y puerto mapeado) |
| `DIAS_GRACIA` | Días de gracia del periodo prepago (10 por defecto) |
| `SUSPENSION_AUTOMATICA`, `SUSPENSION_INTERVALO_HORAS` | Activa la suspensión diaria y define su intervalo |
| `COLA_AUTOMATICA`, `COLA_INTERVALO_SEGUNDOS` | Activa la cola de órdenes y define cada cuántos segundos revisa las pendientes (30 por defecto) |
| `COLA_CONCURRENCIA` | Órdenes que se aplican a la vez (5 por defecto) |

El archivo `.env` contiene credenciales y **no se publica** (está en `.gitignore`).

## Ejecución

```powershell
uvicorn app.main:app --reload
```

La interfaz de operación queda disponible en `http://127.0.0.1:8000/docs`.

## Pruebas

```powershell
python -m pytest -v
```

Las pruebas se ejecutan siempre sobre la base `wisp_test`; cada prueba revierte sus cambios al terminar. Las de la Capa de Abstracción de Hardware usan un ruteador simulado y no necesitan red.

Prueba manual sobre un ruteador real (usar solo IP ficticias con su cola simple de prueba creada a mano):

```powershell
python -m scripts.prueba_hal ver       192.168.103.101
python -m scripts.prueba_hal cortar    192.168.103.101
python -m scripts.prueba_hal reactivar 192.168.103.101 4M 7M
```

## Alcance

Prototipo mínimo viable que se ejecuta en un equipo con Windows 11 como servidor central y opera sobre ruteadores reales de la red del caso de estudio, con abonados ficticios. La puesta en producción en un servidor Linux y la migración de la operación del proveedor quedan como trabajo futuro.

## Uso de inteligencia artificial

En el desarrollo se empleó la herramienta Claude (Anthropic) como apoyo, bajo la dirección y verificación del autor. El alcance, los usos y el procedimiento de control se detallan en el Anexo J de la tesis.
