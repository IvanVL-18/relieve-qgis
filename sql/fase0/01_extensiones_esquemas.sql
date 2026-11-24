-- Fase 0 · 1: extensiones, esquemas y funciones de apoyo.
--
-- El esquema relieve NO se toca: es la carga del proyecto web (pnpm data:db), que lo borra con DROP SCHEMA ... CASCADE
-- cada vez que recarga. Por eso lo nuevo vive aparte y las capas de QGIS son tablas (no vistas): una vista que dependa
-- de relieve desaparecería sin aviso en esa recarga. Si se recarga relieve, basta con volver a correr la fase 0.

create extension if not exists postgis;
create extension if not exists postgis_raster;   -- fase 1: consultar alturas desde SQL (rásters fuera de la base)
create extension if not exists pgrouting;        -- relieve.red_vial ya viene como grafo

create schema if not exists base;
comment on schema base is 'Fuentes oficiales cargadas tal cual (reproyectadas a EPSG:6369 y con geometrías válidas): límites de INEGI, acuíferos y ordenamientos de CONAGUA. Las regenera scripts/fase0.py';

create schema if not exists qgis;
comment on schema qgis is 'Capas listas para QGIS: las tablas de relieve con geometría PostGIS en EPSG:6369, índice espacial y sus comentarios, más uniones con base. Son tablas, no vistas, para sobrevivir a la recarga de relieve. Las regenera scripts/fase0.py';

create schema if not exists meta;
comment on schema meta is 'Catálogo de capas (resolución, fecha y fuente de cada una) y funciones de apoyo';

-- Lista de columnas de una tabla para armar SELECT dinámicos: "alias.col [as prefijo_col], ..." sin las excluidas.
create or replace function meta.columnas(origen regclass, alias text default 'r', excluir text[] default '{}',
                                         prefijo text default '') returns text
language sql stable as $$
  select string_agg(format('%s.%I', alias, attname)
                    || case when prefijo <> '' then format(' as %I', prefijo || attname) else '' end,
                    ', ' order by attnum)
  from pg_attribute
  where attrelid = origen and attnum > 0 and not attisdropped and attname <> all (excluir)
$$;

-- Copia el comentario de la tabla y los de las columnas que se llaman igual.
create or replace function meta.copiar_comentarios(origen regclass, destino regclass) returns void
language plpgsql as $$
declare
  r record;
begin
  execute format('comment on table %s is %L', destino, obj_description(origen, 'pg_class'));
  for r in
    select a.attname, col_description(origen, a.attnum) as c
    from pg_attribute a
    where a.attrelid = origen and a.attnum > 0 and not a.attisdropped and col_description(origen, a.attnum) is not null
  loop
    if exists (select 1 from pg_attribute where attrelid = destino and attname = r.attname and not attisdropped) then
      execute format('comment on column %s.%I is %L', destino, r.attname, r.c);
    end if;
  end loop;
end $$;

-- Deja lista una capa: llave primaria (la dada o la del origen), índice espacial, comentarios del origen y estadísticas.
create or replace function meta.preparar_capa(destino regclass, origen regclass default null, clave text default null)
returns void language plpgsql as $$
declare
  k text := clave;
begin
  if k is null and origen is not null then
    select string_agg(quote_ident(a.attname), ', ' order by x.ord) into k
    from pg_index i
    cross join lateral unnest(i.indkey) with ordinality as x(attnum, ord)
    join pg_attribute a on a.attrelid = i.indrelid and a.attnum = x.attnum
    where i.indrelid = origen and i.indisprimary;
  end if;
  if k is not null then
    execute format('alter table %s add primary key (%s)', destino, k);
  end if;
  if exists (select 1 from pg_attribute where attrelid = destino and attname = 'geom' and not attisdropped) then
    execute format('create index on %s using gist (geom)', destino);
  end if;
  if origen is not null then
    perform meta.copiar_comentarios(origen, destino);
  end if;
  execute format('analyze %s', destino);
end $$;

-- GeoJSON (jsonb, WGS84) del proyecto web → geometría en EPSG:6369 (los polígonos se reparan donde se usan).
create or replace function meta.de_geojson(g jsonb) returns geometry
language sql immutable as $$
  select case when g is null or g = 'null'::jsonb then null
              else ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(g::text), 4326), 6369) end
$$;

-- lon/lat (WGS84) → punto en EPSG:6369. (Una función no conserva el subtipo: quien la usa en CREATE TABLE AS
-- la convierte a geometry(Point, 6369) para que QGIS sepa el tipo sin recorrer la tabla.)
create or replace function meta.punto(lon double precision, lat double precision) returns geometry
language sql immutable as $$
  select case when lon is null or lat is null then null
              else ST_Transform(ST_SetSRID(ST_MakePoint(lon, lat), 4326), 6369) end
$$;
