-- =====================================================================
--  Sistema de gestión comercial y control MikroTik para WISP
--  Script 01: creación del esquema (tablas, claves, restricciones, índices)
--  Fuente: Anexo H - Diccionario de Base de Datos (PFC2, revisión 4)
--  Motor: MySQL 8.4 LTS  |  Motor de tablas: InnoDB  |  Juego de caracteres: utf8mb4
--
--  Uso: ejecutar UNA VEZ por cada base de datos, con la base seleccionada.
--       1) USE wisp_db;    luego este script
--       2) USE wisp_test;  luego este script
--  Las bases y el usuario de la aplicación se crean antes con el script 00.
--
--  Decisiones de diseño aplicadas (registradas en Control_cambios_tesis.docx):
--   C-01  caja_ingreso.cliente_id referencia a cliente.id (corrige errata del Anexo H).
--   C-02  Todas las claves foráneas usan RESTRICT: no se permite borrar ni
--         modificar un registro del que dependen otros (pagos, órdenes, historial).
--         En las tablas con restricción CHECK sobre columnas de clave foránea
--         (enlace_backhaul_ptp y registro_alerta) se omite la cláusula explícita:
--         MySQL 8 no admite acciones referenciales sobre esas columnas, y su
--         comportamiento por defecto en InnoDB ya es RESTRICT.
--   C-03  registro_alerta.fecha_registro toma la fecha y hora actual por defecto.
--   C-04  Un enlace troncal no puede tener el mismo ruteador como origen y destino.
-- =====================================================================

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------
-- 1. router_master: cabeceras distritales
-- ---------------------------------------------------------------------
CREATE TABLE router_master (
    id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
    nombre_distrito   VARCHAR(80)       NOT NULL,
    ddns_url          VARCHAR(255)      NOT NULL,
    puerto_base       SMALLINT UNSIGNED NOT NULL,
    version_routeros  VARCHAR(10)       NULL,
    CONSTRAINT pk_router_master PRIMARY KEY (id),
    CONSTRAINT uq_router_master_distrito UNIQUE (nombre_distrito)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'Clase RouterMaster. Cabeceras distritales.';

-- ---------------------------------------------------------------------
-- 2. router_node: ruteadores de borde y puntos de acceso
-- ---------------------------------------------------------------------
CREATE TABLE router_node (
    id                INT UNSIGNED      NOT NULL AUTO_INCREMENT,
    master_id         INT UNSIGNED      NOT NULL,
    padre_id          INT UNSIGNED      NULL,
    nombre_equipo     VARCHAR(80)       NOT NULL,
    tipo_nodo         ENUM('ROUTER','ACCESS_POINT') NOT NULL,
    ip_gestion_ospf   VARCHAR(15)       NOT NULL,
    puerto_socket     SMALLINT UNSIGNED NOT NULL,
    version_routeros  VARCHAR(10)       NULL,
    estado_operativo  ENUM('CHECK_OK','NODO_CAIDO') NOT NULL DEFAULT 'CHECK_OK',
    CONSTRAINT pk_router_node PRIMARY KEY (id),
    CONSTRAINT uq_router_node_ip     UNIQUE (master_id, ip_gestion_ospf),
    CONSTRAINT uq_router_node_puerto UNIQUE (master_id, puerto_socket),
    CONSTRAINT fk_router_node_master FOREIGN KEY (master_id)
        REFERENCES router_master (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_router_node_padre FOREIGN KEY (padre_id)
        REFERENCES router_node (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'Clase RouterNode. Ruteadores de borde y puntos de acceso.';

-- ---------------------------------------------------------------------
-- 3. enlace_backhaul_ptp: enlaces troncales punto a punto
-- ---------------------------------------------------------------------
CREATE TABLE enlace_backhaul_ptp (
    id                    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    router_origen_id      INT UNSIGNED  NOT NULL,
    router_destino_id     INT UNSIGNED  NOT NULL,
    nombre_enlace         VARCHAR(80)   NOT NULL,
    ip_antena_origen      VARCHAR(15)   NOT NULL,
    ip_antena_destino     VARCHAR(15)   NOT NULL,
    rssi_minimo_esperado  SMALLINT      NOT NULL,
    frecuencia_operacion  VARCHAR(20)   NULL,
    CONSTRAINT pk_enlace_backhaul_ptp PRIMARY KEY (id),
    -- C-02: sin cláusula explícita (RESTRICT por defecto) por el CHECK C-04
    CONSTRAINT fk_enlace_origen  FOREIGN KEY (router_origen_id)  REFERENCES router_node (id),
    CONSTRAINT fk_enlace_destino FOREIGN KEY (router_destino_id) REFERENCES router_node (id),
    -- C-04
    CONSTRAINT ck_enlace_extremos_distintos CHECK (router_origen_id <> router_destino_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'Clase EnlaceBackhaulPTP. Enlaces troncales punto a punto.';

-- ---------------------------------------------------------------------
-- 3.1 lectura_senal_enlace: historial de lecturas de señal
-- ---------------------------------------------------------------------
CREATE TABLE lectura_senal_enlace (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    enlace_id    INT UNSIGNED    NOT NULL,
    rssi_medido  SMALLINT        NOT NULL,
    fecha_hora   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_lectura_senal_enlace PRIMARY KEY (id),
    INDEX ix_lectura_enlace_fecha (enlace_id, fecha_hora),
    CONSTRAINT fk_lectura_enlace FOREIGN KEY (enlace_id)
        REFERENCES enlace_backhaul_ptp (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'Clase LecturaSenalEnlace. Historial de lecturas de señal.';

-- ---------------------------------------------------------------------
-- 4. perfil_tarifa: catálogo de planes
-- ---------------------------------------------------------------------
CREATE TABLE perfil_tarifa (
    id              INT UNSIGNED   NOT NULL AUTO_INCREMENT,
    nombre_plan     VARCHAR(60)    NOT NULL,
    precio_mensual  DECIMAL(10,2)  NOT NULL,
    rate_upload     VARCHAR(10)    NOT NULL,
    rate_download   VARCHAR(10)    NOT NULL,
    CONSTRAINT pk_perfil_tarifa PRIMARY KEY (id),
    CONSTRAINT uq_perfil_tarifa_nombre UNIQUE (nombre_plan)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'Clase PerfilTarifa. Catálogo de planes.';

-- ---------------------------------------------------------------------
-- 5. cliente: abonados del ISP
-- ---------------------------------------------------------------------
CREATE TABLE cliente (
    id                    INT UNSIGNED      NOT NULL AUTO_INCREMENT,
    router_id             INT UNSIGNED      NOT NULL,
    tarifa_id             INT UNSIGNED      NOT NULL,
    nombres               VARCHAR(40)       NOT NULL,
    apellidos             VARCHAR(40)       NOT NULL,
    dni                   VARCHAR(12)       NOT NULL,
    direccion             VARCHAR(150)      NOT NULL,
    ip_cliente            VARCHAR(15)       NOT NULL,
    mac_cliente           VARCHAR(17)       NULL,
    estado                ENUM('ACTIVO','PENDIENTE_SUSPENSION','SUSPENDIDO') NOT NULL DEFAULT 'ACTIVO',
    fecha_vencimiento     DATE              NOT NULL,
    fecha_corte_efectivo  DATE              NULL,
    saldo_dias_favor      SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    CONSTRAINT pk_cliente PRIMARY KEY (id),
    CONSTRAINT uq_cliente_router_ip UNIQUE (router_id, ip_cliente),
    INDEX ix_cliente_apellidos (apellidos),
    INDEX ix_cliente_dni (dni),
    CONSTRAINT fk_cliente_router FOREIGN KEY (router_id)
        REFERENCES router_node (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_cliente_tarifa FOREIGN KEY (tarifa_id)
        REFERENCES perfil_tarifa (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'Clase Cliente. Abonados del ISP.';

-- ---------------------------------------------------------------------
-- 6. caja_ingreso: pagos registrados
-- ---------------------------------------------------------------------
CREATE TABLE caja_ingreso (
    id              INT UNSIGNED   NOT NULL AUTO_INCREMENT,
    cliente_id      INT UNSIGNED   NOT NULL,
    monto           DECIMAL(10,2)  NOT NULL,
    medio_pago      VARCHAR(30)    NOT NULL,
    fecha_registro  DATE           NOT NULL,
    CONSTRAINT pk_caja_ingreso PRIMARY KEY (id),
    -- C-01: referencia a cliente.id
    CONSTRAINT fk_caja_cliente FOREIGN KEY (cliente_id)
        REFERENCES cliente (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'Clase CajaIngreso. Pagos registrados.';

-- ---------------------------------------------------------------------
-- 7. tarea_pendiente_red: cola de órdenes pendientes
-- ---------------------------------------------------------------------
CREATE TABLE tarea_pendiente_red (
    id                      INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    router_id               INT UNSIGNED  NOT NULL,
    cliente_id              INT UNSIGNED  NOT NULL,
    accion                  ENUM('CORTE','ACTIVACION') NOT NULL,
    payload_parametros_red  JSON          NOT NULL,
    intentos                INT UNSIGNED  NOT NULL DEFAULT 0,
    estado                  ENUM('PENDIENTE','PROCESADO','ANULADO') NOT NULL DEFAULT 'PENDIENTE',
    fecha_creacion          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_tarea_pendiente_red PRIMARY KEY (id),
    INDEX ix_tarea_estado_cliente (estado, cliente_id),
    CONSTRAINT fk_tarea_router FOREIGN KEY (router_id)
        REFERENCES router_node (id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_tarea_cliente FOREIGN KEY (cliente_id)
        REFERENCES cliente (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'Clase TareaPendienteRed. Cola de órdenes pendientes.';

-- ---------------------------------------------------------------------
-- 8. registro_alerta: fallas detectadas por el monitoreo
-- ---------------------------------------------------------------------
CREATE TABLE registro_alerta (
    id_alerta          INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    prefijo_excepcion  ENUM('OSPF_RUTA_AUSENTE','PTP_DEGRADADO','CABECERA_INACCESIBLE') NOT NULL,
    master_id          INT UNSIGNED  NULL,
    router_id          INT UNSIGNED  NULL,
    enlace_id          INT UNSIGNED  NULL,
    descripcion_error  VARCHAR(500)  NOT NULL,
    fecha_registro     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- C-03
    fecha_resolucion   DATETIME      NULL,
    CONSTRAINT pk_registro_alerta PRIMARY KEY (id_alerta),
    -- C-02: sin cláusula explícita (RESTRICT por defecto) por el CHECK de origen único
    CONSTRAINT fk_alerta_master FOREIGN KEY (master_id) REFERENCES router_master (id),
    CONSTRAINT fk_alerta_router FOREIGN KEY (router_id) REFERENCES router_node (id),
    CONSTRAINT fk_alerta_enlace FOREIGN KEY (enlace_id) REFERENCES enlace_backhaul_ptp (id),
    -- Exactamente una de las tres columnas de origen tiene valor (Anexo H)
    CONSTRAINT ck_alerta_origen_unico CHECK (
        (master_id IS NOT NULL) + (router_id IS NOT NULL) + (enlace_id IS NOT NULL) = 1
    )
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci
  COMMENT = 'Clase RegistroAlerta. Fallas detectadas por el monitoreo.';

-- Verificación: debe listar 9 tablas
SHOW TABLES;
