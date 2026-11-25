-- Fase 2 · 2: cartas topográficas 1:50 000 de INEGI, unificadas. Las ediciones nombran distinto sus campos
-- (las nuevas: nom_geo, term_gen; las viejas: nombre, geografico): se leen por nombre desde to_jsonb(renglón).

create or replace function pg_temp.campo(j jsonb, variadic nombres text[]) returns text language sql immutable as $$
  select nullif(trim(coalesce(j ->> nombres[1], j ->> nombres[2], j ->> nombres[3])), '')
$$;

drop table if exists base.inegi50_corrientes;
create table base.inegi50_corrientes as
select gid, hoja50 as hoja, edicion50::int as edicion,
       pg_temp.campo(j, 'nom_geo', 'nombre') as nombre,
       pg_temp.campo(j, 'condicion') as condicion,
       pg_temp.campo(j, 'term_gen', 'geografico') as tipo,
       geom::geometry(MultiLineString, 6369) as geom
from (select c.*, to_jsonb(c) - 'geom' as j from base.carga50_corrientes c) x;

drop table if exists base.inegi50_cuerpos_agua;
create table base.inegi50_cuerpos_agua as
select gid, hoja50 as hoja, edicion50::int as edicion,
       pg_temp.campo(j, 'nom_geo', 'nombre') as nombre,
       pg_temp.campo(j, 'condicion') as condicion,
       pg_temp.campo(j, 'term_gen', 'geografico') as tipo,
       geom::geometry(MultiPolygon, 6369) as geom
from (select c.*, to_jsonb(c) - 'geom' as j from base.carga50_cuerpos_agua c) x
union all
select 100000000 + gid, hoja50, edicion50::int,
       pg_temp.campo(j, 'nom_geo', 'nombre'), pg_temp.campo(j, 'condicion'),
       coalesce(pg_temp.campo(j, 'term_gen', 'geografico'), 'Corriente (área)'),
       geom::geometry(MultiPolygon, 6369)
from (select c.*, to_jsonb(c) - 'geom' as j from base.carga50_corrientes_area c) x;

drop table if exists base.inegi50_obras_agua;
create table base.inegi50_obras_agua as
select gid, 'canal' as obra, hoja50 as hoja, edicion50::int as edicion, pg_temp.campo(j, 'nom_geo', 'nombre') as nombre,
       pg_temp.campo(j, 'condicion') as condicion, pg_temp.campo(j, 'term_gen', 'geografico') as tipo,
       geom::geometry(MultiLineString, 6369) as geom
from (select c.*, to_jsonb(c) - 'geom' as j from base.carga50_canales c) x
union all
select 100000000 + gid, 'presa', hoja50, edicion50::int, pg_temp.campo(j, 'nom_geo', 'nombre'), pg_temp.campo(j, 'condicion'),
       pg_temp.campo(j, 'term_gen', 'geografico'), geom::geometry(MultiLineString, 6369)
from (select c.*, to_jsonb(c) - 'geom' as j from base.carga50_presas c) x
union all
select 200000000 + gid, 'bordo', hoja50, edicion50::int, pg_temp.campo(j, 'nom_geo', 'nombre'), pg_temp.campo(j, 'condicion'),
       pg_temp.campo(j, 'term_gen', 'geografico'), geom::geometry(MultiLineString, 6369)
from (select c.*, to_jsonb(c) - 'geom' as j from base.carga50_bordos c) x;

drop table if exists base.inegi50_caminos;
create table base.inegi50_caminos as
select gid, hoja50 as hoja, edicion50::int as edicion, pg_temp.campo(j, 'nom_geo', 'nombre') as nombre,
       pg_temp.campo(j, 'tipo') as tipo, geom::geometry(MultiLineString, 6369) as geom
from (select c.*, to_jsonb(c) - 'geom' as j from base.carga50_caminos c) x;

drop table if exists base.inegi50_carreteras;
create table base.inegi50_carreteras as
select gid, hoja50 as hoja, edicion50::int as edicion,
       pg_temp.campo(j, 'nom_geo', 'nume_carr', 'nombre') as nombre,
       pg_temp.campo(j, 'num_carr', 'numero') as numero,
       pg_temp.campo(j, 'administ') as administracion,
       pg_temp.campo(j, 'condicion') as condicion,
       pg_temp.campo(j, 'pavimento', 'tipo') as pavimento,
       pg_temp.campo(j, 'dere_tran') as derecho_transito,
       pg_temp.campo(j, 'jurisdicci') as jurisdiccion,
       geom::geometry(MultiLineString, 6369) as geom
from (select c.*, to_jsonb(c) - 'geom' as j from base.carga50_carreteras c) x;

do $$
declare
  t text;
begin
  foreach t in array array['inegi50_corrientes', 'inegi50_cuerpos_agua', 'inegi50_obras_agua', 'inegi50_caminos',
                           'inegi50_carreteras'] loop
    execute format('alter table base.%I add primary key (gid)', t);
    execute format('create index on base.%I using gist (geom)', t);
    execute format('analyze base.%I', t);
  end loop;
end $$;

drop table base.carga50_corrientes, base.carga50_corrientes_area, base.carga50_cuerpos_agua, base.carga50_canales,
           base.carga50_presas, base.carga50_bordos, base.carga50_caminos, base.carga50_carreteras;

comment on table base.inegi50_corrientes is 'Corrientes de agua de las cartas topográficas 1:50 000 de INEGI (conjuntos de datos vectoriales, ediciones 2013–2023; la más reciente de cada carta en la caché del proyecto web): nombre, condición (perenne o intermitente) y tipo. Escala 1:50 000: ≈ 25 m de detalle; un cauce de la carta no siempre cae en el fondo del valle del relieve de 1.5 m';
comment on table base.inegi50_cuerpos_agua is 'Cuerpos de agua de las cartas 1:50 000 de INEGI (vasos de presas y bordos, pozas, lagunas) y corrientes de área (tipo «Corriente (área)»): nombre, condición y tipo';
comment on table base.inegi50_obras_agua is 'Canales, cortinas de presas y bordos de las cartas 1:50 000 de INEGI';
comment on table base.inegi50_caminos is 'Caminos (terracerías, brechas, veredas) de las cartas 1:50 000 de INEGI';
comment on table base.inegi50_carreteras is 'Carreteras de las cartas 1:50 000 de INEGI: número, administración, condición, pavimento, derecho de tránsito';
