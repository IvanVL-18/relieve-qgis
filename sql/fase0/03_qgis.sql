-- Fase 0 · 3: capas de QGIS a partir de relieve (puntos lon/lat y GeoJSON en jsonb) y base, todas en EPSG:6369,
-- con llave primaria, índice espacial y los comentarios de su tabla de origen.
-- Las tablas sin lugar propio (series de tiempo, balances, mediciones) se quedan en relieve: QGIS las une por clave.

-- ── 1. Puntos: toda tabla de relieve con lon y lat ───────────────────────────────────────────────────────────────
-- Se omiten las filas sin coordenadas (en repda_*, ubicacion = sin_lugar); la validación las cuenta.
do $$
declare
  t record;
begin
  for t in
    select c.table_name
    from information_schema.columns c
    join information_schema.tables tb on tb.table_schema = c.table_schema and tb.table_name = c.table_name
    where c.table_schema = 'relieve' and tb.table_type = 'BASE TABLE' and c.column_name in ('lon', 'lat')
    group by c.table_name
    having count(*) = 2
    order by c.table_name
  loop
    execute format('drop table if exists qgis.%I', t.table_name);
    execute format($q$
      create table qgis.%1$I as
      select r.*, meta.punto(r.lon, r.lat)::geometry(Point, 6369) as geom
      from relieve.%1$I r
      where r.lon is not null and r.lat is not null$q$, t.table_name);
    perform meta.preparar_capa(format('qgis.%I', t.table_name)::regclass, format('relieve.%I', t.table_name)::regclass);
    raise notice 'qgis.% (puntos)', t.table_name;
  end loop;
end $$;

-- ── 2. Tablas por localidad: el punto de su localidad del ITER ──────────────────────────────────────────────────
do $$
declare
  t text;
begin
  foreach t in array array['agua_localidades', 'agua_prioridad'] loop
    execute format('drop table if exists qgis.%I', t);
    execute format($q$
      create table qgis.%1$I as
      select r.*, l.geom
      from relieve.%1$I r
      join qgis.localidades l using (cvegeo)$q$, t);
    perform meta.preparar_capa(format('qgis.%I', t)::regclass, format('relieve.%I', t)::regclass);
    raise notice 'qgis.% (punto de su localidad)', t;
  end loop;
end $$;

-- ── 3. Líneas y polígonos que venían como GeoJSON ───────────────────────────────────────────────────────────────
do $$
begin
  drop table if exists qgis.rios;
  execute format($q$
    create table qgis.rios as
    select %s, meta.de_geojson(r.geom)::geometry(LineString, 6369) as geom
    from relieve.rios r$q$, meta.columnas('relieve.rios', 'r', '{geom}'));
  perform meta.preparar_capa('qgis.rios', 'relieve.rios');

  drop table if exists qgis.culturas_rutas;
  execute format($q$
    create table qgis.culturas_rutas as
    select %s, meta.de_geojson(r.geom)::geometry(LineString, 6369) as geom
    from relieve.culturas_rutas r$q$, meta.columnas('relieve.culturas_rutas', 'r', '{geom}'));
  perform meta.preparar_capa('qgis.culturas_rutas', 'relieve.culturas_rutas');

  -- Uso de suelo: 37 polígonos inválidos en el origen se reparan con ST_MakeValid (solo se conservan las partes de área).
  drop table if exists qgis.uso_suelo;
  execute format($q$
    create table qgis.uso_suelo as
    select %s, g.nombre as grupo_nombre, g.color as grupo_color,
           ST_Multi(ST_CollectionExtract(ST_MakeValid(meta.de_geojson(r.geom)), 3))::geometry(MultiPolygon, 6369) as geom
    from relieve.uso_suelo r
    left join relieve.uso_suelo_grupos g on g.id = r.grupo$q$, meta.columnas('relieve.uso_suelo', 'r', '{geom}'));
  alter table qgis.uso_suelo add column area_ha double precision;
  update qgis.uso_suelo set area_ha = ST_Area(ST_Transform(geom, 4326)::geography) / 1e4;
  perform meta.preparar_capa('qgis.uso_suelo', 'relieve.uso_suelo');
  comment on column qgis.uso_suelo.area_ha is 'Área elipsoidal del polígono en hectáreas';
  raise notice 'qgis.rios, qgis.culturas_rutas, qgis.uso_suelo';
end $$;

-- ── 4. Red vial: cada tramo como recta entre sus dos nodos ──────────────────────────────────────────────────────
-- relieve.red_vial no guarda la forma de los tramos: es un grafo para calcular rutas. recta_m y forma_aproximada
-- dicen cuándo la recta se aleja del camino real (largo_m del camino > 1.2 × la recta).
drop table if exists qgis.red_vial;
create table qgis.red_vial as
select v.*, round(ST_Distance(a.geom, b.geom)::numeric, 1)::real as recta_m,
       v.largo_m > 1.2 * ST_Distance(a.geom, b.geom) as forma_aproximada,
       ST_MakeLine(a.geom, b.geom)::geometry(LineString, 6369) as geom
from relieve.red_vial v
join qgis.red_vial_nodos a on a.id = v.nodo_a
join qgis.red_vial_nodos b on b.id = v.nodo_b;
select meta.preparar_capa('qgis.red_vial', 'relieve.red_vial');
comment on column qgis.red_vial.recta_m is 'Distancia en línea recta entre los dos nodos del tramo (m)';
comment on column qgis.red_vial.forma_aproximada is 'Verdadero si el camino real (largo_m) mide más de 1.2 veces la recta: la línea dibujada no sigue sus curvas';

-- ── 5. Municipios: polígono de INEGI (dic. 2025) con los indicadores del proyecto web ───────────────────────────
-- Columnas de relieve.municipios tal cual (sin su area_km2: aquí va la elipsoidal del polígono de 2025) y las de cada
-- tabla *_municipios con prefijo.
do $$
declare
  sel   text;
  joins text := '';
  t     record;
begin
  sel := 'b.cvegeo, b.cve_mun, b.nombre, b.area_km2, '
         || meta.columnas('relieve.municipios', 'm', '{cve,id,nombre,area_km2}');
  for t in
    select * from (values
      ('edificios_municipios', 'edif_'), ('laderas_municipios', 'laderas_'), ('potencial_municipios', 'potencial_'),
      ('recarga_municipios', 'recarga_'), ('solar_municipios', 'solar_'), ('volcanes_municipios', 'volcanes_')
    ) as v(tabla, prefijo)
  loop
    sel   := sel || ', ' || meta.columnas(format('relieve.%I', t.tabla)::regclass, t.tabla, '{cve_mun}', t.prefijo);
    joins := joins || format(' left join relieve.%1$I on %1$I.cve_mun = b.cve_mun', t.tabla);
  end loop;
  drop table if exists qgis.municipios;
  execute format($q$
    create table qgis.municipios as
    select %s, rg.region_id, rg.region, b.geom
    from base.municipios b
    left join relieve.municipios m on m.id = b.cve_mun
    left join relieve.regiones_geoculturales rg on rg.cve_mun = b.cve_mun
    %s$q$, sel, joins);
  perform meta.preparar_capa('qgis.municipios', 'relieve.municipios', 'cvegeo');
  comment on table qgis.municipios is 'Municipios de Hidalgo: polígono de INEGI (Marco Geoestadístico de dic. 2025, area_km2 elipsoidal) con relieve.municipios (población ITER 2020, marginación CONAPO 2020, relieve a 30 m, uso de suelo) y, con prefijo, edificios (edif_), laderas (laderas_), potencial de agua subterránea (potencial_), recarga (recarga_), radiación solar (solar_) y roca volcánica (volcanes_) por municipio, más su región geocultural';
  raise notice 'qgis.municipios';
end $$;

-- ── 6. Polígonos armados con municipios: regiones geoculturales y provincias hacia 1500 ─────────────────────────
drop table if exists qgis.regiones_geoculturales;
create table qgis.regiones_geoculturales as
select rg.region_id, rg.region, count(*)::int as municipios,
       string_agg(b.nombre, ', ' order by b.nombre) as lista,
       sum(b.area_km2) as area_km2,
       ST_Multi(ST_Union(b.geom))::geometry(MultiPolygon, 6369) as geom
from relieve.regiones_geoculturales rg
join base.municipios b on b.cve_mun = rg.cve_mun
group by rg.region_id, rg.region;
select meta.preparar_capa('qgis.regiones_geoculturales', null, 'region_id');
comment on table qgis.regiones_geoculturales is 'Regiones geoculturales (Secretaría de Cultura del Estado de Hidalgo, 2019), unión de los polígonos municipales de INEGI de dic. 2025; el número de regiones y sus límites cambian según la fuente';

drop table if exists qgis.culturas_provincias;
create table qgis.culturas_provincias as
select p.provincia, p.nombre, p.tipo, min(p.cabecera) as cabecera, min(p.tributo) as tributo,
       string_agg(b.nombre, ', ' order by b.nombre) as municipios_hoy,
       ST_Multi(ST_Union(b.geom))::geometry(MultiPolygon, 6369) as geom
from relieve.culturas_provincias p
join base.municipios b on b.cve_mun = p.cve_mun
group by p.provincia, p.nombre, p.tipo;
select meta.preparar_capa('qgis.culturas_provincias', 'relieve.culturas_provincias', 'provincia');
comment on table qgis.culturas_provincias is 'Provincias tributarias de la Triple Alianza, señoríos de Texcoco e independientes hacia 1500, aproximadas por la unión de los municipios de hoy donde estaban sus pueblos (relieve.culturas_provincias): el contorno es el de los municipios actuales, no el de la provincia';

-- ── 7. Acuíferos y ordenamientos: polígono de CONAGUA recortado al límite de Hidalgo ────────────────────────────
-- Recorte simple: en la orilla quedan franjas angostas de acuíferos de otros estados (el proyecto web pasa las de
-- menos de 250 m al acuífero de Hidalgo de al lado; aquí no).
do $$
begin
  drop table if exists qgis.acuiferos;
  execute format($q$
    create table qgis.acuiferos as
    select %s, %s, %s,
           ST_Multi(ST_CollectionExtract(ST_Intersection(a.geom, e.geom), 3))::geometry(MultiPolygon, 6369) as geom
    from relieve.acuiferos r
    join base.acuiferos a on a.clave = trim(r.clave)
    cross join base.estado e
    left join relieve.recarga_acuiferos ra on ra.clave = r.clave
    left join relieve.calidad_agua_acuiferos ca on ca.clave = r.clave$q$,
    meta.columnas('relieve.acuiferos', 'r'),
    meta.columnas('relieve.recarga_acuiferos', 'ra', '{clave}', 'recarga_'),
    meta.columnas('relieve.calidad_agua_acuiferos', 'ca', '{clave,nombre}', 'calidad_'));
  perform meta.preparar_capa('qgis.acuiferos', 'relieve.acuiferos');
  comment on table qgis.acuiferos is 'Acuíferos con territorio de Hidalgo: polígono de CONAGUA (DOF 9-nov-2023) recortado al límite de INEGI de dic. 2025, con relieve.acuiferos (disponibilidad, parte de Hidalgo), recarga_* (relieve.recarga_acuiferos) y calidad_* (relieve.calidad_agua_acuiferos). En la orilla quedan franjas angostas de acuíferos vecinos (de_hidalgo = falso)';

  drop table if exists qgis.ordenamientos_agua;
  create table qgis.ordenamientos_agua as
  select r.*,
         (select ST_Multi(ST_CollectionExtract(ST_Intersection(ST_Union(o.geom), e.geom), 3))
          from base.ordenamientos o
          where o.tipo = r.tipo and o.nombre = r.nombre
            and (r.tipo = 'veda' or o.acuifero = trim(r.acuifero)))::geometry(MultiPolygon, 6369) as geom
  from relieve.ordenamientos_agua r
  cross join base.estado e;
  perform meta.preparar_capa('qgis.ordenamientos_agua', 'relieve.ordenamientos_agua');
  raise notice 'qgis.acuiferos, qgis.ordenamientos_agua';
end $$;

-- ── 8. Movilidad: línea del municipio de origen al de destino (o a la entidad) ──────────────────────────────────
-- Une puntos interiores de los polígonos (ST_PointOnSurface): dice quién va a dónde, no por qué camino.
drop table if exists qgis.movilidad_flujos;
create table qgis.movilidad_flujos as
with destinos as (
  select cvegeo, nombre, ST_PointOnSurface(geom) as p from base.municipios
  union all
  select cvegeo, nombre, ST_PointOnSurface(geom) from base.municipios_edomex
  union all
  select cvegeo, nombre, ST_PointOnSurface(geom) from base.entidades
)
select f.*, ST_MakeLine(ST_PointOnSurface(o.geom), d.p)::geometry(LineString, 6369) as geom
from relieve.movilidad_flujos f
join base.municipios o on o.cve_mun = f.cve_mun_origen
left join destinos d on d.cvegeo = f.destino_clave;
select meta.preparar_capa('qgis.movilidad_flujos', 'relieve.movilidad_flujos');
