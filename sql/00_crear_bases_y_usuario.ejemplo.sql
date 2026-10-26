-- =====================================================================
--  Script 00: creación de las bases de datos y del usuario de la aplicación
--  Ejecutar UNA SOLA VEZ, conectado como root (MySQL Workbench).
--
--  Este archivo es la PLANTILLA que se publica en el repositorio.
--  Para usarlo: copiarlo como 00_crear_bases_y_usuario.sql, reemplazar
--  __CLAVE_WISP_APP__ por una clave propia y colocar la misma clave en
--  DB_URL dentro del archivo .env. La copia con la clave real no se
--  publica (está en .gitignore).
-- =====================================================================

-- Base de operación y base de pruebas independiente (sección 6.6)
CREATE DATABASE IF NOT EXISTS wisp_db
    DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS wisp_test
    DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci;

-- Usuario propio de la aplicación (no se usa root desde el programa)
CREATE USER IF NOT EXISTS 'wisp_app'@'localhost' IDENTIFIED BY '__CLAVE_WISP_APP__';
CREATE USER IF NOT EXISTS 'wisp_app'@'127.0.0.1' IDENTIFIED BY '__CLAVE_WISP_APP__';

-- Base de operación: solo lectura y escritura de datos
GRANT SELECT, INSERT, UPDATE, DELETE ON wisp_db.*   TO 'wisp_app'@'localhost', 'wisp_app'@'127.0.0.1';
-- Base de pruebas: permisos completos (las pruebas crean y limpian datos)
GRANT ALL PRIVILEGES                  ON wisp_test.* TO 'wisp_app'@'localhost', 'wisp_app'@'127.0.0.1';

-- Verificación
SHOW DATABASES LIKE 'wisp%';
SHOW GRANTS FOR 'wisp_app'@'localhost';
