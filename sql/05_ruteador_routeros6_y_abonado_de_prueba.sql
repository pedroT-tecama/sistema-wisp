-- =====================================================================
-- 05_ruteador_routeros6_y_abonado_de_prueba.sql
-- Agrega un ruteador con RouterOS 6 y un abonado de prueba en él.
--
-- Qué hace:
--   1. Registra el ruteador AP NetBox (192.168.5.14, RouterOS 6.48.4).
--      Es un punto de acceso inalámbrico que enruta su propia LAN de
--      clientes (192.168.4.0/24), por eso se registra como ROUTER.
--      Cuelga de la cabecera del distrito (192.168.5.1).
--   2. Registra un abonado ficticio en ese ruteador: 192.168.4.101, plan
--      de 4M/7M, con su cola simple de prueba ya creada en el equipo
--      ("CLIENTE ANTENA", max-limit 4M/7M).
--   Sirve para verificar el corte y la reactivación en RouterOS 6 (IOV de
--   R3.1: escenarios en ruteadores con RouterOS 6 y 7).
--
-- Datos del abonado: se calculan como lo hace el registro del sistema
--   (registrar_cliente_nuevo): fecha de registro = hoy, primer vencimiento
--   = día siguiente, día de pago = día de ese vencimiento, estado ACTIVO.
--   Al insertarse por script no genera orden de alta; su cola ya tiene
--   las velocidades del plan.
--
-- Cuándo se ejecuta:
--   Una sola vez, después de los scripts 01 a 04, sobre wisp_db.
--   Si se ejecuta dos veces, MySQL lo rechaza por las restricciones UNIQUE.
--
-- Con qué se relaciona:
--   - sql/02_carga_inicial.sql: cabecera del distrito (192.168.5.1).
--   - app/models.py: RouterNode y Cliente (Anexo H).
-- =====================================================================

USE wisp_db;
START TRANSACTION;

-- Cabecera del distrito: el nodo raíz con IP 192.168.5.1
SET @cabecera := (SELECT id FROM router_node WHERE ip_router = '192.168.5.1');
SET @master   := (SELECT master_id FROM router_node WHERE id = @cabecera);

-- 1. Ruteador AP NetBox (RouterOS 6), cuelga de la cabecera
INSERT INTO router_node (master_id, padre_id, nombre_equipo, tipo_nodo, ip_router,
                         puerto_socket, version_routeros, estado_operativo) VALUES
    (@master, @cabecera, 'AP NetBox', 'ROUTER', '192.168.5.14', 8005, '6.48.4', 'CHECK_OK');

SET @ap   := (SELECT id FROM router_node WHERE master_id = @master AND ip_router = '192.168.5.14');
SET @plan := (SELECT id FROM perfil_tarifa WHERE rate_upload = '4M' AND rate_download = '7M' LIMIT 1);

-- 2. Abonado ficticio de prueba en el AP NetBox
INSERT INTO cliente (router_id, tarifa_id, nombres, apellidos, dni, direccion, ip_cliente,
                     estado, fecha_registro, fecha_vencimiento, dia_pago, saldo_dias_favor) VALUES
    (@ap, @plan, 'Prueba', 'RouterOS6 AP', '48004101', 'Jr. Prueba 4101', '192.168.4.101',
     'ACTIVO', '2026-11-09', '2026-11-10', 10, 0);

COMMIT;

-- Verificación
SELECT id, padre_id, nombre_equipo, tipo_nodo, ip_router, puerto_socket, version_routeros
FROM router_node ORDER BY id;
SELECT c.id, c.nombres, c.apellidos, c.ip_cliente, r.nombre_equipo AS ruteador, t.nombre_plan AS plan,
       c.estado, DATE_FORMAT(c.fecha_vencimiento,'%d/%m/%Y') AS vencimiento, c.dia_pago
FROM cliente c JOIN router_node r ON r.id = c.router_id JOIN perfil_tarifa t ON t.id = c.tarifa_id
WHERE c.router_id = @ap;
