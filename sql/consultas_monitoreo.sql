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

-- 8. Enlaces troncales registrados, con los ruteadores que unen y sus antenas.
SELECT  e.id, e.nombre_enlace AS enlace,
        o.nombre_equipo AS ruteador_origen, d.nombre_equipo AS ruteador_destino,
        e.ip_antena_origen AS antena_emisora, e.ip_antena_destino AS antena_receptora,
        e.rssi_minimo_esperado AS umbral_dbm
FROM    enlace_backhaul_ptp e
JOIN    router_node o ON o.id = e.router_origen_id
JOIN    router_node d ON d.id = e.router_destino_id
ORDER BY e.id;

-- 9. Alertas de los enlaces: señal degradada (PTP_DEGRADADO) y caídas con probable caída del radioenlace.
SELECT  a.id_alerta AS id, a.prefijo_excepcion AS tipo,
        COALESCE(e.nombre_enlace, r.nombre_equipo) AS origen,
        DATE_FORMAT(a.fecha_registro, '%d/%m %H:%i:%s') AS registro,
        COALESCE(DATE_FORMAT(a.fecha_resolucion, '%d/%m %H:%i:%s'), 'ABIERTA') AS resolucion,
        a.descripcion_error AS descripcion
FROM    registro_alerta a
LEFT JOIN enlace_backhaul_ptp e ON e.id = a.enlace_id
LEFT JOIN router_node r ON r.id = a.router_id
WHERE   a.prefijo_excepcion = 'PTP_DEGRADADO'
   OR   a.descripcion_error LIKE '%radioenlace%'
ORDER BY a.id_alerta DESC;

-- 10. Registro del monitoreo en orden de tiempo (como un log): alertas que se abren,
--     alertas que se cierran y lecturas de señal. Muestra los últimos 50 eventos.
SELECT  DATE_FORMAT(t.hora, '%d/%m %H:%i:%s') AS hora, t.evento, t.origen, t.detalle
FROM (
    SELECT  a.fecha_registro AS hora, CONCAT('ALERTA ', a.prefijo_excepcion) AS evento,
            COALESCE(r.nombre_equipo, e.nombre_enlace, CONCAT('Cabecera, distrito ', a.master_id)) AS origen,
            LEFT(a.descripcion_error, 120) AS detalle
    FROM    registro_alerta a
    LEFT JOIN router_node r ON r.id = a.router_id
    LEFT JOIN enlace_backhaul_ptp e ON e.id = a.enlace_id
    UNION ALL
    SELECT  a.fecha_resolucion, CONCAT('CIERRE ', a.prefijo_excepcion),
            COALESCE(r.nombre_equipo, e.nombre_enlace, CONCAT('Cabecera, distrito ', a.master_id)),
            CONCAT('Resuelta tras ', TIMEDIFF(a.fecha_resolucion, a.fecha_registro))
    FROM    registro_alerta a
    LEFT JOIN router_node r ON r.id = a.router_id
    LEFT JOIN enlace_backhaul_ptp e ON e.id = a.enlace_id
    WHERE   a.fecha_resolucion IS NOT NULL
    UNION ALL
    SELECT  l.fecha_hora, 'LECTURA DE SEÑAL', e.nombre_enlace,
            CONCAT(l.rssi_medido, ' dBm (umbral ', e.rssi_minimo_esperado, ' dBm)',
                   IF(l.rssi_medido < e.rssi_minimo_esperado, ' BAJO EL UMBRAL', ''))
    FROM    lectura_senal_enlace l
    JOIN    enlace_backhaul_ptp e ON e.id = l.enlace_id
) t
ORDER BY t.hora DESC
LIMIT 50;

-- ============================================================================
-- Consultas generales de la red y la operación
-- ============================================================================

-- 11. Distritos (cabeceras) registrados.
SELECT  id, nombre_distrito AS distrito, ddns_url AS acceso, puerto_base, version_routeros AS version
FROM    router_master
ORDER BY id;

-- 12. Ruteadores con todos sus datos: distrito, tipo, versión, IP, bandera, superior y estado.
SELECT  r.id, m.nombre_distrito AS distrito, r.nombre_equipo AS ruteador, r.tipo_nodo AS tipo,
        r.version_routeros AS version, r.ip_router AS ip_gestion, r.ip_gestion_ospf AS bandera_ospf,
        r.puerto_socket AS puerto, COALESCE(p.nombre_equipo, '(cabecera, raíz)') AS ruteador_superior,
        r.estado_operativo AS estado
FROM    router_node r
JOIN    router_master m ON m.id = r.master_id
LEFT JOIN router_node p ON p.id = r.padre_id
ORDER BY r.master_id, r.id;

-- 13. Árbol de la red: cada ruteador con su cadena de superiores hasta la cabecera.
WITH RECURSIVE arbol AS (
    SELECT  id, nombre_equipo, padre_id, 0 AS nivel, CAST(nombre_equipo AS CHAR(500)) AS ruta
    FROM    router_node WHERE padre_id IS NULL
    UNION ALL
    SELECT  r.id, r.nombre_equipo, r.padre_id, a.nivel + 1, CONCAT(a.ruta, ' > ', r.nombre_equipo)
    FROM    router_node r JOIN arbol a ON r.padre_id = a.id
)
SELECT  id, nivel, ruta FROM arbol ORDER BY ruta;

-- 14. Abonados por ruteador y por estado (cuántos clientes depende de cada equipo).
SELECT  r.id, r.nombre_equipo AS ruteador,
        COUNT(c.id) AS abonados,
        SUM(c.estado = 'ACTIVO') AS activos,
        SUM(c.estado = 'PENDIENTE_SUSPENSION') AS por_suspender,
        SUM(c.estado = 'SUSPENDIDO') AS suspendidos
FROM    router_node r
LEFT JOIN cliente c ON c.router_id = r.id
GROUP BY r.id, r.nombre_equipo
ORDER BY r.id;

-- 15. Cola de órdenes: las pendientes y las últimas aplicadas, con su ruteador.
SELECT  t.id, t.accion, t.estado, t.intentos, r.nombre_equipo AS ruteador,
        JSON_UNQUOTE(JSON_EXTRACT(t.payload_parametros_red, '$.ip_cliente')) AS ip_abonado,
        DATE_FORMAT(t.fecha_creacion, '%d/%m %H:%i:%s') AS creada
FROM    tarea_pendiente_red t
JOIN    router_node r ON r.id = t.router_id
ORDER BY (t.estado = 'PENDIENTE') DESC, t.id DESC
LIMIT 30;

-- 16. Incidentes del día, una fila por alerta con la descripción completa (evidencia).
--     Para desde una hora exacta, cambiar CURDATE() por '2026-11-16 04:50'.
SELECT  a.id_alerta AS id, a.prefijo_excepcion AS tipo,
        COALESCE(e.nombre_enlace, r.nombre_equipo, m.nombre_distrito) AS origen,
        DATE_FORMAT(a.fecha_registro, '%d/%m %H:%i:%s') AS registro,
        COALESCE(DATE_FORMAT(a.fecha_resolucion, '%d/%m %H:%i:%s'), 'ABIERTA') AS resolucion,
        a.descripcion_error AS descripcion
FROM    registro_alerta a
LEFT JOIN enlace_backhaul_ptp e ON e.id = a.enlace_id
LEFT JOIN router_node r         ON r.id = a.router_id
LEFT JOIN router_master m       ON m.id = a.master_id
WHERE   a.fecha_registro >= CURDATE()
ORDER BY a.id_alerta DESC;
