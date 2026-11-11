-- =====================================================================
-- 07_renombrar_ip_router.sql
-- Renombra la columna router_node.ip_gestion_ospf a ip_router.
--
-- Qué hace:
--   La columna guardaba la IP del ruteador, con la que el sistema lo
--   gestiona por la API (cortes, reactivaciones, consulta de colas). Su
--   nombre se reserva para la dirección que el ruteador anuncia en OSPF
--   (bandera /32), que se agrega en un script posterior. Este script solo
--   cambia el nombre: los datos y la restricción UNIQUE (master_id, ip)
--   se conservan.
--
-- Cuándo se ejecuta:
--   Una sola vez, en wisp_db y en wisp_test, en bases creadas antes de este
--   ajuste. Las instalaciones nuevas ya crean la columna ip_router en el
--   script 01.
--
-- Con qué se relaciona:
--   - sql/01_crear_esquema.sql: definición de router_node.
--   - app/models.py: RouterNode.ip_router.
-- =====================================================================

ALTER TABLE wisp_db.router_node   RENAME COLUMN ip_gestion_ospf TO ip_router;
ALTER TABLE wisp_test.router_node RENAME COLUMN ip_gestion_ospf TO ip_router;

-- Verificación
SELECT id, nombre_equipo, ip_router, puerto_socket FROM wisp_db.router_node ORDER BY id;
SHOW COLUMNS FROM wisp_test.router_node LIKE 'ip_%';
