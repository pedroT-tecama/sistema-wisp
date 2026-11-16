-- ============================================================================
-- consultas_monitoreo.sql
-- Consultas de revisión del monitoreo (solo lectura; no modifican datos).
-- Se ejecutan sobre wisp_db en MySQL Workbench o en la extensión SQL de VS Code.
--
-- Con qué se relaciona:
--   - router_node y registro_alerta las actualiza app/monitoreo.py
--     (MotorTelemetriaProactiva) en cada vuelta del monitoreo.
--   - Sirven como evidencia de las pruebas en vivo (Anexo K).
-- ============================================================================

USE wisp_db;

-- 1. Ruteadores con su bandera OSPF, su ruteador superior y su estado.
--    NODO_CAIDO = su bandera /32 no está en la tabla de rutas de la cabecera.
SELECT  r.id,
        r.nombre_equipo                       AS ruteador,
        r.ip_router                           AS ip_gestion,
        r.ip_gestion_ospf                     AS bandera_ospf,
        p.nombre_equipo                       AS ruteador_superior,
        r.estado_operativo                    AS estado
FROM    router_node r
LEFT JOIN router_node p ON p.id = r.padre_id
ORDER BY r.master_id, r.id;

-- 2. Alertas con fecha y hora, en columnas cortas.
--    La descripción se recorta a 90 caracteres; el texto completo está en la consulta 3.
SELECT  a.id_alerta                                           AS id,
        a.prefijo_excepcion                                   AS tipo,
        COALESCE(r.nombre_equipo, e.nombre_enlace, CONCAT('Cabecera, distrito ', a.master_id)) AS origen,
        DATE_FORMAT(a.fecha_registro,   '%d/%m %H:%i:%s')     AS registro,
        COALESCE(DATE_FORMAT(a.fecha_resolucion, '%d/%m %H:%i:%s'), 'ABIERTA') AS resolucion,
        LEFT(a.descripcion_error, 90)                         AS descripcion
FROM    registro_alerta a
LEFT JOIN router_node r ON r.id = a.router_id
LEFT JOIN enlace_backhaul_ptp e ON e.id = a.enlace_id
ORDER BY a.id_alerta DESC;

-- 3. Texto completo de una alerta (cambiar el número por el id que se quiera ver).
SELECT  id_alerta, prefijo_excepcion, descripcion_error
FROM    registro_alerta
WHERE   id_alerta = 7;

-- 4. Alertas abiertas en este momento (fallas aún no resueltas).
SELECT  a.id_alerta AS id, a.prefijo_excepcion AS tipo,
        COALESCE(r.nombre_equipo, CONCAT('Cabecera, distrito ', a.master_id)) AS origen,
        DATE_FORMAT(a.fecha_registro, '%d/%m %H:%i:%s') AS desde
FROM    registro_alerta a
LEFT JOIN router_node r ON r.id = a.router_id
WHERE   a.fecha_resolucion IS NULL
ORDER BY a.fecha_registro;

-- 5. Duración de cada falla ya resuelta (de la alerta a su cierre).
SELECT  a.id_alerta AS id, a.prefijo_excepcion AS tipo,
        COALESCE(r.nombre_equipo, CONCAT('Cabecera, distrito ', a.master_id)) AS origen,
        TIMEDIFF(a.fecha_resolucion, a.fecha_registro) AS duracion
FROM    registro_alerta a
LEFT JOIN router_node r ON r.id = a.router_id
WHERE   a.fecha_resolucion IS NOT NULL
ORDER BY a.id_alerta;

-- 6. Enlaces troncales con su umbral y su última lectura de señal.
SELECT  e.id, e.nombre_enlace AS enlace, e.ip_antena_destino AS antena,
        e.rssi_minimo_esperado AS umbral_dbm,
        (SELECT l.rssi_medido FROM lectura_senal_enlace l
          WHERE l.enlace_id = e.id ORDER BY l.id DESC LIMIT 1) AS ultima_dbm,
        (SELECT DATE_FORMAT(MAX(l.fecha_hora), '%d/%m %H:%i:%s') FROM lectura_senal_enlace l
          WHERE l.enlace_id = e.id) AS ultima_lectura
FROM    enlace_backhaul_ptp e
ORDER BY e.id;

-- 7. Últimas 10 lecturas de un enlace (cambiar el número por el id del enlace).
SELECT  id, rssi_medido AS dbm, DATE_FORMAT(fecha_hora, '%d/%m %H:%i:%s') AS hora
FROM    lectura_senal_enlace
WHERE   enlace_id = 1
ORDER BY id DESC
LIMIT 10;
