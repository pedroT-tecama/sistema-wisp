-- =====================================================================
-- 08_ip_gestion_ospf_bandera.sql
-- Agrega a router_node la columna ip_gestion_ospf: la bandera OSPF del ruteador.
--
-- Qué hace:
--   La bandera es una dirección /32 propia de cada ruteador, configurada en
--   un bridge sin puertos (loopback) y anunciada en OSPF como interfaz pasiva.
--   Solo ese ruteador la anuncia: si cae o deja de participar en OSPF, la
--   bandera desaparece de la tabla de rutas de la cabecera. El monitoreo
--   compara esta columna con esa tabla para detectar los ruteadores caídos.
--   No se usa para gestionar el ruteador (eso se hace con ip_router).
--
--   - Puede quedar vacía: la cabecera no tiene bandera (es la que observa)
--     y un ruteador sin bandera configurada no se vigila.
--   - No se repite dentro del mismo distrito (UNIQUE con master_id; MySQL
--     admite varias filas vacías).
--   - Se llena con las banderas ya configuradas en la red de pruebas.
--     E7 (192.168.5.43) queda vacía hasta configurar la suya.
--
-- Cuándo se ejecuta:
--   Una sola vez, después del script 07. Agrega la columna en wisp_db y en
--   wisp_test, y llena las banderas solo en wisp_db. Las instalaciones
--   nuevas ya la crean en el script 01.
--
-- Con qué se relaciona:
--   - sql/01_crear_esquema.sql: definición de router_node.
--   - app/models.py: RouterNode.ip_gestion_ospf.
--   - Anexo H: diccionario de datos (ip_gestion_ospf).
-- =====================================================================

ALTER TABLE wisp_db.router_node
    ADD COLUMN ip_gestion_ospf VARCHAR(15) NULL AFTER ip_router,
    ADD CONSTRAINT uq_router_node_ospf UNIQUE (master_id, ip_gestion_ospf);

ALTER TABLE wisp_test.router_node
    ADD COLUMN ip_gestion_ospf VARCHAR(15) NULL AFTER ip_router,
    ADD CONSTRAINT uq_router_node_ospf UNIQUE (master_id, ip_gestion_ospf);

-- Banderas configuradas en los ruteadores de la red de pruebas
UPDATE wisp_db.router_node SET ip_gestion_ospf = '10.0.5.33'  WHERE ip_router = '192.168.5.33';
UPDATE wisp_db.router_node SET ip_gestion_ospf = '10.0.108.2' WHERE ip_router = '192.168.108.2';
UPDATE wisp_db.router_node SET ip_gestion_ospf = '10.0.112.4' WHERE ip_router = '192.168.112.4';
UPDATE wisp_db.router_node SET ip_gestion_ospf = '10.0.5.14'  WHERE ip_router = '192.168.5.14';

-- Verificación
SELECT id, nombre_equipo, ip_router, ip_gestion_ospf, puerto_socket FROM wisp_db.router_node ORDER BY id;
SHOW COLUMNS FROM wisp_test.router_node LIKE 'ip_%';
