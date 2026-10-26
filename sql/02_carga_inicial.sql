-- =====================================================================
--  Sistema de gestión comercial y control MikroTik para WISP
--  Script 02: carga inicial de datos maestros (sección 6.6)
--  Planes de servicio, cabecera distrital, ruteadores y enlace troncal
--  del escenario de pruebas (red del distrito Bellavista Sector 2).
--
--  Uso: ejecutar UNA VEZ sobre wisp_db (clic derecho en wisp_db >
--       Set As Current Database Schema, luego Run).
--       La base wisp_test no se carga aquí: sus datos los crean las pruebas.
--
--  Decisiones aplicadas (Control_cambios_tesis.docx):
--   C-05  El ruteador de la cabecera se registra también en router_node
--         como nodo raíz del distrito (padre_id nulo), para que los enlaces
--         troncales que parten de la cabecera puedan registrarse.
--   P-07  Acceso local: el sistema se conecta a cada ruteador por su IP de
--         gestión y el puerto 8728. puerto_socket conserva el puerto que le
--         correspondería en el mapeo de la cabecera (rango 8001-8050 del Anexo G) y no se
--         usa en las pruebas locales.
-- =====================================================================

SET NAMES utf8mb4;
START TRANSACTION;

-- ---------------------------------------------------------------------
-- 1. Planes de servicio (velocidades en formato RouterOS)
-- ---------------------------------------------------------------------
INSERT INTO perfil_tarifa (nombre_plan, precio_mensual, rate_upload, rate_download) VALUES
    ('Plan Básico',   50.00, '4M', '7M'),
    ('Plan Estrella', 60.00, '6M', '10M'),
    ('Plan Familiar', 70.00, '8M', '14M');

-- ---------------------------------------------------------------------
-- 2. Cabecera distrital
-- ---------------------------------------------------------------------
INSERT INTO router_master (nombre_distrito, ddns_url, puerto_base, version_routeros) VALUES
    ('Bellavista Sector 2', '192.168.5.1', 8001, '6.48.3');

SET @master := (SELECT id FROM router_master WHERE nombre_distrito = 'Bellavista Sector 2');

-- ---------------------------------------------------------------------
-- 3. Ruteadores
-- ---------------------------------------------------------------------
-- 3.1 Ruteador de la cabecera como nodo raíz (C-05)
INSERT INTO router_node (master_id, padre_id, nombre_equipo, tipo_nodo, ip_gestion_ospf,
                         puerto_socket, version_routeros, estado_operativo) VALUES
    (@master, NULL, 'Cabecera Bellavista Sector 2', 'ROUTER', '192.168.5.1', 8001, '6.48.3', 'CHECK_OK');

SET @nodo_cabecera := (SELECT id FROM router_node
                       WHERE master_id = @master AND ip_gestion_ospf = '192.168.5.1');

-- 3.2 Ruteador de borde conectado a la cabecera por el enlace PTP
INSERT INTO router_node (master_id, padre_id, nombre_equipo, tipo_nodo, ip_gestion_ospf,
                         puerto_socket, version_routeros, estado_operativo) VALUES
    (@master, @nodo_cabecera, 'Villanova 1 - E7', 'ROUTER', '192.168.5.43', 8002, '7.21.4', 'CHECK_OK');

SET @nodo_villanova := (SELECT id FROM router_node
                        WHERE master_id = @master AND ip_gestion_ospf = '192.168.5.43');

-- ---------------------------------------------------------------------
-- 4. Enlace troncal punto a punto (antenas MikroTik MIMO, umbral -68 dBm)
-- ---------------------------------------------------------------------
INSERT INTO enlace_backhaul_ptp (router_origen_id, router_destino_id, nombre_enlace,
                                 ip_antena_origen, ip_antena_destino,
                                 rssi_minimo_esperado, frecuencia_operacion) VALUES
    (@nodo_cabecera, @nodo_villanova, 'Villanova 1 - E7',
     '192.168.5.41', '192.168.5.42', -68, NULL);

COMMIT;

-- ---------------------------------------------------------------------
-- Verificación
-- ---------------------------------------------------------------------
SELECT id, nombre_plan, precio_mensual, rate_upload, rate_download FROM perfil_tarifa;

SELECT n.id, n.nombre_equipo, n.ip_gestion_ospf, n.version_routeros,
       p.nombre_equipo AS depende_de, m.nombre_distrito
FROM router_node n
JOIN router_master m ON m.id = n.master_id
LEFT JOIN router_node p ON p.id = n.padre_id;

SELECT e.nombre_enlace, o.nombre_equipo AS origen, d.nombre_equipo AS destino,
       e.ip_antena_origen, e.ip_antena_destino, e.rssi_minimo_esperado
FROM enlace_backhaul_ptp e
JOIN router_node o ON o.id = e.router_origen_id
JOIN router_node d ON d.id = e.router_destino_id;
