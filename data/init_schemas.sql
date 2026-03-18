-- Создание схем для приложения (выполняется при инициализации postgres)
CREATE SCHEMA IF NOT EXISTS public;
CREATE SCHEMA IF NOT EXISTS "references";
CREATE SCHEMA IF NOT EXISTS dct;
CREATE SCHEMA IF NOT EXISTS dcm;
CREATE SCHEMA IF NOT EXISTS stm;

-- search_path для удобства
ALTER DATABASE mock_uto SET search_path TO public, "references", dct;
