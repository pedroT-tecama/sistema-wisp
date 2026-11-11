-- =====================================================================
-- 06_ruteador_torre6_y_enlace.sql
-- Agrega el ruteador Condominio 1 - Torre 6 y su radioenlace con la cabecera,
-- y corrige el ruteador padre de Condominio 1 - Torre 3.
--
-- Qué hace:
--   1. Registra el ruteador Condominio 1 - Torre 6 (192.168.5.33, RouterOS 7.20.4).
--      Cuelga de la cabecera del distrito (192.168.5.1).
--   2. Registra el radioenlace troncal cabecera -> Torre 6: antena de origen
--      192.168.5.31 (lado de la cabecera) y antena de destino 192.168.5.32,
--      que baja por cable a Torre 6. Señal mínima aceptable: -68 dBm.
--   3. Corrige la cascada: Condominio 1 - Torre 3 (192.168.108.2) cuelga de
--      Torre 6 (por su puerto 192.168.108.1), no de Condominio 1 - E7, como
--      se había registrado en el script 04.
--
--   Topología resultante (radioenlaces troncales: 3):
--     Cabecera (5.1) --antenas 5.41/5.42--> Condominio 1 - E7 (5.43)
--     Cabecera (5.1) --antenas 5.31/5.32--> Condominio 1 - Torre 6 (5.33)
--                                               | cable (108.1 -> 108.2)
--                                         Condominio 1 - Torre 3 (108.2)
--                                               | antenas 112.2 -> 112.3
--                                         Condominio 3 - Torre 5 (112.4)
--
-- Cuándo se ejecuta:
--   Una sola vez, después de los scripts 01 a 05, sobre wisp_db.
--   Si se ejecuta dos veces, MySQL lo rechaza por las restricciones UNIQUE.
--
-- Con qué se relaciona:
--   - sql/02_carga_inicial.sql: cabecera y radioenlace hacia E7.
--   - sql/04_ruteadores_y_enlaces_adicionales.sql: Torre 3, Torre 5 y su radioenlace.
--   - app/models.py: RouterNode y EnlaceBackhaulPTP (Anexo H).
-- =====================================================================

USE wisp_db;
START TRANSACTION;

SET @cabecera := (SELECT id FROM router_node WHERE ip_router = '192.168.5.1');
SET @master   := (SELECT master_id FROM router_node WHERE id = @cabecera);

-- 1. Condominio 1 - Torre 6, cuelga de la cabecera por radioenlace
INSERT INTO router_node (master_id, padre_id, nombre_equipo, tipo_nodo, ip_router,
                         puerto_socket, version_routeros, estado_operativo) VALUES
    (@master, @cabecera, 'Condominio 1 - Torre 6', 'ROUTER', '192.168.5.33', 8006, '7.20.4', 'CHECK_OK');

SET @torre6 := (SELECT id FROM router_node WHERE master_id = @master AND ip_router = '192.168.5.33');

-- 2. Radioenlace troncal cabecera -> Torre 6
INSERT INTO enlace_backhaul_ptp (router_origen_id, router_destino_id, nombre_enlace,
                                 ip_antena_origen, ip_antena_destino,
                                 rssi_minimo_esperado, frecuencia_operacion) VALUES
    (@cabecera, @torre6, 'Condominio 1 - Torre 6', '192.168.5.31', '192.168.5.32', -68, NULL);

-- 3. Torre 3 cuelga de Torre 6
UPDATE router_node SET padre_id = @torre6
WHERE master_id = @master AND ip_router = '192.168.108.2';

COMMIT;

-- Verificación
SELECT r.id, r.nombre_equipo, r.ip_router, r.version_routeros, p.nombre_equipo AS cuelga_de
FROM router_node r LEFT JOIN router_node p ON p.id = r.padre_id ORDER BY r.id;
SELECT e.id, o.nombre_equipo AS origen, d.nombre_equipo AS destino, e.ip_antena_origen,
       e.ip_antena_destino, e.rssi_minimo_esperado
FROM enlace_backhaul_ptp e
JOIN router_node o ON o.id = e.router_origen_id
JOIN router_node d ON d.id = e.router_destino_id ORDER BY e.id;
