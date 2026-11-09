-- =====================================================================
-- 04_ruteadores_y_enlaces_adicionales.sql
-- Agrega dos ruteadores de borde y un enlace troncal al distrito de prueba.
--
-- Qué hace:
--   Completa la topología de la red del caso de estudio que usan las
--   pruebas de cortes y el monitoreo OSPF:
--
--     Cabecera (5.1) --antenas 5.41/5.42--> Condominio 1 - E7 (5.43)   [script 02]
--                                               | cable (108.1 -> 108.2)
--                                         Condominio 1 - Torre 3 (108.2) [nuevo]
--                                               | antenas 112.2 -> 112.3  [enlace nuevo]
--                                         Condominio 3 - Torre 5 (112.4) [nuevo]
--
--   - Los dos ruteadores nuevos tienen RouterOS 7 (7.13.3 y 7.8).
--   - El tramo 108.1 -> 108.2 es cable: no se registra como enlace troncal
--     (esa tabla es para radioenlaces cuya señal se mide); si se corta, lo
--     detecta el monitoreo OSPF.
--   - El radioenlace 112.2 -> 112.3 (MikroTik en ambos lados) se registra con
--     -68 dBm como señal mínima aceptable.
--   - Los puertos 8003 y 8004 solo cumplen la regla de unicidad de la base:
--     con MK_MODO_CONEXION=directo el sistema se conecta a la IP de gestión.
--   - Los nombres de las zonas no son los reales (discreción del caso de estudio).
--
-- Cuándo se ejecuta:
--   Una sola vez, después de los scripts 01, 02 y 03. El script selecciona
--   wisp_db por sí mismo (USE wisp_db).
--   Si se ejecuta dos veces, MySQL lo rechaza por las restricciones UNIQUE
--   (misma IP o mismo puerto en el distrito) y no duplica nada.
--   Los abonados de prueba de estos ruteadores se registran después desde
--   /docs (POST /abonados), no en este script.
--
-- Con qué se relaciona:
--   - sql/02_carga_inicial.sql: cabecera y ruteador Condominio 1 - E7.
--   - app/models.py: RouterNode y EnlaceBackhaulPTP (Anexo H).
-- =====================================================================

USE wisp_db;                       -- se ejecuta siempre sobre la base de operación
START TRANSACTION;

-- La cabecera se obtiene del ruteador Condominio 1 - E7, ya registrado en el script 02
SET @nodo_e7 := (SELECT id FROM router_node WHERE ip_gestion_ospf = '192.168.5.43');
SET @master  := (SELECT master_id FROM router_node WHERE id = @nodo_e7);

-- 1. Condominio 1 - Torre 3: cuelga de E7 por cable
INSERT INTO router_node (master_id, padre_id, nombre_equipo, tipo_nodo, ip_gestion_ospf,
                         puerto_socket, version_routeros, estado_operativo) VALUES
    (@master, @nodo_e7, 'Condominio 1 - Torre 3', 'ROUTER', '192.168.108.2', 8003, '7.13.3', 'CHECK_OK');

SET @nodo_torre3 := (SELECT id FROM router_node
                     WHERE master_id = @master AND ip_gestion_ospf = '192.168.108.2');

-- 2. Condominio 3 - Torre 5: cuelga de Torre 3 por radioenlace
INSERT INTO router_node (master_id, padre_id, nombre_equipo, tipo_nodo, ip_gestion_ospf,
                         puerto_socket, version_routeros, estado_operativo) VALUES
    (@master, @nodo_torre3, 'Condominio 3 - Torre 5', 'ROUTER', '192.168.112.4', 8004, '7.8', 'CHECK_OK');

SET @nodo_torre5 := (SELECT id FROM router_node
                     WHERE master_id = @master AND ip_gestion_ospf = '192.168.112.4');

-- 3. Radioenlace troncal Torre 3 -> Torre 5 (antenas MikroTik, umbral -68 dBm)
INSERT INTO enlace_backhaul_ptp (router_origen_id, router_destino_id, nombre_enlace,
                                 ip_antena_origen, ip_antena_destino,
                                 rssi_minimo_esperado, frecuencia_operacion) VALUES
    (@nodo_torre3, @nodo_torre5, 'Condominio 3 - Torre 5',
     '192.168.112.2', '192.168.112.3', -68, NULL);

COMMIT;

-- Verificación
SELECT id, padre_id, nombre_equipo, ip_gestion_ospf, version_routeros FROM router_node ORDER BY id;
SELECT id, router_origen_id, router_destino_id, nombre_enlace, ip_antena_origen, ip_antena_destino,
       rssi_minimo_esperado FROM enlace_backhaul_ptp ORDER BY id;
