-- Run once on 163.18.26.228 as the local PostgreSQL administrator:
-- sudo -u postgres psql -X -v ON_ERROR_STOP=1 < /home/c113118138/polimax_next/deploy/create_archive_database.sql
-- No password is embedded. Does not change the source database or delete data.
\set ON_ERROR_STOP on
SELECT format('CREATE DATABASE %I OWNER %I TEMPLATE template0 ENCODING %L',
              'polimax_PostgreSQL_Expired', 'polimax_admin', 'UTF8')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'polimax_PostgreSQL_Expired')
\gexec
REVOKE CONNECT, TEMPORARY ON DATABASE "polimax_PostgreSQL_Expired" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE "polimax_PostgreSQL_Expired" TO polimax_admin;
\connect polimax_PostgreSQL_Expired
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO polimax_admin;
