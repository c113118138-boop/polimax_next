\set ON_ERROR_STOP on

BEGIN;
SET LOCAL lock_timeout = '10s';

CREATE FUNCTION public.polimax_sync_location()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.location := CASE
        WHEN NEW.longitude BETWEEN -180 AND 180
         AND NEW.latitude BETWEEN -90 AND 90
        THEN ST_SetSRID(ST_MakePoint(
            NEW.longitude::double precision,
            NEW.latitude::double precision
        ), 4326)::geography
        ELSE NULL
    END;
    RETURN NEW;
END;
$$;

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['gps_readings', 'new_reports', 'FindMy']
    LOOP
        EXECUTE format(
            'ALTER TABLE public.%I ADD COLUMN location geography(Point, 4326)',
            table_name
        );
        EXECUTE format(
            'CREATE TRIGGER polimax_sync_location
             BEFORE INSERT OR UPDATE ON public.%I
             FOR EACH ROW EXECUTE FUNCTION public.polimax_sync_location()',
            table_name
        );
        -- The trigger computes location for each existing row.
        EXECUTE format('UPDATE public.%I SET location = NULL', table_name);
        EXECUTE format(
            'CREATE INDEX %I ON public.%I USING GIST (location)',
            table_name || '_location_gist', table_name
        );
    END LOOP;
END;
$$;

COMMIT;

SELECT 'gps_readings' AS table_name, count(*) AS total,
       count(location) AS with_location
FROM public.gps_readings
UNION ALL
SELECT 'new_reports', count(*), count(location)
FROM public.new_reports
UNION ALL
SELECT 'FindMy', count(*), count(location)
FROM public."FindMy";
