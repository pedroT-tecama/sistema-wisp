-- =====================================================================
-- 03_cliente_fecha_registro_dia_pago.sql
-- Agrega a la tabla cliente la fecha de registro y el día de pago.
--
-- Qué hace:
--   - fecha_registro: día en que se instaló y registró al abonado. Queda
--     como dato histórico y no cambia.
--   - dia_pago: día del mes en que vence su pago (1 a 31). Al registrar es
--     el día siguiente al registro. Se mantiene mientras el abonado pague
--     dentro de los días de gracia; solo cambia cuando, tras un corte, el
--     pago recalcula su vencimiento. Si ese día no existe en un mes (por
--     ejemplo, el 31 en noviembre), el vencimiento cae el último día de ese
--     mes, y al mes siguiente vuelve a su día.
--
-- Cuándo se ejecuta:
--   Una sola vez en cada base que ya tiene las tablas: primero en wisp_db y
--   luego en wisp_test. Las instalaciones nuevas no lo necesitan, porque
--   01_crear_esquema.sql ya incluye estas columnas.
--   La tabla cliente debe estar vacía (aún no hay abonados de operación).
--
-- Con qué se relaciona:
--   - app/models.py (clase Cliente) y app/services/periodo.py (cálculo).
--   - Anexo H, tabla cliente (cambio por registrar en el control de cambios).
-- =====================================================================

ALTER TABLE cliente
    ADD COLUMN fecha_registro DATE NOT NULL AFTER estado,
    ADD COLUMN dia_pago TINYINT UNSIGNED NOT NULL AFTER fecha_vencimiento,
    ADD CONSTRAINT ck_cliente_dia_pago CHECK (dia_pago BETWEEN 1 AND 31);
